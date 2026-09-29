# Changelog

## 0.1.0 (unreleased)

First version.

- `caderno` CLI (Python 3.9+, standard library only): `init`, `init --clone`,
  `connect` for Codex, Claude Code and Gemini CLI, `new`, `index`, `check`,
  `sync`, `install-timer` (systemd, launchd, cron), `status`.
- Notebook template: root index with the contract, identity prompts, memory
  and machines folders with generated indexes.
- Secret scanning in a pre-commit hook, with a per-machine denylist.
- Search service (Docker): Postgres + pgvector, any Ollama or
  OpenAI-compatible embedding model, MCP over streamable HTTP with a bearer
  token. Tools: `recall`, `remember` (with duplicate check), `update` (with
  revision history), `forget`, `history`, `context`, `status`.
- Per-agent tokens: `python -m caderno_service.agents add|list|revoke|rotate`,
  read-only or read-write, stored hashed, revocable immediately. Every revision
  records which agent made it (`history` shows it; hand edits show as
  "file edit"). `CADERNO_TOKEN` is now an optional owner token.
- Scale-tested on 764 real notes (see docs/design.md): split indexes past 150
  notes, nested front matter, fewer false secret alarms, batched embedding,
  and `remember` now lists related notes it did not block on.
