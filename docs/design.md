# Why caderno works the way it does

Caderno came out of a year of running a shared memory for several AI agents
across seven machines. Every rule below is here because something went wrong
without it.

## Files are the source of truth

Memory products usually put a database first and give you an API to it. That
makes the memory hard to read, hard to fix by hand, and gone if the service
dies. Here the markdown files are the memory. The search index is derived:
the service rebuilds it from the files, and `python -m caderno_service.reindex
--rebuild` can throw it away at any time.

This also gives you a single write path. An agent's `remember` or `update`
writes the file first and indexes it from there. A hand edit, or a change
pulled in by sync, is picked up on the next reindex. There is never a fact in
the database that is not in a file.

## An index, not a dump

Loading every note into every session wastes context and buries the useful
parts. So the notebook is layered: three small files load every session, and
everything else is behind one-line descriptions in `memory/INDEX.md`. The
description is written for a future agent deciding whether to open the note,
which is why `caderno check` flags a note without one.

The indexes are generated and sorted with no timestamps, so two machines that
regenerate them from the same files produce identical bytes. An earlier
version wrote timestamps; every night ended in a merge conflict.

## Corrections replace, they don't pile up

The most common failure in agent memory is two notes that disagree, recalled
with equal confidence. In the system caderno came from, more than twice as many
facts had been corrected as were currently true (1,640 superseded revisions
against 751 active ones). Without a correction path, every one of those would
still be in recall.

So a note has a stable key (its path), `update` edits it in place, and the
service keeps each earlier revision, with the reason it changed, where
`history` can see it and `recall` cannot. `remember` checks for a similar
existing note before writing, and sends the agent to `update` instead.

## One fact per note

Small notes make sharp descriptions, sharp descriptions make a useful index,
and a useful index is what lets an agent find the one note that matters
without reading forty. When a note starts covering two things, split it.

## No secrets, enforced twice

Agents will write a password into a note if nothing stops them. The
pre-commit hook scans every commit, the service refuses secret-shaped text in
`remember` and `update`, and `~/.config/caderno/denylist` covers the strings
only you know are sensitive. The patterns favour precision: a false alarm
blocks a sync, so each one needs the shape of a real secret, not just the word
"password".

## Lessons from running the original

- **Give the notebook and any service different names.** Ours shared one, and
  agents kept editing the service when they meant the notebook.
- **A quiet job looks like a working job.** A scheduled export sat 17 days
  stale because nothing ran it, and notes written on one machine went
  uncommitted for weeks because the sync staged only one folder. `caderno sync`
  stages everything, and `caderno status` shows when the last sync happened.
  Check the date, not whether the job exists.
- **The service host is also a sync host.** When an agent on another machine
  calls `remember`, the file is written on the service's machine and reaches
  the others through that machine's sync timer. Give it one.
