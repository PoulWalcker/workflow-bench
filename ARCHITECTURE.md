# Workflow Bench architecture

Workflow Bench measures Sapiens on autonomous tasks; comparison with another
configuration is optional. [SPEC](SPEC.md) owns product requirements and
[GLOSSARY](GLOSSARY.md) owns terms. This document describes surviving code and
extension rules, rather than claiming the whole product flow is implemented.

## Execution boundary

Use native `harbor run`: Harbor owns job scheduling, trials, environment lifecycle,
agent invocation, artifact collection, verifier execution and native result files.
[pyproject.toml](pyproject.toml) pins Harbor to 0.24.0; [uv.lock](uv.lock) locks dependencies.
Workflow Bench supplies harness integration and shared validation, evidence,
reward and lifecycle helpers. Task authors own business criteria and checks.
There is no Workflow Bench execution CLI or second trial engine in this checkout;
the `wb` command checks tasks, launching native `harbor run` controls, and reports
saved Harbor jobs offline.

Harbor's native task layout uses `task.toml`, public `instruction.md`,
`environment/`, private `tests/` and oracle `solution/`. Compose sidecars, MCP
configuration, artifacts and verifier collection use Harbor's contracts.
Keep untrusted execution separate from private verification; Harbor's mechanisms
must be configured and checked for each environment, not assumed from a prompt.
Service exports need protected provenance; candidate logs cannot prove effects.

The shared harness image `agents` ([environments/agents](environments/agents)) holds
a pinned Python base, procps, one pinned Codex CLI, pinned Sapiens source and the
Workflow Bench evaluation and observation-window helpers (`contracts`, `data`,
`evaluation`, `window` copied from this checkout, with runtime dependencies at
their `uv.lock` versions), and no task content.
The Sapiens source is archived from its committed revision before the build, so local
worktree changes do not enter the image. Task environment images
build `FROM` it, so agents need no network to install a harness and separate verifiers
can import the helper. The tag does not change with the helper, so the image must be
rebuilt after changing those modules; `wb check-task` and the integration preflight
reject a base image whose helper files differ from this checkout. Tasks follow the
[task authoring regulation](docs/agents/task-authoring.md); the checkout holds one
trivial task, [tasks/l1-basket-total](tasks/l1-basket-total), and no simulated service
implementation. The retained helpers and
schemas do not establish the complete flow required by SPEC. Native Harbor results
remain the source facts; reporting one configuration needs no comparison baseline.

## Existing components

