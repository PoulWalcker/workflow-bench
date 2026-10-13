# Workflow Bench repository guide

This is the canonical repository instruction source for coding agents, not a benchmark
Task or Judge prompt. [README](README.md) owns local setup and verified commands.

## Project boundaries

Workflow Bench measures Sapiens on autonomous tasks: outcomes, reliability, cost and
failure points. Comparing configurations is optional when the question needs a baseline.
Read [SPEC](SPEC.md) before changing product behavior and [GLOSSARY](GLOSSARY.md) before
changing domain terms. Product requirements do not imply every stage is implemented.

Harbor owns scheduling, Trials, environments, agent invocation, collection and verification.
Workflow Bench supplies integrations and shared helpers; Tasks own business criteria.
The agent chooses its strategy; tools provide capabilities rather than business solutions.

## Architecture and entry points

<a id="task-first-and-rternarity"></a>

Read [ARCHITECTURE](ARCHITECTURE.md) before changing an interface, dependency, environment
or parameter source. Native Harbor is the execution entry point; there is no WB execution CLI,
service implementation or report command. Tasks follow the
[task authoring regulation](docs/agents/task-authoring.md), checked by `wb check-task`.

The product flow is Task Definition → Readiness → Environment → Execution → Evidence →
Evaluation → Comparison; [SPEC](SPEC.md#3-flow-contract) assigns inputs, outputs and owners.
[ARCHITECTURE's component map](ARCHITECTURE.md#existing-components) locates retained helpers
and integrations. Its [extension rules](ARCHITECTURE.md#extension-rules) keep business rules
in Task directories and harnesses at Harbor's agent seam; core never branches on names.
Follow its [parameter map](ARCHITECTURE.md#parameter-sources): one effective source per
parameter, user paths resolved once at entry. Its [exclusions](ARCHITECTURE.md#not-doing)
govern new abstractions and runtime responsibilities.

## Invariants

<a id="operation-and-completion"></a>

- Verdicts depend on independently checked task results, not agent declarations or process
  success. A proven violation is fail; unknown measurements remain unknown, never zero.
- Keep infrastructure failure distinct from agent failure. Early termination still requires
  assessment from trustworthy resulting state; see [outcomes](SPEC.md#4-outcomes-and-evaluation).
- Report one configuration without a baseline. Optional comparison requires equal conditions
  or an incomparable label; follow [reporting](SPEC.md#5-reporting-and-optional-comparison).
- Enforce [security and evidence](SPEC.md#7-security-and-evidence) outside candidate code:
  isolate private verification, preserve protected provenance and keep secrets/private data
  out of ordinary logs and feedback. Candidate artifacts cannot prove protected effects.
- Enforce [lifecycle rules](SPEC.md#6-errors-and-lifecycle): finite limits, confirmed stop of
  processes and children, bounded cleanup of owned resources and honest residual/unknown status.
- Model runs require separate permission and finite limits before credential access; enforce
  the spending/allowance gates in SPEC. Keep benchmark checks independent of candidate output.
- Preserve native source facts once. Diagnostics use stderr; machine-readable stdout contains
  only command results. Use stdlib logging configured at process entry, module loggers without
  import-time handlers, available Trial/Step/phase context and safe codes/relative references.

## Development and verification

<a id="code-quality-and-portability"></a>

Before changing Python code, read [Code style](docs/development/code-style.md).
Before completing a Python change or review, check every new or modified definition
against that document's applicable rules and agent checklist.

Validate external arguments/JSON at trust boundaries; typed internal values rely on that
validation. Catch exceptions where recovery or honest classification is possible; broad
catches belong at process/server/cleanup boundaries. Ruff owns mechanics in `pyproject.toml`;
fix violations with narrowly justified exceptions rather than blanket suppression.

Run from the checkout root and record the commands and exact results:

```sh
uv run --locked ruff check
uv run --locked ruff format --check
uv run --locked ty check
uv run --locked pytest -q
```

Use installed domain-modeling for terms, codebase-design for Interfaces, tdd before behavioral
implementation and writing-for-agents for agent instructions; resolve skills from the current
environment's catalog. Agree test seams before behavioral code: Interface, observable behavior,
failure detected and limits of proof. Test agreed interfaces with expected red → minimal green
→ optional local refactoring; derive expectations from requirements. Design/doc-only work adds
no tests. Mocks may cover external responses/errors but cannot prove isolation, stop or Judge
quality: require a real end-to-end control for those claims.

Default pytest is fast and needs no network, Docker or credentials. Gate integration/model
paths before collection and resources before fixture setup, including indirect/cached access;
collection is side-effect free. Integration requires `--run-integration`; unavailable Docker
or images are an error, not a green skip. Integration opt-in does not authorize model calls;
model mode remains closed. No tests is pytest exit 5, not successful verification.

## Documentation map

- [SPEC](SPEC.md): product contract, flow, outcomes, reporting, lifecycle and trust rules.
- [GLOSSARY](GLOSSARY.md): canonical domain terms; ADRs are not kept.
- [ARCHITECTURE](ARCHITECTURE.md): current code, boundaries, extension rules and parameter sources.
- [README](README.md): setup and verified local commands.
- [Code style](docs/development/code-style.md): Python conventions and review checklist.
- [Task authoring](docs/agents/task-authoring.md): task layout, template and readiness rules.
- [Agent rules](docs/agents/issue-tracker.md) and [triage labels](docs/agents/triage-labels.md):
  narrow tracker/skill conventions. [CLAUDE.md](CLAUDE.md) points to this file.

Update the document owning a changed fact and link to it elsewhere. Promote durable knowledge
from tickets to that document.

## Tasks / agent workflow

The user request assigns work; implement only the assigned slice. When `AGENTS.override.md`
is present, read it for private context and task workflow. The gitignored `.codex/` workspace
is local execution context, not canonical project documentation; follow the override's entry
points. Surface conflicting requirements explicitly and label new decisions as current work.
Inspect actual code and user changes; preserve unrelated work. Before finishing, inspect the
whole scoped diff and mark DONE only when acceptance is met; report unverified/blocked work.

## Git

Use the assigned milestone branch and Conventional Commits with English headers explaining
the requirement without private context. Stage explicit paths; keep history append-only during
phases and leave local private context, runs, data, credentials and old evidence uncommitted.
Merge, push and repository visibility changes require the owner's explicit instruction.

## Agent skills

### Issue tracker

Local markdown in the private `.codex/tasks/<milestone>/` workspace, when present. See
[docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).

### Triage labels

Default role names, used as ticket `Status:` values. See
[docs/agents/triage-labels.md](docs/agents/triage-labels.md).

### Domain docs

Glossary = [GLOSSARY.md](GLOSSARY.md); ADRs are not kept.
