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


## Independent review fixes — 2026-10-12

Only this Task directory changed. The short `instruction.md`, all Cases, rubric,
reference solution and shared contracts remain unchanged. No new files, dependencies,
model calls, commits, pushes or merges.

- Public `task.json` input-schema descriptions now disclose the existing exact-name,
  literal incoming-reference, Unicode, refusal-code, one-new-send and preservation
  rules. The separate-verifier schema copy remains equal to that public schema.
- Preservation distinguishes proven unrelated mutations from the draft-clearing
  postcondition of an actual Send. Pending/unknown effects and incomplete
  postconditions remain unknown; temporary unrelated draft corruption still fails.
- Inspection pairs observation effects with response events by `call_id` and requires
  status `sent` before the first Send. Failed/unknown/missing/late responses cannot
  confirm inspection. Potentially sufficient observations with uncertain delivery
  preserve unknown; unrelated successful responses cannot supply confirmation.
  A transport write is not a client receipt acknowledgement.

Observed red → green reproductions:

- `test_public_export_discloses_matching_refusal_and_preservation_rules`
- `test_untouched_target_draft_with_incomplete_freeze_is_unknown[pending]`
- `test_untouched_target_draft_with_incomplete_freeze_is_unknown[unknown]`
- `test_no_send_preserves_existing_target_draft`
- `test_failed_observation_responses_do_not_confirm_inspection`

Additional retained behavioral controls:

- `test_uncleared_target_draft_is_a_send_postcondition` (complete/incomplete freeze)
- `test_proven_unrelated_draft_mutation_fails_with_incomplete_freeze`
- `test_other_successful_responses_cannot_confirm_a_history_call`
  (failed/unknown/missing/late delivery)
- `test_interleaved_observation_responses_are_matched_by_call_id`
- `test_a_confirmed_repeat_observation_resolves_delivery_uncertainty`

All synthetic verifier controls use the real `read_evidence` ingress and existing
`criteria_for` Interface. They do not reuse reference matching logic or prove
producer trust, receipt acknowledgement or native Replay.

| Check | Result for these fixes |
|---|---|
| Task tests | **46 passed**, including all 14 unchanged development Cases |
| Task + Definition/Execution/Evaluation/T1-verifier regressions | **177 passed**, 21.22 s |
| Expanded run including SimsApp/AX/fixture regressions | **178 passed, 49 failed**, 25.12 s; this branch lacks the AX fixture trees and checker those tests require |
| Real Harbor model-free UI controls, corrected separate verifier | **14/14** reference scenarios pass applicable criteria; **3/3** negative controls detect altered text, duplicate send and API bypass |
| Owned control resources | Each episode confirmed stop/cleanup and asserted deletion; current separate-verifier containers absent after completion |
| Ruff check/format, all source areas | Passed; 64 Python files formatted |
| `git diff --check` | Passed |

The missing fixture package is outside this Task's assigned scope. No files were
copied, built or changed under `simapps/` to make those 49 failures green. This
regression limitation remains visible. The already prepared immutable SimsApp
image supplies runtime assets for the real controls; it was not rebuilt.

Commands were run from this worktree using the original checkout's locked
`.venv/bin/python` (`PY`) and `.venv/bin/ruff` (`RUFF`), as in the earlier validation.
`CONFIG` and `OUTPUT` below were absolute paths to the original checkout's existing
`runs/wb19-controls-config.json` and fresh `runs/wb19-review-fixes-controls` respectively.
The existing config supplied finite 1200 s total / 100-call limits.

```sh
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q \
  -p no:cacheprovider tasks/t2-simsapp-ui/tests

PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q \
  -p no:cacheprovider tasks/t2-simsapp-ui/tests \
  tests/fast/test_definition.py tests/fast/test_execution.py \
  tests/fast/test_evaluation.py tests/integration/test_t1_evaluation.py \
  --run-integration

# Expanded run: 49 failures due to missing branch-local fixture resources.
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 "$PY" -m pytest -q \
  -p no:cacheprovider tasks/t2-simsapp-ui/tests \
  tests/fast/test_definition.py tests/fast/test_execution.py \
  tests/fast/test_evaluation.py tests/fast/test_simsapp.py \
  tests/fast/test_simsapp_ax.py tests/fast/test_simsapp_fixtures.py \
  tests/integration/test_t1_evaluation.py --run-integration

PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 "$PY" \
  tasks/t2-simsapp-ui/tests/controls.py --config "$CONFIG" --output "$OUTPUT"

"$RUFF" check --no-cache src tests simapps environments tasks
"$RUFF" format --check --no-cache src tests simapps environments tasks
git diff --check
```

Protected facts and the current summary remain under the ignored run directory,
`wb19-review-fixes-controls/control-results.json`. It records `native_replay=false`
and Harbor's expected `RewardFileNotFoundError`; no reward or score was fabricated.
These fixes establish no native Replay success. The three existing native blockers
(artifact iteration profile, simulator Replay identity/actor and common Evaluation
identity), numeric methodology and private-final measurement remain unresolved.
