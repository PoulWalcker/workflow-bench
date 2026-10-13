# Code style

This is the repository standard for prose written into code — docstrings and comments — and
for typing. Everything mechanical belongs to the tools. Engineering rules that
[AGENTS.md](../../AGENTS.md) already owns, such as
[logging and diagnostics](../../AGENTS.md#operation-and-completion) and
[test gates](../../AGENTS.md#executable-test-gates), are not repeated here.

## Ruff is the sole authority for anything mechanical

Line length, quotes, indentation, blank lines and import order are decided by `ruff format`
and `ruff check`. Their configuration in `pyproject.toml` is the only place those rules are
written down; how that configuration may change is owned by
[AGENTS.md](../../AGENTS.md#code-quality-and-portability). A review comment about a
mechanical rule is a bug in the configuration, not a finding.

## What earns a docstring

The seams, and nothing else. A seam is a place where a caller crosses from one module,
package or process into another. In this repository that means:

- package modules under `src/`;
- public functions and classes used from other modules;
- CLI and Harbor entry points;
- exchange values passed across those boundaries.

**Every such module** carries a module docstring: one line naming its subject. It is the line
a reader takes instead of the file.

**Every public entry point** carries one line saying what the caller gets. When the return
value is a decision rather than data — `False` means the run must stop — that meaning is part
of what the caller gets and belongs in the line.

Private helpers carry no docstring, and neither do self-explanatory accessors whose name
already says everything a docstring would repeat. Adding one for symmetry makes the file
longer and the seams harder to spot.

## The invariant exception

A docstring runs past one line only to state an invariant the code cannot show, and then it
states that invariant and nothing else: a lock deliberately not taken, a record that must be
written after an operation rather than before, a return value a retry depends on.

Design history, rejected alternatives and rationale stay out. A docstring is read by someone
using the code, not by someone re-deciding it.

## What earns a comment

Intent the code cannot state: a constraint from outside the file, a failure mode a reader
would not predict, a non-obvious reason for an ordering. Never a restatement of the next line.

## No decision ids, no style narration

A docstring or comment carries no decision id, ticket id or person's name. The code says what
holds, not who agreed to it or when.

A docstring or comment never describes a convention. Conventions are read once, here.

## Typing

- Every public function is annotated, parameters and return value.
- Every exchange value is annotated. JSON and contract values are `TypedDict`s or
  dataclasses, not bare `dict`s.
- No `Any` at a public boundary.
- `ty` checks these rules once it joins the project checks.

## Language

English, everywhere in `src/`, `tests/` and the other code directories (`tasks/`, `simapps/`,
`environments/`).
