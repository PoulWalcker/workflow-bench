# Issue tracker: local markdown

When the private `.codex/tasks/` workspace is present, it is this repository's issue tracker.
Specs and tickets live there as markdown, one directory per milestone; nothing in it is
committed. Its `README.md` is the entry point.

## Conventions

- One milestone per directory: `.codex/tasks/<milestone>/`, with `README.md` as its entry.
- The spec is `.codex/tasks/<milestone>/spec.md`.
- Tickets are one file each at `.codex/tasks/<milestone>/tickets/<NN>-<slug>.md`, numbered from
  `01` in blocking order; a `Blocked by:` line near the top lists the ticket numbers that gate it.
- Triage state is a `Status:` line near the top of each ticket (role strings in
  [triage-labels.md](triage-labels.md)).
- Review reports are `.codex/tasks/<milestone>/reviews/<NN>-r<K>.md`.
- Ticket progress, review history and notes are sections of the ticket file itself.

## When a skill says "publish to the issue tracker"

Create the file under `.codex/tasks/<milestone>/`, creating the directory if needed.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path; the user normally passes the path or ticket number.

## Without the workspace

If `.codex/tasks/` is absent, no tracker exists for this checkout: work from the tracked
documentation and the task the user provides, and ask where a spec or ticket should go before
writing one.