| Component | Current responsibility |
|---|---|
| [data](src/workflow_bench/data.py) | Bounded regular-file reads, strict JSON decoding, packaged Draft 2020-12 schemas and local-only schema references. `DataError` exposes a safe code and relative label. |
| [contracts](src/workflow_bench/contracts.py) and [wire schema](src/workflow_bench/resources/wire.schema.json) | Typed exchange values and JSON envelopes. Criterion and Evaluation describe the verifier's `evaluation.json`; Evidence keeps its legacy identity fields until the evidence rework. |
| [evaluation](src/workflow_bench/evaluation.py) | `evaluate` validates task-owned criterion results and derives the verdict (a proven violation is `fail` even beside unknowns) and completeness (`complete` only without unknown criteria or errors). `harbor_reward` gives `1.0`/`0.0` only for a complete evaluation; `write_evaluation` writes `evaluation.json` and, only then, `reward.json` into the verifier directory. `read_evidence` checks supplied identity, revisions, event sequences, call consistency, references and freeze completeness; returns `FrozenEvidence` with the exact byte hash. `resolve_ref` reads JSON pointers. |
| [window](src/workflow_bench/window.py) | `python -m workflow_bench.window` executes one task-owned schedule in a `main` collect hook after the agent phase, with bounded sampling, drops and snapshots; `read_window` validates collected window evidence for task verifiers and later `compare` metrics. The image supplies the helper, while the task supplies the schedule and business criteria. Window evidence is candidate-reachable in the agent environment. |
| [readiness](src/workflow_bench/readiness.py) and [cli](src/workflow_bench/cli.py) | `wb check-task` checks a task's layout and `task.toml` rules (via Harbor's task parser) and that the local base image named by the task's final `FROM` carries this checkout's helper files (`stale:`/`unverified:agents_helper` otherwise; never pulled), then runs native `harbor run` with the `oracle` and `nop` agents through `DeadlineDockerEnvironment`, requiring verdicts `pass` and `fail` from the trial's `evaluation.json`. Prints a JSON report on stdout; Harbor's console output and progress logs go to stderr. |
| [comparison](src/workflow_bench/comparison.py) and [cli](src/workflow_bench/cli.py) | `wb compare <job-dir>…` reads Harbor job directories offline (each argument is `<jobs-dir>/<job-name>`, checked by its `config.json` job name; every subdirectory is a Trial). Each Trial with a Harbor `result.json` gets one outcome: `infra_error` when its agent never started (`setup_failed`), an artifact manifest entry failed (`artifacts_failed`), Harbor never began the verifier phase (`verifier_skipped`), the verifier was not `separate` (`verifier_not_separate`), `verifier/evaluation.json` is missing or invalid, or a pass or complete evaluation lacks Harbor's verifier result (`verifier_result_missing`: the candidate can write that directory until a started separate verifier clears it); otherwise the evaluation verdict, also after an agent timeout or non-zero exit. Harbor's reward value is ignored, so a missing reward is never 0. Trials without a readable `result.json` (running or killed) are listed apart as incomplete. Groups by task name and checksum and by configuration (harness name/version, model, base reasoning effort, requested reasoning-summary setting and web-search setting). JSON retains the v0 outcome counts, rates and medians with known counts of agent seconds, input/cached/output tokens and Sapiens session count; it adds valid count, pass^3 over valid Trials (null below three), validated failed/unknown criterion counts, bounded Codex session effort and summary-presence counts, a session median from saved sessions with Harbor metadata fallback, and a per-level summary. It also adds per-Trial Sapiens `delegation` diagnostics (status, participating Sapi, delegations, specialists created, decision steps by node) and per-pair `{known, delegated, unknown}`; absent snapshots are null, truncated or invalid source collections make dependent values unknown. Markdown adds a `Delegated` column and per-Trial section with agent-environment provenance. When a task has at least two configurations, comparison labels it comparable or lists all unequal/missing-condition reason codes; it makes no better/worse verdict. Level is read from the recorded task directory only when Harbor's directory digest matches the Trial lock. `--format summary` presents each Trial's native phase timing, the report's outcome class, validated evaluation, tokens, session count, delegation diagnostics, manifest status and key file paths; it does not recalculate outcomes. |
| [pricing](src/workflow_bench/pricing.py) | Reads and validates explicit dated API price JSON. One formula estimates USD from Harbor input (including cached), cached input and output tokens for both harnesses; missing prices or token facts remain unknown. It is also used by `collect_codex_usage`. `wb compare` adds per-Trial and per-pair cost estimates without changing outcome classification or existing report fields. |
| [transcript](src/workflow_bench/transcript.py) | `wb compare --transcript` reads saved Codex sessions and the Sapiens state snapshot under each Trial's agent logs, then renders a Markdown chronology and verifier footer. It reuses `compare`/`summarize` for outcome facts; missing sources stay marked missing. It selects message/tool/decision fields and redacts recognized credential and account identifiers. `--full-prompts` expands Sapiens node prompts without changing saved facts. |
| [mcp](src/workflow_bench/mcp.py) | Newline JSON-RPC over stdio: initialize, ping, list public tools and forward permitted calls to HTTP with a bearer capability. Disables ambient HTTP proxies, does not retry writes or export admin tools, and reports transport uncertainty. |
| [composer](src/workflow_bench/composer.py) | Codex preflight, live subscription allowance reads and usage extraction. `SessionSafeCodex` retains Harbor's agent loop while bounding native session ingestion and blocking candidate trajectory fallback. The filename is historical; no workflow composition engine remains. |
| [Sapiens integration](src/workflow_bench_integrations/sapiens.py) | `SapiensInstalledAgent` uses Harbor's Codex configuration/auth/MCP seams. Checks a prepared image's Sapiens revision and Codex installation, creates fresh homes, starts the unmodified Sapiens host, submits once, then polls its public `/api/state` snapshot across two consecutive quiet Pulse ticks; Sapiens owns planning and delegation. Each adapter `doctor`/`chat` attempt gets a safe `phase=sapiens-cli` line, and observed turn/workload state changes get `phase=sapiens-transition` lines. Host stdout/stderr remain in `agent/sapiens-host.txt`; the pinned revision has no host log-level option. Routine-origin turns and workloads do not hold completion or become agent outcomes; only activity attributable to a wholly routine batch is ignored. Waiting, failed, interrupted and unresolved admin terminal states return as agent outcomes so Harbor can run the verifier. On terminal observation it invokes the bounded [state exporter](src/workflow_bench_integrations/sapiens_state.py) inside the agent environment; selected agents, turns, calls, decisions and transitions go to Harbor's agent log directory, with bounded masked routines and selected routine/task-type origins when present. If the terminal snapshot lists routines, one detached exporter atomically refreshes the state every 15 seconds for at most 3600 seconds, using the same masking source, redirected stdio and a recorded pid. Harbor container stop ends the host and exporter. SQLite, WAL, workspaces, notes and auth files stay out of collection. An export failure is diagnostic only. |
| [harbor helpers](src/workflow_bench/harbor.py) | `DeadlineDockerEnvironment` bounds native stop and buffered/streamed collection cleanup, and logs UTC phase results for environment start, stop and confirmed native deletion with `env=agent`/`env=verifier`. After separate verifier teardown it logs one summary from validated `evaluation.json` or `unavailable` when unreadable. `_cleanup`, `LifecycleFacts`, `docker` and `assert_stopped` record or check Compose-project-scoped residual resources using bounded metadata queries. |

