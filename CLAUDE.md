# tfl_ttl

## Session wrap-up: Notion decision log

Before ending a session — when the user signals we're wrapping up, or we
reach a natural stopping point — update the **Decision Log** section of the
[TFL Project Notion page](https://app.notion.com/p/3dc3fdcf437d81119e6cc73469cad2a8)
with anything decision-worthy from the session: architecture/design choices
made, options ruled out and why, gotchas discovered, or scope changes.

- Skip it if nothing decision-worthy happened (pure Q&A, no changes) — don't
  pad the log with routine implementation detail.
- Keep entries terse: one entry per decision, dated (use the actual current
  date), one or two sentences on what was decided and why. Match the style
  already on the page (plain prose, no filler).
- This is separate from Claude's own memory files for this project — the
  Notion log is the user's own project record, so entries should stand alone
  and read sensibly to a human without this session's context.
- If the Notion connector isn't available/authenticated, say so rather than
  skipping silently.
