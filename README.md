# Caderno

**One notebook that every AI agent you use can read, on every machine you own.**

*Caderno* is Portuguese for notebook. This one holds what your agents need to
know to work with you: who you are, your hard rules, how your machines are set
up, and every lesson learned the hard way. Codex, Claude Code, Gemini CLI and
local models all read the same plain markdown files, so you tell one agent
something once and every agent knows it.

- **Plain markdown in git.** You can read, grep, edit and version every word.
  Nothing is locked inside a vendor or a database.
- **An index, not a dump.** A few small files load every session. Everything
  else sits behind one-line descriptions, and an agent opens a note only when
  the description matches the task.
- **Corrections replace facts instead of piling up.** When something changes,
  the note is updated. With the optional search service, old revisions stay in
  history but never come back in search.
- **Grows with you.** A folder works this afternoon with no code at all. Sync,
  semantic search and automatic cleanup are layers you add when you miss them.

## Where it fits

Built-in memory in ChatGPT or Claude is fine if you use one vendor on one
device. Caderno is for people who use several agents on several machines and
want one memory they own. It is a pattern and a small starter kit, not a
hosted product: you run it, you customize it, and it is yours.

| | Built-in vendor memory | Database-first memory services | Caderno |
| --- | --- | --- | --- |
| Where the memory lives | the vendor's servers | a database | markdown files in your git repo |
| Works across agents | no | through their API | yes, anything that reads a file |
| You can read and edit it | partly | through their tools | with any editor |
| Needs a server | no | yes | no (optional for search) |
| Corrections | varies | varies | enforced: update, never duplicate |

## Five-minute start

Requirements: Python 3.9+ and git. Nothing else for the notebook itself.

```bash
git clone https://github.com/vpontual/caderno.git ~/.local/share/caderno-kit
~/.local/share/caderno-kit/bin/caderno init        # creates ~/caderno, asks 3 questions
caderno connect                                    # points Codex / Claude Code / Gemini at it
```

`connect` adds a short, clearly marked block to `~/.codex/AGENTS.md`,
`~/.claude/CLAUDE.md` and `~/.gemini/GEMINI.md` (only for the agents you have
installed). The rest of those files is left alone, and `caderno connect --remove`
takes it back out.

Then fill in `~/caderno/identity/` yourself, or let your agent do it:

> Read ~/.local/share/caderno-kit/SETUP-WITH-AN-AGENT.md and set up my caderno.

That file is written for the agent: it interviews you, writes your profile and
rules, sets up sync and, if you want it, the search service.

## The layers

Each layer is useful on its own. Stop at any of them.

| Layer | What you get | What it needs |
| --- | --- | --- |
| **0. The notebook** | Every agent reads your profile, rules and notes | nothing |
| **1. Sync** | The same notebook on every machine, every few minutes | a private git remote |
| **2. Search** | `recall`, `remember`, `update`, `forget`, `history` as MCP tools; search by meaning | Docker, one always-on machine, any embedding model |
| **3. Self-cleaning** | Overnight merging of near-duplicate notes | an LLM you can run on a schedule; see [docs/layer-3.md](docs/layer-3.md) |

### 1. Sync

```bash
caderno remote git@github.com:you/my-caderno.git   # a PRIVATE repo
caderno sync                                        # pull, reindex, commit, push
caderno install-timer                               # every 5 min (systemd, launchd or cron)
```

On each other machine, join the same notebook:

```bash
~/.local/share/caderno-kit/bin/caderno init --clone git@github.com:you/my-caderno.git
caderno connect && caderno install-timer
```

A pre-commit hook scans every commit for passwords, tokens and private keys and
refuses the commit if it finds one. Add your own never-commit strings (real
hostnames, account names) to `~/.config/caderno/denylist`, which stays on that
machine.

### 2. Search

The search service indexes the notebook into Postgres with pgvector and serves
it to agents over MCP (streamable HTTP, bearer token). The files stay the source
of truth: agent writes go to the files first, hand edits and synced changes are
picked up every few minutes, and the whole index can be rebuilt from the files
at any time.

```bash
cd ~/.local/share/caderno-kit/service
cp .env.example .env          # set the notebook path, two secrets, your embedding model
docker compose up -d
curl -s localhost:8420/health # {"ok": true}
```

Any embedding model works: Ollama (`nomic-embed-text` or `qwen3-embedding:0.6b`
run fine on a CPU), or any OpenAI-compatible endpoint such as vLLM, LM Studio,
llama.cpp or OpenAI itself. No GPU is required.

Connect your agents:

```bash
# Codex
export CADERNO_TOKEN=...      # in your shell profile
codex mcp add caderno --url http://127.0.0.1:8420/mcp --bearer-token-env-var CADERNO_TOKEN

# Claude Code
claude mcp add --scope user --transport http caderno http://127.0.0.1:8420/mcp \
  --header "Authorization: Bearer $CADERNO_TOKEN"
```

The tools:

| Tool | Does |
| --- | --- |
| `recall` | search every note by meaning |
| `remember` | save a new note; refuses if a similar note exists and points at it instead |
| `update` | correct a note; the old version moves to history with the reason |
| `forget` | retire a note to `_archive/`; it leaves search but stays in git |
| `history` | every revision of a note and why it changed |
| `context` | the index and every-session files, for a machine with no copy of the notebook |
| `status` | note counts, embedding model, last index run |

`remember` and `update` also refuse text that looks like a secret.

**Reaching it from other machines.** The service listens on `127.0.0.1` only.
To share it, set `CADERNO_BIND=0.0.0.0` in `.env`, and only over a private
network such as WireGuard or Tailscale, or behind a reverse proxy that adds TLS.
The token travels in plain text over plain HTTP.

## The contract

The notebook's own `INDEX.md` tells every agent these rules, and the service
enforces the ones code can check:

1. **Look before you write.** Search for an existing note first.
2. **Correct, don't duplicate.** A changed fact is an edit, never a second note.
3. **One fact per note,** with a sharp one-line description.
4. **Durable only.** Decisions, corrections, setup, lessons. Not scratch work.
5. **No secrets.** Write where a secret lives, never the secret.
6. **Files win.** If the index and a file disagree, the file is right.

Why these rules, and what went wrong without them: [docs/design.md](docs/design.md).

## Commands

```
caderno init [PATH] [--clone URL]   create a notebook, or join one from another machine
caderno connect [AGENT...]          point codex / claude / gemini at it (--remove to undo)
caderno new "description"           start a note with the right front matter
caderno index                       rebuild the one-line indexes
caderno check                       missing descriptions, stale indexes, secrets
caderno sync                        pull, reindex, commit, push
caderno install-timer               sync on a schedule
caderno status                      what is set up on this machine
```

## Development

```bash
python3 -m unittest discover -s tests          # CLI and notes, stdlib only
# end to end, against a running service and a THROWAWAY notebook:
pip install "mcp==2.2.0"
python3 service/tests/e2e.py http://127.0.0.1:8420/mcp "$CADERNO_TOKEN" /tmp/test-notebook
```

## License

MIT. See [LICENSE](LICENSE).
