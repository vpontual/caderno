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