Comparison counts a criterion status once per Trial only when a separate Harbor verifier
result confirms the evaluation's producer. It resolves agent network policy through
Harbor's task and Trial settings and applies Harbor's timeout cap and multiplier before
deciding comparability. Task digest verification reads at most 4096 entries and 64 MiB;
an unverified directory has level `unknown`. Markdown qualifies observed session effort
and summary counts when some session files are unavailable.

Dependency direction: Sapiens integration → composer/data/contracts and Harbor;
composer → data/contracts, pricing, harbor helpers and Harbor;
evaluation → data/contracts; window → data; mcp → data/contracts;
cli → readiness, comparison, pricing, transcript and composer; comparison → pricing and transcript (bounded session and Sapiens state readers);
transcript → comparison (type hints only);
observability → comparison (evaluation reader), transcript (pattern masking);
readiness → comparison (evaluation reader);
both → data/contracts and Harbor.
Core modules do not import the Sapiens integration or application business rules.
New environment and agent run-result diagnostics use UTC ISO 8601 `at=` timestamps with
`phase=`, `result=` and elapsed `duration=` fields in Trial logs. The trivial
task verifier writes the same shape to its captured stdout after evaluation.
The host verifier line reads only validated `evaluation.json`, reports the verdict,
criterion count and failed ids, and uses `unavailable` if the file cannot be read.
Sapiens CLI lines include a bounded excerpt after submitted chat argument removal
and the existing best-effort pattern masking. Transition lines use only known state
names or `other`, and omit unchanged polls. These lines are diagnostic and do not feed
verdict or reward calculation.

Schemas load through `importlib.resources`, without checkout/cwd lookup or remote
schema fetching. Nested JSON values remain mutable despite frozen outer containers.
Evidence validation and a hash establish consistency and byte identity, not producer
trust. The caller must supply protected facts and the expected identity.
Evaluation helpers derive a verdict only from criterion results the task's verifier
supplies; they do not implement task business rules, perform semantic judging or
classify every native Trial outcome.

MCP trusts host-installed tool/connection shapes and relays tool payloads without
schema validation. The service must enforce authorization, business semantics and
limits. HTTP status and successful transport do not establish committed effects.
Protocol responses alone belong on the MCP process's stdout.

