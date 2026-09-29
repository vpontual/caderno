"""MCP server over streamable HTTP. Agents connect with a URL and a bearer token."""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import re
import threading
import time
from pathlib import Path

import anyio
import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request
from starlette.responses import JSONResponse

from caderno import notes

from .agents import Agent, Registry
from .config import Settings
from .embed import Embedder, EmbedError
from .store import Store

log = logging.getLogger("caderno")
# Set per request by BearerAuth; read by the tools to enforce scope and attribute writes.
CURRENT_AGENT: contextvars.ContextVar[Agent | None] = contextvars.ContextVar("caderno_agent", default=None)
WRITE_KEY = re.compile(r"^(memory|machines)/[a-z0-9][a-z0-9-]{0,79}$")

INSTRUCTIONS = """\
caderno is the owner's shared memory across every AI agent and machine they use.
The markdown files are the source of truth; these tools search and edit them.
- Call `recall` before starting work on anything the owner may have told an agent before.
- Call `recall` before `remember`. If the fact already has a note, call `update` on it.
- Never store passwords, tokens or keys. Say where the secret is kept instead.
- Only save durable facts: corrections, decisions, setup, lessons. Not session scratch.
"""


def build(s: Settings) -> tuple[MCPServer, Store, Registry]:
    embedder = Embedder(s)
    store = Store(s.database_url, s.notebook, embedder)
    registry = Registry(s.database_url, s.token)
    mcp = MCPServer("caderno", instructions=INSTRUCTIONS, version="0.1.0")

    def run(fn, *args):
        return anyio.to_thread.run_sync(lambda: fn(*args))

    def check_key(key: str) -> Path:
        key = key.removesuffix(".md").strip("/")
        if not WRITE_KEY.match(key):
            raise ToolError(f"'{key}' is not a note key; keys look like memory/some-note or machines/some-host")
        return s.notebook / f"{key}.md"

    def refuse_secrets(*texts: str) -> None:
        for t in texts:
            hits = notes.scan_text(t or "")
            if hits:
                raise ToolError(
                    f"refused: this looks like it contains a secret ({hits[0][1]}). "
                    "Store where the secret lives, not the secret itself."
                )

    def caller() -> Agent:
        agent = CURRENT_AGENT.get()
        if agent is None:  # BearerAuth guarantees this is set; fail closed if it is not
            raise ToolError("no agent identity on this request")
        return agent

    def require_write() -> Agent:
        agent = caller()
        if not agent.can_write:
            raise ToolError(f"agent '{agent.name}' is read-only; it can recall, history, context and status")
        return agent

    def after_write(key: str, agent: Agent, reason: str | None = None) -> None:
        notes.write_indexes(s.notebook)
        store.reconcile(only={key})
        store.annotate(key, agent.name, reason)

    @mcp.tool()
    async def recall(query: str, limit: int = 5, type: str | None = None) -> dict:
        """Search every note by meaning. Returns the closest active notes, best first.

        Args:
            query: what you want to know, in plain words
            limit: how many notes to return (1-20)
            type: optionally only one kind: lesson, preference, project, person, machine, reference
        """
        found = await run(store.recall, query, max(1, min(limit, 20)), type)
        return {"results": found}

    @mcp.tool()
    async def remember(
        description: str, body: str, type: str = "lesson", name: str | None = None, force: bool = False
    ) -> dict:
        """Save a new durable fact as a note. Checks for an existing note on the same thing first.

        Args:
            description: one line a future agent reads to decide whether to open the note
            body: the fact, and why it matters
            type: lesson, preference, project, person, machine or reference
            name: file name, lowercase-with-dashes (default: made from the description)
            force: save even though similar notes exist (only when it is truly a different fact)
        """
        agent = require_write()
        if type not in notes.NOTE_TYPES:
            raise ToolError(f"type must be one of {', '.join(notes.NOTE_TYPES)}")
        refuse_secrets(description, body)
        folder = "machines" if type == "machine" else "memory"
        key = f"{folder}/{name or notes.slugify(description)}"
        path = check_key(key)
        if path.exists():
            return {"saved": False, "reason": f"{key} already exists", "next": f"call update with key '{key}'"}
        similar = await run(store.recall, f"{description}\n\n{body}", 3, None)
        if not force:
            dupes = [r for r in similar if r["score"] >= s.duplicate_threshold]
            if dupes:
                return {
                    "saved": False,
                    "reason": "notes on something similar already exist",
                    "possible_duplicates": [{k: d[k] for k in ("key", "description", "score")} for d in dupes],
                    "next": "call update on the matching key, or call remember again with force=true "
                    "if this is a different fact",
                }

        def write():
            with store.lock:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(notes.render({"description": description, "type": type}, body), encoding="utf-8")
                after_write(key, agent)

        await run(write)
        out = {"saved": True, "key": key, "file": f"{key}.md"}
        # Similarity cannot tell "same fact" from "related fact" reliably (measured:
        # true duplicates scored 0.76-0.87 while 44% of notes had a neighbour >= 0.75),
        # so below the block threshold the agent is shown close notes and decides.
        related = [r for r in similar if r["score"] >= s.duplicate_threshold - 0.12]
        if related:
            out["related"] = [{k: r[k] for k in ("key", "description", "score")} for r in related]
            out["next"] = "if one of these says the same thing, merge them: update it and forget this one"
        return out

    @mcp.tool()
    async def update(
        key: str, reason: str, description: str | None = None, body: str | None = None, type: str | None = None
    ) -> dict:
        """Correct or extend an existing note. The old version stays in history, out of search.

        Args:
            key: the note's key, e.g. memory/newsfeed-deploys (from recall)
            reason: why it changed, in a few words
            description: new one-line description (omit to keep)
            body: the full new body (omit to keep); replaces the old body, so include what still holds
            type: new type (omit to keep)
        """
        agent = require_write()
        path = check_key(key)
        key = key.removesuffix(".md").strip("/")
        if not path.exists():
            raise ToolError(f"no note at {key}; use recall to find the right key, or remember to create one")
        refuse_secrets(description or "", body or "")
        if type is not None and type not in notes.NOTE_TYPES:
            raise ToolError(f"type must be one of {', '.join(notes.NOTE_TYPES)}")

        def write():
            with store.lock:
                meta, old_body = notes.parse(path.read_text(encoding="utf-8"))
                if description is not None:
                    meta["description"] = description
                if type is not None:
                    meta["type"] = type
                path.write_text(notes.render(meta, body if body is not None else old_body), encoding="utf-8")
                after_write(key, agent, reason)

        await run(write)
        hist = await run(store.history, key)
        return {"updated": True, "key": key, "revision": hist[-1]["revision"] if hist else None}

    @mcp.tool()
    async def forget(key: str, reason: str) -> dict:
        """Retire a note that is no longer true. It moves to an _archive folder and leaves search.

        Args:
            key: the note's key, e.g. memory/old-setup
            reason: why it no longer applies
        """
        agent = require_write()
        path = check_key(key)
        key = key.removesuffix(".md").strip("/")
        if not path.exists():
            raise ToolError(f"no note at {key}")

        def move():
            with store.lock:
                folder, name = key.split("/", 1)
                dest = s.notebook / folder / notes.ARCHIVE_DIR / f"{name}.md"
                dest.parent.mkdir(parents=True, exist_ok=True)
                meta, body = notes.parse(path.read_text(encoding="utf-8"))
                meta["retired"] = f"{dt.date.today().isoformat()}: {reason}"
                dest.write_text(notes.render(meta, body), encoding="utf-8")
                path.unlink()
                after_write(key, agent, reason)
                return dest.relative_to(s.notebook).as_posix()

        archived = await run(move)
        return {"forgotten": True, "key": key, "archived_to": archived}

    @mcp.tool()
    async def history(key: str) -> dict:
        """Every revision of a note, oldest first, with why each one changed."""
        key = key.removesuffix(".md").strip("/")
        return {"key": key, "revisions": await run(store.history, key)}

    @mcp.tool()
    async def context() -> dict:
        """The notebook's index and the files to read every session. For machines without a copy of the notebook."""

        def read():
            files = ["INDEX.md", "identity/profile.md", "identity/rules.md", "identity/voice.md"]
            return {f: (s.notebook / f).read_text(encoding="utf-8") for f in files if (s.notebook / f).exists()}

        return {"files": await run(read)}

    @mcp.tool()
    async def status() -> dict:
        """How healthy the index is: note counts, embedding model, last reconcile."""
        c = await run(store.counts)
        me = caller()
        return {
            "you": {"agent": me.name, "can_write": me.can_write},
            "notes": c,
            "embedding_model": embedder.label,
            "last_reconcile": store.last_reconcile.isoformat(timespec="seconds") if store.last_reconcile else None,
            "last_error": store.last_error,
        }

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        ok = store.last_reconcile is not None and store.last_error is None
        return JSONResponse({"ok": ok}, status_code=200 if ok else 503)

    return mcp, store, registry


