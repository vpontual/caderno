"""Per-agent tokens: each agent gets its own token, scope and name on every write.

    docker compose exec api python -m caderno_service.agents add codex-laptop
    docker compose exec api python -m caderno_service.agents add openwebui --read-only
    docker compose exec api python -m caderno_service.agents list
    docker compose exec api python -m caderno_service.agents revoke codex-laptop

Only a SHA-256 of each token is stored. The token itself is printed once, at
`add`, and cannot be shown again; `rotate` issues a new one.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import re
import secrets
import sys
from dataclasses import dataclass

import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name        text PRIMARY KEY,
    token_hash  text NOT NULL UNIQUE,
    scope       text NOT NULL CHECK (scope IN ('read', 'write')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz,
    revoked_at  timestamptz
);
"""

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
TOKEN_PREFIX = "cad_"  # also matched by caderno's secret scanner, so a leaked token is caught
READ_TOOLS = frozenset({"recall", "history", "context", "status"})


@dataclass(frozen=True)
class Agent:
    name: str
    scope: str  # "read" or "write"

    @property
    def can_write(self) -> bool:
        return self.scope == "write"


OWNER = Agent("owner", "write")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_hex(32)


class Registry:
    def __init__(self, database_url: str, owner_token: str = ""):
        self.url = database_url
        self.owner_hash = token_hash(owner_token) if owner_token else None

    def migrate(self) -> None:
        with psycopg.connect(self.url) as c:
            c.execute(SCHEMA)

    def resolve(self, token: str) -> Agent | None:
        """The agent a bearer token belongs to, or None. Revocation takes effect at once."""
        if not token:
            return None
        h = token_hash(token)
        if self.owner_hash and hmac.compare_digest(h, self.owner_hash):
            return OWNER
        with psycopg.connect(self.url, autocommit=True) as c:
            row = c.execute(
                "UPDATE agents SET last_seen = now() WHERE token_hash = %s AND revoked_at IS NULL RETURNING name, scope",
                (h,),
            ).fetchone()
        return Agent(row[0], row[1]) if row else None

    def add(self, name: str, scope: str) -> str:
        if not NAME_RE.match(name) or name == OWNER.name:
            raise ValueError(f"'{name}' is not a usable name: lowercase letters, digits, . _ - (and not 'owner')")
        token = new_token()
        with psycopg.connect(self.url) as c:
            if c.execute("SELECT 1 FROM agents WHERE name = %s", (name,)).fetchone():
                raise ValueError(f"an agent called '{name}' already exists (use rotate, or revoke it first)")
            c.execute("INSERT INTO agents (name, token_hash, scope) VALUES (%s, %s, %s)", (name, token_hash(token), scope))
        return token

    def rotate(self, name: str) -> str:
        token = new_token()
        with psycopg.connect(self.url) as c:
            r = c.execute(
                "UPDATE agents SET token_hash = %s, revoked_at = NULL WHERE name = %s RETURNING name",
                (token_hash(token), name),
            ).fetchone()
        if not r:
            raise ValueError(f"no agent called '{name}'")
        return token

    def revoke(self, name: str) -> bool:
        with psycopg.connect(self.url) as c:
            r = c.execute(
                "UPDATE agents SET revoked_at = now() WHERE name = %s AND revoked_at IS NULL RETURNING name", (name,)
            ).fetchone()
        return bool(r)

    def list(self) -> list[tuple]:
        with psycopg.connect(self.url) as c:
            return c.execute(
                "SELECT name, scope, created_at, last_seen, revoked_at FROM agents ORDER BY name"
            ).fetchall()


def main(argv: list[str] | None = None) -> int:
    from .config import Settings

    ap = argparse.ArgumentParser(prog="python -m caderno_service.agents", description="Manage agent tokens.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add", help="create an agent and print its token (shown once)")
    p.add_argument("name")
    p.add_argument("--read-only", action="store_true", help="recall, history, context and status only")
    sub.add_parser("list", help="every agent, its scope and when it was last seen")
    p = sub.add_parser("revoke", help="stop a token working, immediately")
    p.add_argument("name")
    p = sub.add_parser("rotate", help="issue a new token for an agent (the old one stops working)")
    p.add_argument("name")
    a = ap.parse_args(argv)

    s = Settings.from_env()
    reg = Registry(s.database_url, s.token)
    reg.migrate()
    try:
        if a.cmd == "add":
            token = reg.add(a.name, "read" if a.read_only else "write")
            print(f"Created {a.name} ({'read-only' if a.read_only else 'read and write'}). Its token, shown once:\n")
            print(token)
            print("\nGive it to that agent through an environment variable, never a committed file.")
        elif a.cmd == "rotate":
            print(reg.rotate(a.name))
        elif a.cmd == "revoke":
            print(f"revoked {a.name}" if reg.revoke(a.name) else f"no active agent called {a.name}")
        else:
            rows = reg.list()
            if not rows:
                print("No agents yet. Add one: python -m caderno_service.agents add <name> [--read-only]")
            for name, scope, created, seen, revoked in rows:
                state = f"revoked {revoked:%Y-%m-%d}" if revoked else f"last seen {seen:%Y-%m-%d %H:%M}" if seen else "never used"
                print(f"{name:<24} {scope:<6} created {created:%Y-%m-%d}  {state}")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