`wb preflight --auth-path <path>` reads live ChatGPT subscription allowance through
`read_codex_limits` in a temporary host Codex home. It returns JSON with `allowed`,
validated quota windows and observation time, or a safe rejection reason; it never
launches a model. Unknown/malformed allowance, exhausted windows and native spend
control denial block admission. Account ids, credentials and unrecognized response
fields are omitted. The pinned Codex 0.162.1 account protocol is verified from its
local generated schema and fixture responses; live allowance still requires an
authorized credential read. Native `harbor run` does not enforce this check or owner
authorization automatically; apply SPEC's readiness, allowance and limits gates
before every live Trial. API-billed measurement remains unauthorized without the
required external spending constraint.

[The direct job example](examples/codex/job.yaml) uses native Harbor agent options:
`SessionSafeCodex`, pinned version, model, reasoning effort and inline Codex config.
Its default provider is an unused container loopback port with no authentication,
so the command is a model-free startup/failure control. Explicit empty credential
paths/keys and `CODEX_FORCE_AUTH_JSON=FALSE` override ambient credentials. Uppercase
`FALSE` avoids Harbor 0.24.0's text scrubber replacing JSON's lowercase `false`.
MCP servers come from the task's native configuration; the trivial task needs none.
On cancellation, `SessionSafeCodex` recovers only validated, bounded session files
from the stopped container through `DeadlineDockerEnvironment` (10-second recovery
deadline), because native Codex's final in-container copy can no longer execute.
Docker copy streams an uncompressed archive into bounded memory (32 MiB payload
plus 1 MiB archive overhead); oversized transfers are stopped without extracting
anything to host disk. Before writing JSONL snapshots, validation rejects unsafe
paths, links, special files, invalid JSON and trees beyond 256 entries/depth 8.
The Docker controls cover a fake executable's answer and private-file isolation,
real pinned Codex's native session parsing and state-based failure, and cessation
of a detached late writer on timeout and SIGINT.

`collect_codex_usage` uses one session's last cumulative totals, preserving missing,
ambiguous or malformed values as unknown; optional supplied prices use the shared
estimate formula in `pricing.py`.
`collect_sapiens_usage` sums the last cumulative `token_count` of every validated
native Codex session, and records the session count in Harbor agent metadata. Missing
or invalid session totals remain unknown, never zero; `wb compare` reports token
medians and the session-count median, with the per-Trial values in summary mode.
The Sapiens adapter polls `/api/state` for all turns, workloads and `run_activity`.
It returns after two distinct consecutive quiet `bpm60` Pulse ticks over admin work.
Routine-origin work is excluded; unknown or mixed-batch activity remains busy. Harbor's agent
timeout bounds the observation loop; timeout/cancellation follows the same
`DeadlineDockerEnvironment` stop path as direct Codex. A terminal Sapiens agent
state is diagnostic; the independent verifier determines the Trial outcome.
The adapter writes observation start and terminal decision lines to the Trial log.
The decision line records safe turn/workload state names, whether `run_activity`
was empty, and the consecutive quiet-tick count; an interrupted observation has
no terminal decision line.
Each observed turn-status or workload-state change is logged with an observation
time and safe id. The first observed state starts from `none`; later unchanged
polls add no line. The adapter logs every host CLI `doctor` attempt and the one
`chat` submission without logging the chat command or instruction.

`DeadlineDockerEnvironment` installs a cancellation callback that kills the main
candidate container and confirms it is no longer running before cancelling the
Docker output collector. The stopped container remains available for native artifact
copy and Harbor-owned teardown; candidate children cannot mutate it during collection.
A caller can replace `cancel_writer` for a different writer boundary. Native `stop`
and collection cleanup have finite deadlines. Select the class through Harbor's
`--env workflow_bench.harbor:DeadlineDockerEnvironment` (or native job config) and
supply `cleanup_timeout_sec` through `--ek`/environment kwargs. The integration
controls exercise Harbor 0.24.0's private collector/Compose interfaces; recheck on
upgrade. This proves local container cessation, not remote provider computation
or billing stopped.

## Extension rules

