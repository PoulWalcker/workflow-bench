# Engineering instructions

For agents developing this repository. This file is not a Composer prompt,
a benchmark Task, or Judge material.

## Start with the assigned task

1. Read [SPEC](SPEC.md) for requirements and terms, then [ARCHITECTURE](ARCHITECTURE.md)
   for the relevant interfaces and trust boundaries.
2. Find the assigned milestone and dependencies in [ROADMAP](ROADMAP.md); read its
   current implementation ticket. WB-01 is historical, not the current design.
3. Inspect the actual code and user changes. Implement only the assigned slice;
   bootstrap does not authorize future modules or empty scaffolding.

The user request assigns work. SPEC owns product requirements and definitions;
ARCHITECTURE owns responsibilities, interfaces and dependency rules; this file
owns engineering rules; ROADMAP owns milestones/status; [README](README.md) owns
setup and verified commands. Tickets preserve task-specific decisions and evidence.
Update the owner of a changed fact and link to it elsewhere. Surface conflicting
requirements explicitly; label new technical decisions as decisions of the current
work rather than previously accepted user wishes.

When a `.codegraph/` index exists, use CodeGraph before searching or reading code:
`codegraph_explore` (pass projectPath) or `codegraph explore "<question or symbol>"`.
Do not index an unindexed repository on your own.

## Task-first and rTernarity

Organize responsibilities as **Definition → Experiment → Evaluation**, each with
clear input, work and output. Decompose only when independent responsibilities
appear; three is not a required count of files, classes, services or collection items.

Keep business rules in Task/application code. A new Task using supported contracts
and existing app capabilities changes only its own directory. Core, common prompts,
binder and evaluator must not branch on Task/app names or supply the solution.
Keep one app state, one native workflow format, one execution path and one score
calculation. Harbor owns sandbox lifecycle; Experiment owns research policy.
Select Composer integrations at the entry point through Harbor's agent seam;
core must not implement harness planning.

Use helpers for repeated meaning, not similar syntax. Avoid plugin registries,
universal backends, factory chains, DI frameworks, base classes for a single
implementation, empty wrappers and speculative dependencies. Do not add a DSL,
compiler, fallback runtime, global ledger/scheduler, daemon or hidden repair loop.
AutoWFBench and old benchmarking are references, not required dependencies. Before
transferring specific external code, check its license and retain attribution;
unclear terms mean no import. Do not copy large subsystems.

## Code quality and portability

Use Python, explicit names, small functions with one responsibility, and typed
public interfaces/exchange values. Validate external arguments/JSON once at each
trust boundary; avoid repeated checks of guaranteed internal values. Comments
explain reasons or constraints; operational instructions belong in documentation.
Catch exceptions where recovery or honest classification is possible. Broad catches
belong only at process/server/cleanup boundaries, never to hide defects as success.

Ruff owns lint/format configuration in `pyproject.toml`. Fix violations first;
no `ALL`, routine `# noqa`, blanket src/tests exclusions, or global rule suppression
for one location. Necessary `lint.ignore`/`lint.per-file-ignores` must have a reason,
the smallest practical scope, and an explicit explanation when widened. Do not add
a second formatter/type checker without a concrete need.

User paths, addresses, ports, model names, credentials, outputs and budgets have
one explicit CLI/env/config source per parameter. Follow the actual parameter map
in ARCHITECTURE; do not add competing overrides. Resolve user paths once at entry,
use `pathlib`, packaged resources and configured container network names. No machine
paths, required absolute executable paths, hidden cwd dependency, assumed free host
port, or implicit container-localhost-as-host. Protocol paths, schema versions,
fixtures and meaningful limits are legitimate constants. Pin environments for
reproducibility; do not turn every literal into configuration.

## Behavioral TDD

When changing terms, use the installed domain-modeling skill; when choosing an
Interface, use codebase-design; before behavioral implementation, use tdd. When
editing these instructions, use writing-for-agents. Resolve skills through the
current environment's catalog, not the author's machine paths. Apply them to the
assigned slice without an extra MVP redesign or new documentation layer.

