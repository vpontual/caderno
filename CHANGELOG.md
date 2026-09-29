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
