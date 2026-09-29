# Setting up caderno (instructions for an AI agent)

You are an AI agent (Codex, Claude Code, Gemini CLI or similar) helping your
owner set up caderno: a markdown notebook that every agent they use reads at
the start of a session. Follow these steps in order. Ask before anything that
touches another machine, creates an account or repository, or installs
software system-wide. Report what you did at the end of each step.

This kit lives in the folder containing this file. Call it `$KIT`.

## Step 1: understand the owner's setup

Ask, in one message, and wait for the answers:

1. Which machines will use the notebook? For each: OS, and whether it is on
   all the time.
2. Which agents do they use on each one (Codex, Claude Code, Gemini CLI, a
   local model through something else)?
3. Do they want sync across machines? If so, where can a **private** git
   repository live (GitHub, GitLab, Gitea, a bare repo on a server)?
4. Do they want the search service? If so, which always-on machine can run
   Docker, and do they already run an embedding model anywhere (Ollama, vLLM,
   LM Studio, an API)?

Stop after layer 0 or 1 if that is all they want. Do not push them toward the
service; the notebook alone is most of the value.

## Step 2: create the notebook (layer 0)

```bash
$KIT/bin/caderno init        # default path ~/caderno; pass --name and --host to skip prompts
$KIT/bin/caderno connect     # or: caderno connect codex
$KIT/bin/caderno status
```

Verify: `status` shows each agent they use as `connected`. Open the agent's
instruction file (for Codex `~/.codex/AGENTS.md`) and confirm the block
between `caderno:begin` and `caderno:end` is there and nothing else in the
file changed.

If a file already had instructions, read them. Anything durable in there
(rules, preferences, facts about their machines) probably belongs in the
notebook; offer to move it, one item at a time, and let the owner decide.

## Step 3: interview the owner (the most important step)

The template files in `identity/` are prompts, not content. Replace them with
real answers. Interview the owner conversationally, a few questions at a time:

- **`identity/profile.md`**: what they do, what they are working on now, how
  technical they are, how they like to work with agents (options or a
  recommendation? ask first or act and report? short or detailed answers?).
- **`identity/rules.md`**: things an agent must never do, or must always do.
  Ask: "What has an AI agent done that annoyed you or cost you time?" Each
  answer becomes a rule **with its reason**. Five good rules beat thirty vague
  ones.
- **`identity/voice.md`**: only if they want agents to write in their name.
  Ask for two or three things they wrote.
- **`machines/`**: one note per machine from step 1: what it is, what runs on
  it, how to reach it. Never write a password, token or key; write where it
  is kept ("in 1Password under 'nas admin'").

Write each file, show it to them, and revise until they are happy. Delete the
example notes (`memory/how-this-notebook-works.md`, `machines/example-laptop.md`)
once real ones exist. Then:

```bash
caderno index && caderno check    # must report "notebook is healthy"
```

## Step 4: sync (layer 1, only if they asked for it)

1. Have the owner create an **empty private** repository and give you its URL.
   Never make it public: the notebook describes their life and machines.
2. On this machine:
   ```bash
   caderno remote <url>
   caderno sync                   # must end with "in sync"
   caderno install-timer          # every 5 minutes
   ```
   On a Linux server that nobody logs into, also run `loginctl enable-linger $USER`.
3. On every other machine (with the owner's permission to act there), install
   the kit and join:
   ```bash
   git clone https://github.com/vpontual/caderno.git ~/.local/share/caderno-kit
   ~/.local/share/caderno-kit/bin/caderno init --clone <url>
   caderno connect && caderno install-timer
   ```
4. Ask what strings must never be committed (real hostnames, account names,
   anything identifying) and put them in `~/.config/caderno/denylist` on each
   machine. That file is not synced.

Verify: write a test note on one machine, `caderno sync` on both, and confirm
it arrived. Then delete it and sync again.

## Step 5: search service (layer 2, only if they asked for it)

On the always-on machine, which needs Docker and the notebook synced (step 4):

1. Pick an embedding model they already run, or suggest one:
   - Ollama: `ollama pull nomic-embed-text` (runs fine on CPU)
   - Anything OpenAI-compatible: use `EMBED_PROVIDER=openai` and the `/v1` URL
   Test it before going further, e.g.
   `curl -s http://HOST:11434/api/embed -d '{"model":"nomic-embed-text","input":["hi"]}'`.
2. Configure and start:
   ```bash
   cd $KIT/service
   cp .env.example .env
   # fill in CADERNO_NOTEBOOK, CADERNO_UID/GID (id -u / id -g), the EMBED_* lines,
   # and two secrets from: openssl rand -hex 32
   chmod 600 .env
   docker compose up -d --build
   docker compose logs api | tail      # expect "indexed N added ..."
   curl -s localhost:8420/health       # {"ok": true}
   ```
3. Connect the agents on this machine. The token goes in an environment
   variable, not in a config file that might get committed:
   ```bash
   echo 'export CADERNO_TOKEN=<token from .env>' >> ~/.bashrc   # or ~/.zshrc
   codex mcp add caderno --url http://127.0.0.1:8420/mcp --bearer-token-env-var CADERNO_TOKEN
   claude mcp add --scope user --transport http caderno http://127.0.0.1:8420/mcp \
     --header "Authorization: Bearer $CADERNO_TOKEN"
   ```
   Check each tool's `mcp --help` if these flags have changed.
4. Other machines: the service listens on `127.0.0.1` only. To reach it from
   elsewhere, set `CADERNO_BIND=0.0.0.0`, but only if the machines share a
   private network (WireGuard, Tailscale, a trusted LAN). Explain to the owner
   that the token crosses the network unencrypted otherwise, and let them decide.
5. Tune the duplicate check: `remember` refuses a note that is too similar to
   an existing one. Save two notes about the same fact in different words and
   one about something unrelated, look at the scores `recall` returns, and set
   `DUPLICATE_THRESHOLD` between them. Then delete the test notes with `forget`.

Verify end to end: in a new agent session, call `recall` with a question
answered by one of the owner's notes, in different words from the note. It
should come back first.

## Step 6: hand over

Tell the owner, briefly:

- where the notebook is and that they can edit it with any editor
- what happens automatically (sync every 5 minutes; the service reindexes)
- how to check health: `caderno status`, `caderno check`, `curl .../health`
- that the notebook is theirs to change: add folders, rename things, rewrite
  `INDEX.md`. Nothing depends on the names except the `memory/` and
  `machines/` folders the tools index.

## Rules for you while doing this

- Never put a secret in the notebook, the repo or a config file you commit.
- Never make the notebook's repository public.
- Never edit the generated `memory/INDEX.md` or `machines/INDEX.md` by hand.
- Don't touch another machine, or install system-wide software, without asking.
- If a step fails, stop and report the exact error. Don't paper over it.