Before coding, agree any unapproved test seams with the user: Interface, observable
behavior, failure detected and limits of proof. A proposal table is not approval.
Design-only work produces no tests. For a business rule/regression, use pytest:
one small test that fails for the expected reason → minimal implementation →
optional local refactoring while green → next scenario. Do not prewrite a suite
against an imagined API. Derive expectations independently from requirements,
not the implementation's algorithm. Docker configuration/spikes may start with a
minimal reproducible experiment, then retain a check for the confirmed behavior.

Test agreed interfaces, not private helpers/getters/imports for coverage, file
counts, arbitrary IDs, giant UI snapshots or exact timings. Frozen Evidence is the
independent verifier's public Interface: checking state/history through it is
required, not a side-channel violation. Run real loaders, validators/binder and
evaluators; substitute only external process/transport, time or fault sources.
Mocks can cover model responses/errors but cannot prove Harbor/n8n/isolation/stop
or Judge quality. Require a real end-to-end control. Keep orchestration tests about
behavior rather than the exact sequence of internal calls.

### Executable test gates

Default pytest runs fast tests without network, Docker or credentials. Gate
integration/model directories before collection; reject explicit gated paths,
node IDs and marked items without opt-in. Path classification cannot be weakened
by markers or `-m`. Check resource fixtures before setup and cached-value access,
including indirect requests from fast tests. Resources belong inside authorized
fixtures, never import/collection, parametrization or root autouse setup.
`--collect-only` is always side-effect free. Integration opt-in does not authorize
models; model execution needs separate permission and finite limits before
credential access. The current model test mode remains closed.

Requested integration without Docker/images is a preflight error, not a green skip.
Gate probes must be harmless local files/processes. No tests means pytest exit 5,
not a successful suite or an `assert True` placeholder. Test counts/coverage are
not project goals. Use verified commands from README and the current configuration.

## Operation and completion

Enforce [SPEC's lifecycle/security rules](SPEC.md#9-errors-and-lifecycle) and
[trust invariants](SPEC.md#10-security-and-evidence) through the environment.
Paid model calls require explicit permission and finite limits. Never contact real
Telegram or a physical desktop in this MVP. Do not weaken benchmark checks or
adjust expected outputs to a candidate; controls use the same independent path.

Every operation has a finite timeout and owned resources. Clean only the current
run's resources. Preserve source facts once, reference native Harbor artifacts,
and avoid a second log tree or hashing all documentation into execution identity.
Use stdlib logging, configured once at each process entry point; modules use
`getLogger(__name__)` and add no import-time handlers. Include available run,
attempt, case/replay and phase context; missing IDs remain absent. INFO records
phase start/end, monotonic duration/status and log refs; long waits report their
phase about every 30 seconds without invented progress percentages. WARNING marks
unknown metrics/effects/cleanup; ERROR marks infrastructure failures with safe
codes; a known benchmark fail need not be an infrastructure ERROR.

Diagnostics go to stderr; machine-readable stdout contains only command results.
Keep credentials, capabilities, full prompts, private input/state/expected and raw
exceptions out of ordinary logs/feedback. Use safe codes and relative refs; private
source logs stay under the closed run root. Logs do not replace protected effects,
Evaluation or confirmed stop.

Before finishing, inspect the entire scoped diff for dependencies, unrelated edits,
duplication, machine paths, secrets and scope growth. Report changes, commands
actually run/results, and unverified/blocked work. Mark DONE only when acceptance
criteria are met; unavailable Docker/credentials are not successful verification.
Do not commit runs, user data, credentials or old evidence; delete others' resources;
create/change remote repository visibility; or push without the user's instruction.
Skill revision provenance for the original design is in the
[WB-03 ticket](docs/implementation/WB-03-component-boundaries.md#design-skill-provenance).
Project TDD permits local refactoring after green; Interface/Seam is not a synonym
for the product's API/UI or trust boundary. A single runtime still requires its trust seam.

## Agent skills

### Issue tracker

Local markdown in the private `.codex/tasks/<milestone>/` workspace, when present. See
[docs/agents/issue-tracker.md](docs/agents/issue-tracker.md).

### Triage labels

Default role names, used as ticket `Status:` values. See
[docs/agents/triage-labels.md](docs/agents/triage-labels.md).

### Domain docs

Deferred to milestone M0: no `GLOSSARY.md` or `docs/adr/` yet; SPEC owns terms until then.
