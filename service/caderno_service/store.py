"""The derived index: every note's revisions, with vectors, in Postgres.

Nothing here is the source of truth. `reconcile()` makes the database match
the files, and `rebuild()` throws the database away and starts over. Writes
from agents go to the files first and are indexed from there, so there is
exactly one write path.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from caderno import notes

from .embed import Embedder

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS revisions (
    id           bigserial PRIMARY KEY,
    key          text        NOT NULL,
    rev          integer     NOT NULL,
    status       text        NOT NULL CHECK (status IN ('active', 'superseded', 'retired')),
    description  text        NOT NULL,
    type         text        NOT NULL,
    body         text        NOT NULL,
    content_hash text        NOT NULL,
    embed_model  text        NOT NULL,
    embedding    vector      NOT NULL,
    reason       text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    ended_at     timestamptz,
    UNIQUE (key, rev)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_revision ON revisions (key) WHERE status = 'active';
-- Which agent made a revision through the tools. NULL = the file was edited directly.
ALTER TABLE revisions ADD COLUMN IF NOT EXISTS agent text;
CREATE TABLE IF NOT EXISTS reconcile_log (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    added      integer NOT NULL,
    revised    integer NOT NULL,
    retired    integer NOT NULL,
    reembedded integer NOT NULL,
    error      text
);
"""


def vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


@dataclass
class Result:
    added: list[str] = field(default_factory=list)
    revised: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    reembedded: int = 0

    def summary(self) -> str:
        return (
            f"{len(self.added)} added, {len(self.revised)} revised, "
            f"{len(self.retired)} retired, {self.reembedded} re-embedded"
        )


class Store:
    def __init__(self, database_url: str, notebook: Path, embedder: Embedder):
        self.url = database_url
        self.root = notebook
        self.embedder = embedder
        # One writer at a time: reconcile and the write tools share files and rows.
        self.lock = threading.RLock()
        self.last_reconcile: dt.datetime | None = None
        self.last_error: str | None = None

    def connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, autocommit=False)

    def migrate(self) -> None:
        with self.connect() as c:
            c.execute(SCHEMA)

    # --- files -> database -------------------------------------------------

    def reconcile(self, only: set[str] | None = None) -> Result:
        """Make the active revisions match the files on disk."""
        with self.lock:
            res = Result()
            try:
                files = {n.key: n for n in notes.searchable_notes(self.root)}
                if only is not None:
                    files = {k: v for k, v in files.items() if k in only}
                with self.connect() as c:
                    active = {
                        row[0]: row
                        for row in c.execute(
                            "SELECT key, rev, content_hash, embed_model FROM revisions WHERE status = 'active'"
                        )
                    }
                    if only is not None:
                        active = {k: v for k, v in active.items() if k in only}

                    changed = [n for k, n in files.items() if k not in active or active[k][2] != n.content_hash()]
                    stale_model = [
                        n
                        for k, n in files.items()
                        if k in active and active[k][2] == n.content_hash() and active[k][3] != self.embedder.label
                    ]
                    vectors = self.embedder.embed([n.embed_text() for n in changed + stale_model])
                    for n, v in zip(changed, vectors[: len(changed)]):
                        prev = active.get(n.key)
                        if prev:
                            c.execute(
                                "UPDATE revisions SET status='superseded', ended_at=now() WHERE key=%s AND status='active'",
                                (n.key,),
                            )
                            res.revised.append(n.key)
                        else:
                            res.added.append(n.key)
                        last = c.execute("SELECT coalesce(max(rev), 0) FROM revisions WHERE key=%s", (n.key,)).fetchone()[0]
                        c.execute(
                            "INSERT INTO revisions (key, rev, status, description, type, body, content_hash, embed_model, embedding)"
                            " VALUES (%s, %s, 'active', %s, %s, %s, %s, %s, %s::vector)",
                            (n.key, last + 1, n.description, n.type, n.body.strip(), n.content_hash(), self.embedder.label, vec(v)),
                        )
                    for n, v in zip(stale_model, vectors[len(changed) :]):
                        c.execute(
                            "UPDATE revisions SET embedding=%s::vector, embed_model=%s WHERE key=%s AND status='active'",
                            (vec(v), self.embedder.label, n.key),
                        )
                        res.reembedded += 1
                    for k in sorted(set(active) - set(files)):
                        c.execute("UPDATE revisions SET status='retired', ended_at=now() WHERE key=%s AND status='active'", (k,))
                        res.retired.append(k)
                    if only is None:
                        c.execute(
                            "INSERT INTO reconcile_log (added, revised, retired, reembedded) VALUES (%s, %s, %s, %s)",
                            (len(res.added), len(res.revised), len(res.retired), res.reembedded),
                        )
                self.last_reconcile = dt.datetime.now(dt.timezone.utc)
                self.last_error = None
            except Exception as e:  # recorded for /health, then re-raised
                self.last_error = str(e)
                raise
            return res

    def rebuild(self) -> Result:
        """Throw the index away and rebuild it from the files. History is lost; files are not."""
        with self.lock:
            with self.connect() as c:
                c.execute("TRUNCATE revisions")
            return self.reconcile()

    # --- reads ---------------------------------------------------------------

    def recall(self, query: str, limit: int = 5, type_: str | None = None) -> list[dict]:
        [q] = self.embedder.embed([query])
        sql = (
            "SELECT key, description, type, body, rev, 1 - (embedding <=> %s::vector) AS score, created_at"
            " FROM revisions WHERE status='active' AND embed_model=%s"
        )
        args: list = [vec(q), self.embedder.label]
        if type_:
            sql += " AND type=%s"
            args.append(type_)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        args += [vec(q), limit]
        with self.connect() as c:
            rows = c.execute(sql, args).fetchall()
        return [
            {
                "key": r[0],
                "file": f"{r[0]}.md",
                "description": r[1],
                "type": r[2],
                "body": r[3],
                "revision": r[4],
                "score": round(float(r[5]), 3),
                "since": r[6].date().isoformat(),
            }
            for r in rows
        ]

    def history(self, key: str) -> list[dict]:
        with self.connect() as c:
            rows = c.execute(
                "SELECT rev, status, description, body, created_at, ended_at, reason, agent FROM revisions WHERE key=%s ORDER BY rev",
                (key,),
            ).fetchall()
        return [
            {
                "revision": r[0],
                "status": r[1],
                "description": r[2],
                "body": r[3],
                "from": r[4].isoformat(timespec="seconds"),
                "until": r[5].isoformat(timespec="seconds") if r[5] else None,
                "reason": r[6],
                "by": r[7] or "file edit",
            }
            for r in rows
        ]

    def annotate(self, key: str, agent: str, reason: str | None = None) -> None:
        """Record who made the newest revision of a key through the tools, and why."""
        with self.connect() as c:
            c.execute(
                "UPDATE revisions SET agent=%s, reason=coalesce(%s, reason)"
                " WHERE key=%s AND rev=(SELECT max(rev) FROM revisions WHERE key=%s)",
                (agent, reason, key, key),
            )

    def counts(self) -> dict:
        with self.connect() as c:
            rows = c.execute("SELECT status, count(*) FROM revisions GROUP BY status").fetchall()
        out = {"active": 0, "superseded": 0, "retired": 0}
        out.update({r[0]: r[1] for r in rows})
        return out
