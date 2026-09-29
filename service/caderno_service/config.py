"""Settings, read once from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    notebook: Path
    database_url: str
    token: str
    embed_provider: str  # ollama | openai | fake
    embed_url: str
    embed_model: str
    embed_api_key: str
    embed_batch: int
    reindex_seconds: int
    duplicate_threshold: float
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        # Optional: a full-access token for the owner. Agents should get their own
        # tokens (python -m caderno_service.agents add <name>).
        token = os.environ.get("CADERNO_TOKEN", "")
        if token and len(token) < 24:
            raise SystemExit("CADERNO_TOKEN is too short; use a long random string (openssl rand -hex 32)")
        return cls(
            notebook=Path(os.environ.get("CADERNO_NOTEBOOK_PATH", "/notebook")),
            database_url=os.environ["DATABASE_URL"],
            token=token,
            embed_provider=os.environ.get("EMBED_PROVIDER", "ollama").lower(),
            embed_url=os.environ.get("EMBED_URL", "http://host.docker.internal:11434").rstrip("/"),
            embed_model=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
            embed_api_key=os.environ.get("EMBED_API_KEY", ""),
            embed_batch=int(os.environ.get("EMBED_BATCH", "32")),
            reindex_seconds=int(os.environ.get("REINDEX_SECONDS", "300")),
            duplicate_threshold=float(os.environ.get("DUPLICATE_THRESHOLD", "0.82")),
            port=int(os.environ.get("PORT", "8420")),
        )
