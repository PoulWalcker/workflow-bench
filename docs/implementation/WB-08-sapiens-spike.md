# WB-08 — Sapiens integration spike

Assigned 12 October 2026. This ticket records the minimal Sapiens → Harbor slice.
The first separately authorized live Attempt timed out without an artifact. The
600-second repeat generated a native artifact but its n8n execution failed; E3
remains unconfirmed. Product terms, Task requirements and Evaluation remain owned
by SPEC, ARCHITECTURE and WB-06.

## Decisions and approved test seams

The owner approved testing Sapiens' Harbor installed-agent Interface and the existing
ControlledSubmission/FrozenEvidence Interfaces in this chat. Model-free controls
exercise the real host, CLI and Harbor lifecycle while substituting only the external
Codex process. They do not prove model reasoning, autonomous tool choice or a genuine
Sapiens-generated WorkflowArtifact. Existing terms remain unchanged: a Sapiens Call or
internal decision is not an extra benchmark Attempt; accepted submission, terminal
outcome, confirmed stop, WorkflowArtifact validity and Evaluation are separate facts.
No new glossary terms or irreversible architectural decision are needed for this slice.

Current-work decisions:

- A separate `workflow_bench_integrations.sapiens:SapiensInstalledAgent` uses Harbor's
  installed-agent seam. Sapiens owns its planning. No replacement CLI, HTTP bridge,
  agent loop, harness planner, custom verifier or Task-specific integration rule.
- The existing Composer function now accepts a native `AgentConfig`. Stock Codex and
  Sapiens reuse public export, simulator reset, MCP transport, isolation probes,
  close-admission/freeze, whole-container stop, native artifact collection and cleanup.
  The CLI alone chooses the harness through `--codex` or `--sapiens`.
- Sapiens inherits Harbor's Codex configuration and credential resolution/upload
  helpers, not its `codex exec` loop. This narrow coupling is pinned to Harbor 0.24.0;
  future Harbor changes require the real controls again. Native Codex configuration
  supplies the same stdio MCP server and provider settings to Sapiens' internal Codex.
- Each Attempt starts with absent `/tmp/sapiens-data` and `/tmp/codex-home`, a clean
  `/home/composer`, and no personal mount. The host binds loopback inside the container;
  it publishes no host port. No Blindly4 binary, desktop submodule or physical desktop.
  Harbor stops the whole host/container even after successful CLI observation.
- CLI submission happens once; observation follows the accepted turn ID. Failure,
  disconnection or detach never triggers an adapter retry. Ctrl-C alone detaches the
  upstream CLI; cancellation/timeout therefore retain Harbor's container stop guarantee.
- Sapiens source stays outside the repository. The builder uses only committed runtime,
  prompt, web and license files, preserving upstream notices. No upstream modifications.

## Upstream source and license

