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
execute them. A verifier crash leaves no evaluation, which Harbor records as a verifier error.

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