- A new Task using supported contracts and existing capabilities changes only its
  own native Harbor directory: public intent, environment, private criteria/checks
  and oracle. Business rules stay there; core and common prompts do not supply solutions.
- A new Harness integrates at Harbor's agent seam, selected by native job configuration
  or `--agent-import-path`. It owns planning and model/tool use; core does not branch
  on task or harness names. Prepare and pin its dependencies before measurement.
- A new Simulated service is a reusable Workflow Bench image plus the task's Compose
  declaration, seed and permitted API/MCP tools. The task connects it through native
  Harbor configuration; the service owns mutable state and protected evidence export.
  This is an extension rule, not an existing service or image in this checkout.

## Parameter sources

Keep one effective source per parameter; do not add competing Workflow Bench overrides.
The table records current entry points and constants, including explicit precedence
where a retained interface supports alternatives. Resolve user paths once at entry.

| Parameter | Existing source |
|---|---|
| Task selection, output location, trial count, concurrency, agent selection | Native Harbor CLI/job configuration; record Harbor's resolved configuration. No Workflow Bench wrapper defaults. |
| Task images, resources, network, timeouts, MCP servers and collected outputs | Native task/Compose configuration, resolved with explicit Harbor job overrides. No runtime-helper object automatically overrides these. |
| `agents` image content: base image digests, Debian package version, installed Codex CLI version and evaluation helper dependency versions | [environments/agents/Dockerfile](environments/agents/Dockerfile) pins these, with Codex CLI 0.162.1. Helper dependency versions come from [uv.lock](uv.lock) through [lock_requirements.py](environments/agents/lock_requirements.py); the lock and helper sources come through Compose's `project` context. |
| Sapiens source path and revision in `agents` | The one source path argument to [environments/agents/build.sh](environments/agents/build.sh) resolves to a repository root. The script requires its HEAD to match [SAPIENS_REVISION](environments/agents/SAPIENS_REVISION), archives only the committed `sapiens`, `prompts`, `web`, `license` and `sapiens4` paths into a temporary Compose context, and writes `REVISION`. The Dockerfile checks that revision, places `/opt/sapiens` on Python's import path and records it in the `org.workflow-bench.sapiens.revision` image label. No source machine path is stored in the image. |
| `agents` image tag | [environments/agents/compose.yaml](environments/agents/compose.yaml) `image` (`workflow-bench-agents:codex-0.162.1`); task Dockerfiles reference it in `FROM`. The tag names the Codex version; the label names the Sapiens revision. |
| Observation-window schedule and evidence destination | The repeated Task's `environment/schedule.json` and `task.toml` collect hook/artifacts; the shared image supplies only the driver. The schedule fixes offsets, watched paths, drops, snapshots and bounds. |
| Model-provider hosts during a repeated window | Native Harbor job `environment.extra_allowed_hosts`, applied to the whole agent environment including its collect hook. The Task's baseline stays `no-network`; the separate verifier stays offline. |
| Model, Codex CLI version and effective config | Native Harbor agent configuration/options inherited by `SessionSafeCodex` and Sapiens. Sapiens derives its model env from the native model selection. A requested Codex version must equal the one installed in the `agents` image; otherwise Harbor attempts a networked install. |
| Reasoning effort | Sapiens requires `model_reasoning_effort` in native Harbor agent `config` (TOML file or inline mapping), copied to `SAPIENS_CODEX_REASONING_EFFORT`; a missing key raises `KeyError` before submission. [The Sapiens example job](examples/sapiens/job.yaml) sets this and Harbor's separate `reasoning_effort` option from the same declared value. Pinned Sapiens' delegation code raises effort to `xhigh` internally when its execution mode is `deep`; the example does not select deep mode. This internal escalation is a configuration caveat for M2 comparisons. |
| Reasoning summary | Native Harbor `agents[].kwargs.config.model_reasoning_summary` is the single source for both harnesses' effective Codex `config.toml`; both example jobs set `auto`. Harbor's separate `kwargs.reasoning_summary` is a command-line option for Harbor's own `codex exec` only and does not reach Sapiens. The requested setting is part of the measured configuration and is read from the saved Trial config; summary presence is read from reasoning response items' `summary[].text`. Session `turn_context.summary` does not indicate the requested setting or summary presence. |
| Native subscription credential file | Harbor's `CODEX_AUTH_JSON_PATH`; the inherited resolver also supports `CODEX_FORCE_AUTH_JSON` for the native home file. Use an explicit authorized path for benchmark execution. |
| Native API authentication | Harbor's provider environment; Sapiens uses `OPENAI_API_KEY` only when no auth file resolves. This fallback does not authorize API-billed measurement. |
| Subscription preflight credential and deadline | `wb preflight --auth-path <path>` (required, resolved once at CLI entry) and `--timeout-sec` (positive finite seconds, default 30). Reads allowance only; authorization and live-run limits remain separate owner gates. |
| Subscription allowance and account-query deadline | Native account response; `timeout_sec` supplied to `read_codex_limits`. Quota is not inferred from configuration. |
| Usage log path and optional prices | Explicit `logs` and `prices` arguments to `collect_codex_usage`; prices are per million input/cached-input/output tokens and use the same formula as `wb compare`. |
| MCP public contract | Required `--contract` file; `serve` receives the installed contract directly. |
| MCP tool URL and capability | `--connection` file fields `tool_url`/`capability`; only when absent, `WB_TOOL_URL`/`WB_CAPABILITY`. These modes are exclusive, with no per-field merging. |
| MCP HTTP timeout | `--timeout` (default 5 seconds), passed as `timeout_sec` to `serve`. |
| Evidence path, expected identity and JSON pointer | Explicit `read_evidence`/`resolve_ref` arguments. |
| Criterion results and verifier output directory | Explicit `write_evaluation` arguments from the task's verifier; the reward follows from the evaluation, not a separate score. |
| Readiness task directory, jobs directory and deadlines | `wb check-task <dir> --jobs-dir <path>` (required), `--run-timeout-sec` per control run (default 900) and `--cleanup-timeout-sec` for teardown and interruption (default 60, also passed to `DeadlineDockerEnvironment`). Paths resolve once at entry; Harbor's own trial timeouts come from `task.toml`. The helper image check has a fixed 60-second deadline. |
| Report inputs, API prices and format | `wb compare` positional Harbor job directories and optional `--prices <file>` (both resolved once at entry; repeated jobs rejected). The tracked dated source is [prices/openai-api-2026-10-14.json](prices/openai-api-2026-10-14.json); the explicit file supplies per-Harbor-model input, cached-input and output USD rates per million tokens, tier, context band, retrieval date and source URL. Missing prices or token facts leave estimates unknown. `--format json\|markdown\|summary` (default `json`), or `--transcript` with optional `--full-prompts` on stdout. Transcripts use best-effort pattern masking and read no host auth source; they add no output path or separate transcript configuration file. |
| Cleanup deadline, resource ownership and stop subset | `cleanup_timeout_sec` constructor/helper argument; explicit Compose `project`, optional `services` and `deleted` arguments. Docker metadata queries have a fixed 10-second deadline. |
| Sapiens revision, internal host address/port, data directory and startup polling | Adapter constants `SAPIENS_REVISION`, `HOST_URL`/`HOST_PORT`, `DATA_DIR` and fixed polling bounds; the loopback listener is inside the agent environment, not a required host port. |
| JSON/evidence/session bounds and protocol/schema versions | Packaged schema and module constants in `data`, `composer`, `mcp`; protocol limits are not independent CLI settings. |
| Python, Harbor and development dependency versions | [pyproject.toml](pyproject.toml), [uv.lock](uv.lock) and [.python-version](.python-version), with setup commands in [README](README.md). |

## Not doing

- A custom orchestrator, duplicate run/fact tree, global scheduler or second runtime.
- A workflow DSL/compiler, mandatory workflow artifact or hidden repair loop.
- Plugin registries, universal backends, speculative factories or DI frameworks.
- Task-specific harness presets, specialists or memory in measured initial state.
- Harness-specific process criteria in the verdict; these remain diagnostics.
- Core branching on task, application or harness names.
- Live remote business services in the MVP; permitted model-provider access is separate.
