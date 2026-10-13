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
There is no Workflow Bench execution CLI or second trial engine in this checkout.

Harbor's native task layout uses `task.toml`, public `instruction.md`,
`environment/`, private `tests/` and oracle `solution/`. Compose sidecars, MCP
configuration, artifacts and verifier collection use Harbor's contracts.
Keep untrusted execution separate from private verification; Harbor's mechanisms
must be configured and checked for each environment, not assumed from a prompt.
Service exports need protected provenance; candidate logs cannot prove effects.

The checkout has no benchmark task, simulated service implementation, image builder,
automated readiness check or offline report command. The retained helpers and
schemas do not establish the complete flow required by SPEC. Native Harbor results
remain the source facts; reporting one configuration needs no comparison baseline.

## Existing components

| Component | Current responsibility |
|---|---|
| [data](src/workflow_bench/data.py) | Bounded regular-file reads, strict JSON decoding, packaged Draft 2020-12 schemas and local-only schema references. `DataError` exposes a safe code and relative label. |
| [contracts](src/workflow_bench/contracts.py) and [wire schema](src/workflow_bench/resources/wire.schema.json) | Retained typed exchange values and JSON envelopes for evidence and evaluation; these still have legacy identity fields, rather than a new native Trial outcome schema. |
| [evaluation](src/workflow_bench/evaluation.py) | `read_evidence` checks supplied identity, revisions, event sequences, call consistency, references and freeze completeness; returns `FrozenEvidence` with the exact byte hash. `resolve_ref` reads JSON pointers. `harbor_reward` maps an already evaluated numeric score only when complete, error-free and without unknown criteria. |
| [mcp](src/workflow_bench/mcp.py) | Newline JSON-RPC over stdio: initialize, ping, list public tools and forward permitted calls to HTTP with a bearer capability. Disables ambient HTTP proxies, does not retry writes or export admin tools, and reports transport uncertainty. |
| [composer](src/workflow_bench/composer.py) | Codex preflight, live subscription allowance reads and usage extraction. `SessionSafeCodex` retains Harbor's agent loop while bounding native session ingestion and blocking candidate trajectory fallback. The filename is historical; no workflow composition engine remains. |
| [Sapiens integration](src/workflow_bench_integrations/sapiens.py) | `SapiensInstalledAgent` uses Harbor's Codex configuration/auth/MCP seams. Checks a prepared image's Sapiens revision and Codex installation, creates fresh homes, starts the unmodified Sapiens host, submits once, then observes through its CLI; Sapiens owns planning and delegation. |
| [harbor helpers](src/workflow_bench/harbor.py) | `DeadlineDockerEnvironment` bounds native stop and buffered/streamed collection cleanup. `_cleanup`, `LifecycleFacts`, `docker` and `assert_stopped` record or check Compose-project-scoped residual resources using bounded metadata queries. |

Dependency direction: Sapiens integration → composer/data/contracts and Harbor;
composer → data/contracts and Harbor; evaluation → data/contracts; mcp → data/contracts.
Core modules do not import the Sapiens integration or application business rules.

Schemas load through `importlib.resources`, without checkout/cwd lookup or remote
schema fetching. Nested JSON values remain mutable despite frozen outer containers.
Evidence validation and a hash establish consistency and byte identity, not producer
trust. The caller must supply protected facts and the expected identity.
Evaluation helpers do not implement task business rules, assemble verdicts, perform
semantic judging or classify every native Trial outcome.

MCP trusts host-installed tool/connection shapes and relays tool payloads without
schema validation. The service must enforce authorization, business semantics and
limits. HTTP status and successful transport do not establish committed effects.
Protocol responses alone belong on the MCP process's stdout.

Codex preflight is a callable helper: isolated model-free mode returns zero calls;
subscription mode requires explicit authorization, an auth path and a runtime
object checked against the retained [runtime schema](src/workflow_bench/resources/e1.schema.json).
That schema still contains legacy runtime fields; no current launcher applies them
to Harbor. API-billed mode is closed by preflight without verified external spending
limits. `read_codex_limits` reads live native account allowance in a temporary host
Codex home; callers must enforce the authorization and continuation rules in SPEC.
These helpers are not automatically wired into `harbor run`.

`collect_codex_usage` uses one session's last cumulative totals, preserving missing,
ambiguous or malformed values as unknown; optional supplied prices give an estimate.
Sapiens saves internal session logs but currently sets `model_usage = {}`; it does
not aggregate all delegated sessions. It waits for the Chief turn's `Completed`
state and raises on another terminal state; this neither proves all delegated work
stopped nor supplies an outcome verdict. SPEC requires assessment from resulting
state; that lifecycle integration is not established by the retained adapter.

`DeadlineDockerEnvironment` can invoke an optional caller-installed `cancel_writer`
callback before collector cancellation; killing a host Docker client alone does
not confirm container children stopped. Select this class explicitly through
Harbor's `--environment-import-path workflow_bench.harbor:DeadlineDockerEnvironment`
and supply `cleanup_timeout_sec` as environment kwargs. No callback is installed
by the class itself. Native lifecycle remains Harbor-owned; private-method coupling
requires renewed checks when Harbor changes. Fast checks do not prove real Docker
isolation, delegated cessation or provider billing stopped.

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
| Model, Codex CLI version and effective config | Native Harbor agent configuration/options inherited by `SessionSafeCodex` and Sapiens. Sapiens derives its model env from the native model selection. |
| Reasoning effort | Sapiens requires `model_reasoning_effort` in native Harbor agent `config` (TOML file or inline mapping), copied to `SAPIENS_CODEX_REASONING_EFFORT`; a missing key raises `KeyError` before submission. `SessionSafeCodex` supports native Codex config and the separate `reasoning_effort` option; that option does not replace Sapiens' required config key. |
| Native subscription credential file | Harbor's `CODEX_AUTH_JSON_PATH`; the inherited resolver also supports `CODEX_FORCE_AUTH_JSON` for the native home file. Use an explicit authorized path for benchmark execution. |
| Native API authentication | Harbor's provider environment; Sapiens uses `OPENAI_API_KEY` only when no auth file resolves. This fallback does not authorize API-billed measurement. |
| Preflight mode, image digest, CLI version, model, reasoning, exploration limit and authentication | Required caller-supplied `composer` mapping to `codex_preflight`; it validates a declaration, not the installed image or provider enforcement. |
| Preflight authorization, auth path, budget and runtime fields | Explicit `authorized`, `auth_path`, `budget`, `runtime` arguments; subscription requires no API budget object. No corresponding Workflow Bench CLI exists. |
| Subscription allowance and account-query deadline | Native account response; `timeout_sec` supplied to `read_codex_limits`. Quota is not inferred from configuration. |
| Usage log path and optional prices | Explicit `logs` and `prices` arguments to `collect_codex_usage`; prices are per million input/cached-input/output tokens. |
| MCP public contract | Required `--contract` file; `serve` receives the installed contract directly. |
| MCP tool URL and capability | `--connection` file fields `tool_url`/`capability`; only when absent, `WB_TOOL_URL`/`WB_CAPABILITY`. These modes are exclusive, with no per-field merging. |
| MCP HTTP timeout | `--timeout` (default 5 seconds), passed as `timeout_sec` to `serve`. |
| Evidence path, expected identity and JSON pointer | Explicit `read_evidence`/`resolve_ref` arguments; numeric score and criteria come from supplied evaluation, not the reward mapper. |
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
