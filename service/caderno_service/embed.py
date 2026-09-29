"""Turn text into vectors. Any Ollama or OpenAI-compatible endpoint works."""

from __future__ import annotations

import hashlib
import math

import httpx

from .config import Settings


class EmbedError(RuntimeError):
    pass


class Embedder:
    def __init__(self, s: Settings):
        self.provider = s.embed_provider
        self.url = s.embed_url
        self.model = s.embed_model
        self.key = s.embed_api_key
        self.http = httpx.Client(timeout=120)

    @property
    def label(self) -> str:
        """Stored with each vector so a model change triggers a re-embed."""
        return f"{self.provider}:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            if self.provider == "ollama":
                r = self.http.post(f"{self.url}/api/embed", json={"model": self.model, "input": texts})
                r.raise_for_status()
                return r.json()["embeddings"]
            if self.provider == "openai":
                headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
                r = self.http.post(
                    f"{self.url}/embeddings", json={"model": self.model, "input": texts}, headers=headers
                )
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            if self.provider == "fake":
                return [fake_vector(t) for t in texts]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise EmbedError(f"embedding call to {self.url} ({self.label}) failed: {e}") from e
        raise EmbedError(f"unknown EMBED_PROVIDER '{self.provider}' (use ollama, openai or fake)")


def fake_vector(text: str, dim: int = 256) -> list[float]:
    """Bag-of-words hashing. For tests and trying the service without a model.

    It matches shared words, not meaning, so never use it for real recall.
    """
    v = [0.0] * dim
    for word in text.lower().split():
        w = "".join(ch for ch in word if ch.isalnum())
        if w:
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