class BearerAuth:
    """Every request except /health needs `Authorization: Bearer <token>` of a known agent."""

    def __init__(self, app, registry: Registry):
        self.app = app
        self.registry = registry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode("latin-1")
        token = header[7:].strip() if header[:7].lower() == "bearer " else ""
        try:
            agent = await anyio.to_thread.run_sync(self.registry.resolve, token)
        except Exception:
            log.exception("token lookup failed")
            agent = None
        if agent is None:
            body = json.dumps({"error": "missing, wrong or revoked bearer token"}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        reset = CURRENT_AGENT.set(agent)
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT_AGENT.reset(reset)


def reconcile_loop(store: Store, every: int) -> None:
    while True:
        time.sleep(every)
        try:
            r = store.reconcile()
            if r.added or r.revised or r.retired or r.reembedded:
                log.info("reconcile: %s", r.summary())
        except EmbedError as e:
            log.error("reconcile: %s", e)
        except Exception:
            log.exception("reconcile failed")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = Settings.from_env()
    mcp, store, registry = build(s)
    for attempt in range(30):  # the database may still be starting
        try:
            store.migrate()
            registry.migrate()
            break
        except Exception as e:
            log.info("waiting for database (%s)", e.__class__.__name__)
            time.sleep(2)
    else:
        raise SystemExit("database never came up")
    try:
        first = store.reconcile()
        log.info("indexed %s from %s using %s", first.summary(), s.notebook, store.embedder.label)
    except Exception as e:  # keep serving; /health reports 503 until the next loop succeeds
        log.error("first index failed, will retry every %ss: %s", s.reindex_seconds, e)
    threading.Thread(target=reconcile_loop, args=(store, s.reindex_seconds), daemon=True).start()
    if not s.token and not registry.list():
        log.warning(
            "no CADERNO_TOKEN and no agents yet, so nothing can connect. Add one: "
            "docker compose exec api python -m caderno_service.agents add <name>"
        )
    app = BearerAuth(mcp.streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0"), registry)
    uvicorn.run(app, host="0.0.0.0", port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