Pinned revision: `71e93cb3de00183c263ec440919b313cf92ed8af` from
[aleski-green/sapiens4](https://github.com/aleski-green/sapiens4/tree/71e93cb3de00183c263ec440919b313cf92ed8af).
Relevant references are its
[CLI specification](https://github.com/aleski-green/sapiens4/blob/71e93cb3de00183c263ec440919b313cf92ed8af/documentation/specs/CLI.md),
[CLI implementation](https://github.com/aleski-green/sapiens4/blob/71e93cb3de00183c263ec440919b313cf92ed8af/sapiens/corpora/host/cli.py),
[loopback transport](https://github.com/aleski-green/sapiens4/blob/71e93cb3de00183c263ec440919b313cf92ed8af/sapiens/corpora/host/cli_transport.py),
and [internal Codex runtime](https://github.com/aleski-green/sapiens4/blob/71e93cb3de00183c263ec440919b313cf92ed8af/sapiens/runtime/codex.py).

Before preparing the image, reviewed upstream `license/LICENSING.md` and
`license/LICENSE.md`: Sustainable Use License 1.0 permits personal/noncommercial or
internal business use and requires retention of terms/notices. The image preserves
the license directory; no external implementation is copied into WB source. Desktop
submodules are excluded. Redistribution or hosting outside these terms is outside
this spike.

## Verification

Confirmed model-free success evidence:
`runs/wb08-third-control/test_sapiens_native_submission0/run/report.json`.
One Attempt, 3 simulator tool calls, native CLI `Completed`, regular-file artifact
collection, 5/5 development and 5/5 private final, score 10/pass/complete. Stop is
confirmed with empty cleanup errors/residual resources. `sapiens-doctor.json` records
`computer_built=false`; `sapiens-native-mcp.json` contains the real Codex-discovered
`get_chat`, `list_messages`, `send_message` inventory. `isolation.json` records the
protected management endpoint unreachable from both main and provider. No real
credentials were accessed and no model turns were submitted.

The first readiness runs failed before submission because the adapter mistakenly
used Harbor's fail-on-nonzero command helper for a readiness probe. Replaced that
read with native environment execution, allowing bounded retries of the read-only
probe. The corrected real success control passed in 418.44 s. Earlier failed
controls remain in their own directories; they are not claimed as successful runs.
All results use fresh owned directories under ignored `runs/`; no runs, credentials
or private final values belong in Git. Fast tests remain network/Docker/credential
free; integration and model gates remain intact.

The native model-free MCP probe starts a real Codex app-server from within the
Sapiens child environment and calls `mcpServerStatus/list`, without `turn/start`.
Its returned tool inventory proves actual initialization/discovery. A separate
inert process calls the real MCP tools against the simulator; frozen protected
facts prove those effects. Native model-free provider failure is a separate control.
Neither check claims that a live model chose or called these tools.

The synthetic success control submits an existing control file through Sapiens'
real decision/terminal path. The same file then follows WB-06's independent
validator/binder/n8n/Evidence/verifier/5+5 scoring path. A resulting score is a
control result, never a Sapiens model score.

Additional confirmed controls:

| Control | Demonstrated result | Evidence root |
|---|---|---|
| Submission timeout | Host and detached late child stopped; no submitted file; complete frozen effects retained | `runs/wb08-timeout-confirm` |
| External cancellation | Cancellation propagated; host/child stop and deletion confirmed | `runs/wb08-cancel-control` |
| Native CLI cancellation | `conversation cancel` accepted; observer reported `Interrupted`; no late artifact | `runs/wb08-native-cancel-control` |
| Host disconnection | Observer emitted `HOST_UNAVAILABLE` with stale state; surviving children stopped; no retry/artifact | `runs/wb08-disconnect-control` |
| Production CLI, real Codex/local stub | CLI observed failure; one Attempt, no artifact/score, confirmed stop/cleanup | `runs/wb08-native-stock-model-free` |
| Stock-Codex failure check and existing Codex timeout/cancel regressions | 3/3 pytest controls passed after extracting shared submission | `runs/wb08-stock-regression` |

The default suite passed 286 tests (latest fast run 28.33 s). Ruff check, Ruff format
check and scoped diff whitespace checks passed. Those model-free checks accessed no
live credentials or provider. The adapter's 5+5 control also passed under `runs/wb08-final-controls`.
That command then failed four fixture setups and the stock check because a parallel
builder verification reused the production image tag. Removing the control's last
temporary base tag deleted the now-untagged old image index. This was an image
management mistake in the spike work, not a successful final matrix.

The builder now assigns a unique retained tag to each image preparation, so it does
not replace an image referenced by another run. Rebuilding exact old inputs recovered
the identical platform manifest `984f9bd6a87ad3f89bc4f682c60c1840f0be75d5bfdd4f155b222979bc96bec2`
and image config `915ea49220d6be69ddf3641fbde9efa8034d1a5b2050e9322caa21c137891f1d`;
Docker produced a new index because its provenance attestation changed. The old
config remains historical evidence; regenerate image configuration to repeat it.
The corrected builder passed under `runs/wb08-unique-builder`. The five affected
controls are repeated under `runs/wb08-final-stop-controls` using that retained image;
all five passed in 123.83 s, with complete freezes, no late artifacts and empty
cleanup/residual errors. The prepared live config uses this new image.
The builder's final pinned `procps=2:4.0.4-9` command also succeeded under
`runs/wb08-builder-validation`, retaining the same runtime/code versions.

Verified commands:

```sh
uv run --locked --offline python environments/build_sapiens.py --source /private/tmp/wb08-sapiens-source --codex-config runs/wb07-completion-review/images/codex-config.json --output runs/wb08-sapiens-images/config.json
uv run --locked --offline python environments/build_sapiens.py --source /private/tmp/wb08-sapiens-source --codex-config runs/wb07-completion-review/images/codex-config.json --output runs/wb08-builder-validation/config.json
uv run --locked --offline pytest -q tests/integration/test_sapiens.py --run-integration --e1-config runs/wb07-completion-review/images/config.json --sapiens-config runs/wb08-sapiens-images/config.json --measurement-task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --basetemp runs/wb08-final-controls --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_sapiens.py::test_sapiens_stock_codex_failure_is_terminal_not_submission tests/integration/test_codex.py::test_native_codex_stops_child_writer_and_revokes_tools --run-integration --e1-config runs/wb07-completion-review/images/config.json --sapiens-config runs/wb08-sapiens-images/config.json --basetemp runs/wb08-stock-regression --log-cli-level=INFO
uv run --locked --offline python -m workflow_bench.cli --sapiens --config runs/wb08-sapiens-images/config.json --task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --output runs/wb08-native-stock-model-free
uv run --locked --offline python environments/build_sapiens.py --source /private/tmp/wb08-sapiens-source --codex-config runs/wb07-completion-review/images/codex-config.json --output runs/wb08-unique-builder/config.json
uv run --locked --offline pytest -q tests/integration/test_sapiens.py -k 'stops_host or stock_codex_failure' --run-integration --e1-config runs/wb07-completion-review/images/config.json --sapiens-config runs/wb08-unique-builder/config.json --basetemp runs/wb08-final-stop-controls --log-cli-level=INFO
uv run --locked --offline pytest -q
uv run --locked --offline ruff check .
uv run --locked --offline ruff format --check .
git diff --check
```

An intermediate timeout test failed on missing test imports before starting Harbor;
the repaired check passed. An attempted `tests/fast/test_cli.py` command exited 4
because no such file exists; the actual default suite and `test_codex.py` passed.
These failed development commands are not counted as verification successes.
An unrelated `docs/research/blindly4-telegram-ui.md` appeared during the session and
was left untouched; it is outside this assigned slice.

## Authorized live experiment

The owner separately authorized the prepared live configuration in this chat on
12 October 2026: ChatGPT subscription with explicit `$HOME/.codex/auth.json`,
`gpt-6.1-sol` / low, up to two Attempt, 240 seconds per Composer Attempt,
40 exploration tool calls per Attempt, 1800 seconds overall, native allowance checks
before/after each Attempt, and disclosed remote-stop uncertainty.
`runs/wb08-prepared-live/config.json` records the exact runtime/image plan; the live
run is under `runs/wb08-live-t1-20261012`.

The authorized run ended after one Attempt: native Harbor `AgentTimeoutError` at
240 seconds, missing WorkflowArtifact, unknown process result, null score and no
development/final replay. The unchanged selection policy blocked continuation;
the two-Attempt allowance did not authorize overriding that gate. Frozen Evidence
confirms two successful actual internal-Codex MCP calls (`get_chat`, `list_messages`),
complete freeze, no pending calls and no violations. This proves live authentication
and actual tool use, not successful generation. Stop is confirmed and cleanup errors
and residual resources are empty; the owned submission containers were independently
checked absent. Native allowance was available before/after (29% consumed in both
observations). The reported wall time, including setup/stop/account checks, is 252.36 s.

The first live run did not retain internal Codex sessions from its temporary home.
Consequently internal-call count, tokens/cost and the reason for unfinished execution
remain unknown; the three archived decisions observed before stop are not proof of
specific model-call counts or completion. This diagnostic integration defect is fixed
by writing only native sessions directly into Harbor's existing log directory, with
auth/config kept in the ephemeral home. Cancellation stops the container before
agent-finally code, so a post-run copy cannot reliably preserve these logs.

The native-session retention regression failed for the expected missing-log reason
under `runs/wb08-session-retention-red`, then passed under
`runs/wb08-session-retention-green`. The final real Docker matrix passed all five
termination/provider controls in 126.16 s under `runs/wb08-session-final-controls`.
The stock internal Codex/provider-stub control retained real `session_meta` JSONL;
the four stop controls retained their session through cleanup. All checks assert
no collected `auth.json`, complete freezes, no late workflow and confirmed cleanup.
The final fast suite passed 286 tests; Ruff lint/format and `git diff --check` passed.

```sh
uv run --locked --offline pytest -q 'tests/integration/test_sapiens.py::test_sapiens_stops_host_and_late_child[timeout]' --run-integration --e1-config runs/wb07-completion-review/images/config.json --sapiens-config runs/wb08-unique-builder/config.json --basetemp runs/wb08-session-retention-green --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_sapiens.py -k 'stops_host or stock_codex_failure' --run-integration --e1-config runs/wb07-completion-review/images/config.json --sapiens-config runs/wb08-unique-builder/config.json --basetemp runs/wb08-session-final-controls --log-cli-level=INFO
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
git diff --check
```

After that first run, the remaining step was a separately authorized repeat with
retained sessions to distinguish execution time from a model/runtime defect.
The 600-second repeat below resolves the artifact-generation blocker and records
the subsequent n8n execution failure. No candidate repair or scoring change was made.

The run uses the production Sapiens image, an unchanged frozen WB-07 T1 Task and WB-06 method,
explicit model authorization, explicit native subscription auth and finite limits.
The shared preflight checks live subscription allowance before/after each Attempt;
API-billed mode remains closed without independently verified provider enforcement.
Sapiens may perform multiple internal Codex calls inside one Attempt. Its native
per-Call budget is 1800 seconds; Harbor's configured submission deadline bounds the
whole Attempt and stops local work sooner. Local stop cannot prove cancellation of
already accepted remote computation or exact remaining provider cost.

The pin advertises a newer Codex minimum in its separate installation preflight
(`0.156.1`); this spike deliberately uses WB-07's existing `0.118.0` for the same
runtime comparison. Actual model-free host/CLI/Codex MCP checks, rather than that
advertised minimum, establish compatibility tested here. A live incompatibility
must be recorded; upgrading Codex changes harness configuration and requires controls.

The authorized command:

```sh
uv run --locked --offline python -m workflow_bench.cli --sapiens --authorize-model --codex-auth "$HOME/.codex/auth.json" --config runs/wb08-prepared-live/config.json --task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --output runs/wb08-live-t1-20261012
```

## Authorized 600-second repeat

After the first live timeout, the owner requested increasing Sapiens' timeout.
Prepared `runs/wb08-prepared-live-600/config.json`: submission timeout 600 seconds
(current-work choice), retaining the same image, model/reasoning, 40 exploration
tool calls per Attempt and 1800-second overall deadline. The old 240-second config
and run remain historical evidence. Runtime schema validation and comparison confirm
this is the only configuration change; no credentials were read for preparation.

The owner explicitly authorized a new live run with these limits in this chat
on 12 October 2026. It uses the fixed native-session collection and fresh output
root `runs/wb08-live-t1-600-20261012`, with the unchanged Task and selection policy;
unknown outcomes still block continuation.

The repeat completed one genuine Sapiens submission: native CLI `Completed` after
455.03 seconds of observation, valid native-collected `workflow.json` (hash
`865d02ccd5077a18baeaab02df13637a7accc66ef69b9152c090ecd79211658b`), completed
process, confirmed stop and empty cleanup/residual records. Creation including
setup/stop/account checks took 466.61 seconds. The production image and three
retained native Codex sessions prove the live internal runtime path. Four admitted
MCP calls occurred: two `get_chat`, two `list_messages`. Eight additional `get_chat`
and three unsupported requests were rejected, not admitted tool effects. Native
allowance was available before/after, with consumption 29% → 30%; this account-wide
coarse observation is not an exact per-run cost measurement. Multiple sessions leave
the existing aggregate token/model-call/cost metrics unknown; raw session refs remain.

All five unchanged development cases then reproduced native n8n
`ExpressionExtensionError: invalid syntax`, with error context parameter `jsonBody`.
Each replay failed with exit code 1 before any admitted replay tool call or terminal
claim. Independent verification returned business fail/partial; report completeness
is unavailable and numeric score null. The unchanged WB-06 selection gate retained
the valid artifact but blocked a second Attempt and private final. No manual repair,
extra model calls, Task/rubric/scoring change or gate bypass was made.

Evidence: `runs/wb08-live-t1-600-20261012/report.json`,
`attempt-1/creation/creation.json`, native agent `sessions/`, native
`artifacts/work/workflow.json`, and `attempt-1/development/report.json`; every case
has its native `harbor/agent/execute.log` with the same safe error classification.
Submission and all replay stops, isolation and fresh databases are confirmed; overall
cleanup errors/residual resources are empty. A schema-valid generated artifact is
distinct from an executable n8n workflow and from successful T1 Evaluation.

The integration spike now demonstrates a genuine model-generated artifact through
native Harbor collection. The remaining E3 blocker is reproducible generated n8n
expression failure. Resolving it requires an owner decision on a separately authorized
candidate-correction experiment under the existing method; no further timeout increase
or Sapiens/Harbor integration change is justified by this error alone.

```sh
uv run --locked --offline python -m workflow_bench.cli --sapiens --authorize-model --codex-auth "$HOME/.codex/auth.json" --config runs/wb08-prepared-live-600/config.json --task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --output runs/wb08-live-t1-600-20261012
```

## Publication scope

The original spike and live experiments ran without commits or pushes. On
12 October 2026 the owner subsequently requested publishing the integration in
one commit on a separate branch. Only WB-08 code, tests and documentation enter
that commit; ignored runs, credentials, generated artifacts and unrelated research
stay outside it. Publishing the integration does not mark successful E3 complete.
