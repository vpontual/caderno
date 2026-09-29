# Layer 3: a notebook that cleans itself

Not shipped as code, on purpose: it needs an LLM on a schedule, and this is
where setups differ most. This page is a recipe for you, or your agent, to
build it against whatever model you run.

## Merge near-duplicates overnight

Even with the duplicate check in `remember`, notes drift together over months.
A nightly job can:

1. Pull every active note's vector from the service's database.
2. Group notes whose cosine similarity is above a high threshold (start at
   0.9 and check the groups by eye before trusting it).
3. For each group, ask an LLM to write one note that keeps **every specific
   value** from the originals: numbers, names, dates, commands. Losing a
   specific is the failure to watch for.
4. Write the merged note over the oldest one in the group, and `forget` the
   rest with the reason "merged into <key>". Git and `history` keep the
   originals.
5. Commit, so the merge shows up as a normal diff you can review or revert.

Run it on a branch or in dry-run mode for the first few weeks and read the
diffs.

### Four ways this goes wrong (all seen in the system caderno came from)

- **Merging in the database only.** If the job writes the merged fact to the
  index and leaves the source files, the next reindex brings every source
  back, the next night merges them again, and one fact multiplies (one reached
  52 copies). Merge by editing and archiving *files*; let the index follow.
- **Merging notes longer than the model's output.** A merge capped at a few
  hundred tokens cannot keep a long note whole. Skip any group containing a
  note too long for the output budget, rather than shrink it.
- **Replacing a note people link to.** Keep the merged note under an existing
  name, the one other notes link to. Never swap a named note for a new
  generated one.
- **Truncating on the way out.** Whatever writes a note must write all of it.
  A cut description that is later read back as the note replaces the real text.

Run the job with a dry-run flag that prints each group it would merge, and read
that output before the first real run.

## Distill a taste profile

Collect every note of `type: preference` and every rule, and ask an LLM to
write one short profile (under 300 words) of how you like to work. Save it as
`identity/taste.md` and list it in `INDEX.md` under "read every session".
Regenerate it weekly. It gives an agent the gist of dozens of preferences in
one small file.

## Rules for the job

- Files first: the job edits notes, and the service picks the changes up.
- Never let the model decide what to delete without leaving a trail in git.
- Measure before trusting: keep a list of merges you rejected, and raise the
  threshold until that list stops growing.
