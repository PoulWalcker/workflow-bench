# WB-19 verification — 2026-10-12

Scope: only `tasks/t2-simsapp-ui/`, on branch `codex/wb19-simsapp-task` based on
`codex/wb18a-blindly-ax` (`68084fd8dab693495bbe1261c7f0338f1f487889`). Work took
place in an isolated worktree. WB-18B and its unpublished fixture directory were
not modified or used as build input. No commit, push, merge or model call.

## Results

| Check | Actual result |
|---|---|
| Behavioral Task tests plus Definition/Execution/Evaluation/T1-verifier regressions | **163 passed**, 22.11 s (32 Task tests, 131 existing regressions) |
| Genuine T1 manual Harbor/n8n regression | **1 passed**, 131.93 s; `fresh-a`, `fresh-b`, `missing` each completed native Replay and independent verification |
| Real isolated SimsApp reference controls | **14/14** returned only pass/not-applicable required criteria in the separate verifier |
| Real negative controls | **3/3** detected: altered text → `text: fail`; duplicate → `multiplicity: fail`; forbidden API attempt → `ui_only: fail` |
| Ruff check, entire tracked source areas plus new Task | Passed |
| Ruff format check | Passed, 63 Python files already formatted |
| Native reference submission | Collected and stopped; rejected by artifact profile, **no Replay**, no score |
| Allowlisted native observation probe | Artifact accepted; simulator reset rejected, **no n8n execution**, no score |
| Common Evaluation with real control identity | Retained local test confirms `invalid_schema: evaluation` |
| Private-final export | Synthetic sentinel absent from all six exported public files; owner-only Task copy and missing-final failure checked |
| Owned resources | Stop/cleanup confirmed for completed controls and native attempts; final Docker inventory contained no WB-19 resources |

The separate UI verifier writes criteria and Evidence hashes, not a native
Evaluation or reward. Harbor records **RewardFileNotFoundError**, intentionally
preserved. Thus 17 successful *control checks* are not 17 successful native Trials,
not native T2 Replay, and not a scored benchmark result. The existing T1 native
regression is the only successful n8n Replay reported here.

The first native attempt exposed a Task packaging defect (`/work` absent); adding
`mkdir -p /work` fixed it before the profile-blocker reproduction. The first full
UI suite used the inherited 360 s total limit; it was explicitly interrupted before
completion, with cleanup confirmed. It is not counted as a passed suite. The final
suite ran fresh with 1200 s total, 90 s verifier timeout and 100 calls per control.

## Commands actually exercised

The worktree reused the already installed locked CPython 3.12.13 environment from
the original checkout, with `PYTHONPATH` set to this worktree's `src`. In the commands
below, `PY` denotes that interpreter and `RUNS` the existing ignored run directory.
No dependency installation, image rebuild or fixture copy was performed.

```sh
PYTHONPATH="$PWD/src" "$PY" -m pytest -q \
  tasks/t2-simsapp-ui/tests \
  tests/fast/test_definition.py tests/fast/test_execution.py \
  tests/fast/test_evaluation.py tests/integration/test_t1_evaluation.py \
  --run-integration

PYTHONPATH="$PWD/src" "$PY" -m pytest -q \
  tests/integration/test_manual.py::test_manual_t1_reaches_independent_verifier \
  --run-integration --e1-config "$RUNS/wb18a-acceptance/telegram/config.json" \
  --basetemp "$RUNS/wb19-t1-regression" --log-cli-level=INFO

PYTHONPATH="$PWD/src" "$PY" tasks/t2-simsapp-ui/tests/controls.py \
  --config "$RUNS/wb19-controls-config.json" --output "$RUNS/wb19-ui-verified"

PYTHONPATH="$PWD/src" "$PY" -m workflow_bench.cli \
  --task tasks/t2-simsapp-ui \
  --config "$RUNS/wb18a-acceptance/simsapp/config.json" \
  --output "$RUNS/wb19-native-profile" --case unique

PYTHONPATH="$PWD/src" "$PY" tasks/t2-simsapp-ui/tests/native_probe.py \
  --config "$RUNS/wb18a-acceptance/simsapp/config.json" \
  --output "$RUNS/wb19-native-observe"

ruff check src tests simapps environments tasks
ruff format --check src tests simapps environments tasks
```

Task-local TDD progressed through red → green for package loading/export,
new-versus-old messages and duplicate effects, expected/incoming consistency,
transient draft corruption, refusal/inspection, API bypass, journal gaps, private-final
separation, the verifier entry point and early proven ambiguity. Synthetic Evidence
controls do not establish producer trust; real isolated UI/Harbor controls supply
that separate evidence. Missing/foreign/forged facts do not become success.

The immutable SimsApp image was
`sha256:5e281fb71b27454f1f366e528d9d3b7281c1c1fad3fd2ec7418d2ddfbac7f9ca`.
Native logs and protected source facts remain only under ignored run directories:
`wb19-ui-verified/control-results.json`, that run's Harbor verifier logs,
`wb19-native-profile/report.json`, `wb19-native-observe/run/report.json`, and
`wb19-t1-regression/`. No Evidence is committed into the Task.

## Remaining limitations

The three reproducible WB-22 blockers are detailed in README: artifact iteration
profile, simulator Replay identity/actor, and common Evaluation identity. Neither
shared contracts nor runtime were extended. Native reference graph expressions and
loops remain unverified in n8n. Task criteria are ready and independently exercised,
but **complete native T2 acceptance is blocked; WB-19 is not marked DONE**.

Numeric rubric methodology was not specified, so `scoring_policy` remains null.
No real private-final set or final measurement was created, exposed or evaluated.
The provisioning mechanism is tested using synthetic sentinel data only. Fixture
publication/packaging remains WB-18B's responsibility. Online NAV/model execution
and further work are outside this change.
