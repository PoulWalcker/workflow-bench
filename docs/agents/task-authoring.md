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

## Repeated tasks (set up and leave)

Use `[metadata] horizon = "repeated"` when the instruction asks for effects after
one setup turn. Tell the agent it will not be present for later changes and state
the business goal and output path; leave the mechanism to the agent. The oracle
may start a detached loop with stdin, stdout and stderr redirected, so the setup
turn exits while the loop keeps working. The task's verifier judges the resulting
state, not the agent's claimed method.

Place `schedule.json` and an initial `manifest.json` under `environment/`. The
Dockerfile copies the schedule into the image and creates the evidence directory
with that manifest, status `not_started`, schema version 1, null start/end/elapsed/
error fields, empty `drops`, `snapshots`, `samples`, `skipped` arrays and
`skipped_truncated = false`. See the exact seed in the
[short control](../../tests/integration/assets/window-task/environment/manifest.json).
This preserves a collected incomplete status if Harbor stops `main` before the hook starts.
The task declares the workspace and evidence directory as artifacts:

```toml
artifacts = ["/work", "/window-evidence"]
[agent]
timeout_sec = 900
[verifier]
environment_mode = "separate"
network_mode = "no-network"
timeout_sec = 120
[[verifier.collect]]
service = "main"
command = "python3 -m workflow_bench.window /opt/window/schedule.json /window-evidence"
timeout_sec = 780 # duration 600 + tail 60 + margin 60
```

The schedule is task-owned JSON with exactly `duration_sec`, `tail_sec`,
`sample_interval_sec`, `watch` (absolute paths), `drops` (`at_sec`, absolute
`source` and `target`) and `snapshots` (`at_sec`, absolute `paths`). Offsets are
seconds from the driver's start, after the agent phase. At equal offsets a
snapshot precedes a drop. The driver samples watched paths at interval offsets
through `duration + tail`, copying changed content so the verifier can determine
when an appended line or row first appeared. It bounds the schedule to 3600 s
duration, 600 s tail, at most 128 samples, 32 watched paths, 128 drops and 128
snapshots, and 32 MiB/4096 copied files and directories of evidence. Each sample
or snapshot processes at most 4096 directory children (with bounded lookahead
to detect truncation); this traversal limit resets for the
next observation, so earlier unchanged samples do not consume later scan capacity.
Symlinks and special files are not copied. A listed entry that cannot be read
because it vanishes or changes kind is omitted (`missing` with null digest/copy
when watched directly); any partial copy of that entry is removed. Successfully
read replacements are recorded with their observed kind and content. A regular
file already open is recorded from the bytes actually read, even if its name
then vanishes or is replaced. Directory fingerprints include only entries observed in that scan;
observations are bounded views rather than atomic filesystem snapshots. These
races do not fail the window.

Drops are written to a hidden temporary sibling with no target suffix, then
published complete by `os.replace`; temporary files are removed on success or
failure. Existing non-regular or symlink targets still fail with `unsafe_file`.
Set the hook timeout to
`duration + tail + 60` seconds.

Use `workflow_bench.window.read_window` in the separate verifier. Missing,
invalid or unsafe evidence raises `DataError`; `not_started`, `running` and
`failed` are explicit incomplete statuses. Criteria needing the window are
`unknown` with reason `window_incomplete` in those cases. Criteria decidable
from final state still decide. Derive timing from first-seen sample offsets;
candidate timestamps can check consistency but cannot establish first appearance.
Window evidence in `main` is candidate-reachable, so reports must label that
provenance. The verifier's `network_mode = "no-network"` keeps its assessment
offline. If scheduled agent work needs model access, the run supplies provider
hosts through `environment.extra_allowed_hosts`; the Task does not embed them.

Run readiness with `wb check-task <task> --jobs-dir <path> --run-timeout-sec 1800`
so its two native controls each have enough time for
the setup turn, window, verification and cleanup. A short-window version may be
used for authoring controls, but it does not replace the task's full criteria.

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
test harness, isolated from the private checker and other verifier inputs. Bound its execution time
and captured output. After each run, kill all processes of that user and confirm none remain;
otherwise mark affected Criteria unknown. Remove entries in
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
