# {{OWNER}}'s caderno

You are reading the index of {{OWNER}}'s notebook: what every AI agent they
use should know about how to work with them. It says **where** things are,
not what they say. Read what the task needs. Do not load everything.

## Read at the start of every session

1. `identity/profile.md`: who {{OWNER}} is and what they are working on
2. `identity/rules.md`: hard rules. Breaking one costs trust.
3. `identity/voice.md`: only when writing something in {{OWNER}}'s name

## Look up when relevant

| If you need... | Open... |
| --- | --- |
| A lesson, preference or fact from an earlier session | `memory/INDEX.md`, then only the notes whose one-line description matches |
| What a machine is, what runs on it, how to reach it | `machines/INDEX.md` |

If the `caderno` MCP tools are connected (`recall`, `remember`, `update`,
`forget`, `history`), prefer `recall` over reading indexes: it searches every
note by meaning.

## How to keep this notebook (the contract)

1. **Look before you write.** Check the index (or `recall`) for an existing
   note before creating one.
2. **Correct, don't duplicate.** When a fact changes, edit its note (or call
   `update`). Never write a second note that contradicts the first.
3. **One fact per note.** Small notes with a sharp one-line `description`
   are what make the index useful.
4. **Durable only.** Save what will matter next week: decisions, corrections,
   how things are set up, what went wrong and why. Not session scratch work.
5. **No secrets.** Passwords, tokens and keys never go in a note. Say where
   the secret lives instead ("the API key is in the password manager under X").
6. **Files win.** If the search service and a file disagree, the file is
   right. The service rebuilds itself from the files.

## Writing a note

Create `memory/<lowercase-name-with-dashes>.md`:

```markdown
---
description: one line that tells a future agent whether to open this file
type: lesson   # lesson | preference | project | person | machine | reference
---

The fact, and **why** it matters. For a correction, say what was wrong.
```

Then run `caderno index` (or let the sync do it). Do not edit the generated
`INDEX.md` files inside `memory/` and `machines/` by hand.
