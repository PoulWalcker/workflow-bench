# Task authoring regulation

Rules for every benchmark [Task](../../GLOSSARY.md#task), whether a person or an agent writes
it. Start from the [template](task-template/); [tasks/l1-basket-total](../../tasks/l1-basket-total/)
is a complete example. A task is admitted to model Trials only after `wb check-task` reports it
ready ([Readiness](#readiness)). [SPEC](../../SPEC.md#3-flow-contract) owns the flow these
rules serve.

## Layout

A task is one native Harbor directory under `tasks/<level>-<name>/`. Its top level holds exactly
these entries; anything else is rejected:

| Path | Status | Role |
|---|---|---|
| `instruction.md` | mandatory | Public goal, constraints and result location. |
| `task.toml` | mandatory | Harbor configuration plus Workflow Bench metadata. |
| `environment/Dockerfile` | mandatory | Agent environment; other files in `environment/` are its build context. |
| `solution/solve.sh` | mandatory | Oracle control; other files in `solution/` are its helpers. |
| `tests/test.sh` | mandatory | Verifier entry point; other files in `tests/` are private checks. |
| `tests/expected/` | optional | Private expectations read only by the verifier. |

Business rules live only in this directory. A task needing a new shared capability states it
as a separate change to Workflow Bench rather than branching core code on its name.

## `instruction.md`

State the goal in the user's terms, the constraints, and where the result goes. Leave the
method to the agent: no algorithm, no step list, and no tool name when tool choice is part of
the measurement. Keep private expectations, criteria and oracle details out of it.

## Result directory

An answer task (typically L1) has the agent write its result into `/work/output/`, and the
instruction names the file and its format; there is no shared answer schema. The environment
image sets `WORKDIR /work` and creates `/work/output`; `task.toml` declares
`artifacts = ["/work/output"]`, so Harbor collects the directory and re-creates it at the same
path for the separate verifier. The final chat message is never the answer. State-based tasks
(L2 and above) are checked against the resulting files or service state instead.

### State-based tasks rebased from Terminal-Bench

Keep the upstream instruction's goal and constraints in `instruction.md`; record every
change in `[metadata] deviations`. Preserve its working paths. Collect the final workspace
as a directory artifact (for example, `artifacts = ["/app"]`) so the separate verifier
assesses the agent's resulting state. Harbor empties that directory in the fresh verifier
container before uploading the collected copy; a deleted file therefore stays deleted. A
missing collected directory is an artifact transfer failure, not a passing pristine image.

Pin the upstream instance by its hub reference and content digest. Record its source
repository URL and commit, license and attribution, difficulty, empirical rank when used,
deviations, and contamination risk in `[metadata]`. Keep upstream `README.md` and a
network-installing `test.sh` out of the rebased task. Port each upstream test function to
one Criterion in a stdlib verifier, with private expectations in `tests/expected/`.

Build deterministic inputs for every comparison against an authored constant: fix random
seeds and git identity and dates where used, pin source commits, and fail the build if a
checked-out commit differs. Add `no_collateral_changes` as its own Criterion. Its finite
authored list in `tests/expected/protected.json` names pre-existing paths and SHA-256 hashes,
plus git refs or ordered commit messages when the instruction protects them. State the
constraint in the public instruction in user terms; record in `[metadata]` that the
Criterion was added by Workflow Bench. Verify every listed entry's presence, type and
bytes, while allowing new helper files outside the list. When there is no pre-existing
state to protect, return `not_applicable` with `reason_code = "no_protected_state"` and
explain that choice in `[metadata]`.

## `task.toml`

Required, and checked by `wb check-task`:

- `[metadata] level` — one of `L1`, `L2`, `L3a`, `L3b` ([levels](../../SPEC.md#2-task-levels-and-horizons));
  `horizon` — `single` or `repeated`.
- `[agent] timeout_sec` — finite; Harbor's default is unbounded.
- `[verifier] environment_mode = "separate"` — candidate work never shares a container with
  the private verifier.

Also set `[environment] network_mode` explicitly (`no-network` unless the task needs a
service) and keep Harbor's other timeouts finite. Model-provider access belongs to the run's
configuration, not the task.

For a task derived from an external benchmark, keep provenance in `[metadata]`: benchmark
name, pinned instance key, dataset URL and revision, checker source URL and commit, license,
attribution, and deviations from the original prompt or evaluation. Use a neutral task
directory name and keep the source name out of `instruction.md` so the task does not cue recall
of a published answer. Review checks this convention; `wb check-task` does not enforce it.

## Environment and services

`environment/Dockerfile` builds `FROM` the shared `agents` image (tag in
[ARCHITECTURE](../../ARCHITECTURE.md#parameter-sources)); that image carries the harness and the
evaluation helper, so the task adds only its public inputs and tools. A service used by one
task lives in that task's `environment/`. When a second task needs it, it moves into a shared
Workflow Bench image instead of being copied.

## Solution

`solution/solve.sh` proves that the task is solvable from the public instruction and
environment and that the verifier accepts a correct result. It is a control, not a reference
answer: an agent's result may differ from it and still pass.

## Verifier and evaluation

`tests/test.sh` runs the task's checks in the separate verifier container and ends by calling
`workflow_bench.evaluation.write_evaluation(Path("/logs/verifier"), criteria)`. Each
[Criterion](../../GLOSSARY.md#criterion) has an id, a status and a safe reason code:

- `pass` — the result satisfies it; `not_applicable` — it does not apply to this case.
- `fail` — a proven violation, including a missing or malformed answer the agent was told to
  write.
- `unknown` — the facts needed to decide are missing or untrusted.

The helper writes `evaluation.json` (verdict, criteria, completeness, errors) and writes
`reward.json` only for a complete assessment: `1.0` for `pass`, `0.0` for `fail`. A known
violation makes the verdict `fail` even when other criteria are unknown. Read candidate files
as untrusted input (`workflow_bench.data.read_json` bounds size and rejects symlinks) and never
execute them except under this rule: candidate code may run only in the separate verifier, as an
unprivileged user in a fresh temporary directory holding copies of the candidate file and private
test harness. Bound its execution time and captured output. After each run, kill all processes of
that user and confirm none remain; otherwise mark affected Criteria unknown. Remove entries in
`/logs/verifier` that the verifier did not create, then write the evaluation last from the verifier
process. A verifier crash leaves no evaluation, which Harbor records as a verifier error.

## Readiness

```sh
uv run --locked wb check-task tasks/<task> --jobs-dir runs/readiness
```

The command prints one JSON report on stdout and exits 0 only when the task is ready:

1. Structure: the layout and `task.toml` rules above, and Harbor parses the task. A violation
   is named, for example `missing:tests/test.sh` or `unexpected:notes.md`, and no run starts.
2. Helper image: the local image named by the final `FROM` of `environment/Dockerfile` must
   carry this checkout's evaluation helper. A stale copy (`stale:agents_helper`, rebuild the
   `agents` image) or an image that cannot be inspected (`unverified:agents_helper`; it is
   never pulled) stops the check before any run.
3. Controls: a real `harbor run` with Harbor's `oracle` agent must yield verdict `pass`, and
   one with the `nop` agent must yield `fail` (not `unknown`). Both run through
   `DeadlineDockerEnvironment`; their native jobs stay under `--jobs-dir`.

Review covers what the command cannot see: instruction quality, that the `FROM` image is the
`agents` image, criteria that decide the task's real requirements, and that expectations stay
private.
