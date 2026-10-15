# Workflow Bench

A small research tool for testing AI on business tasks with simulated tools and
independent checks. Product requirements are in [SPEC](SPEC.md), terms in [GLOSSARY](GLOSSARY.md),
and current technical capabilities in [ARCHITECTURE](ARCHITECTURE.md).
This checkout keeps only the components that work without the previous
n8n-workflow replay path; that path, its Task, simulator, image builders and
Docker controls are preserved at tag `n8n-replay-final`.

## Setup

Run from the checkout root in a POSIX shell. Requires uv and Python >=3.12; the
checked local baseline is macOS arm64, CPython 3.12.13 and uv 0.12.4. Python/cache
remain local; first setup needs network access. Offline restoration requires a filled
cache. Dependency/build/tool versions are owned by [pyproject.toml](pyproject.toml),
[uv.lock](uv.lock) and [.python-version](.python-version). Other hosts/versions are
not established by the recorded checks.

```sh
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
uv python install 3.12.13 --no-bin
uv sync --locked
uv lock --check --offline
```

## Verified local commands

These run without Docker/models/credentials.

```sh
uv run --locked --offline pytest -q
uv run --locked --offline pytest --collect-only -q
uv run --locked --offline ruff check
uv run --locked --offline ruff format --check
uv run --locked --offline ty check
uv build --force-pep517 --offline
```

Default pytest excludes integration/model collection/setup; explicit integration
requires `--run-integration`. `--run-model` remains unimplemented and is rejected.

## Agents image

Task environment images build `FROM` the shared harness image; build it before
using them. Building needs Docker, network access and a local checkout of the pinned
Sapiens revision. Pass its repository root as the sole source path argument; the
build archives committed files, excluding local edits and untracked files. The
installed Codex CLI starts without network. Pins and the tag are listed in
[ARCHITECTURE](ARCHITECTURE.md#parameter-sources). Checked with Docker 29.4.0 on
macOS arm64.

```sh
environments/agents/build.sh /absolute/path/to/sapiens4 --no-cache
docker run --rm --network none workflow-bench-agents:codex-0.162.1 sh -c 'cat /opt/sapiens/REVISION && python -m sapiens --help >/dev/null && codex --version'
docker image inspect workflow-bench-agents:codex-0.162.1 --format '{{index .Config.Labels "org.workflow-bench.sapiens.revision"}}'
```

The second command prints the pinned Sapiens revision and `codex-cli 0.162.1`; the
third prints the same revision from the image label. The image also carries the evaluation
helper from `src/workflow_bench`, with dependencies at their `uv.lock` versions; rebuild
it after changing that package or the lock. `wb check-task` reports
`stale:agents_helper` and the integration preflight fails when the image's helper
differs from the checkout.

## Task readiness

Tasks follow the [task authoring regulation](docs/agents/task-authoring.md). Checking one
needs Docker and the `agents` image, but no model or credentials; the native Harbor
jobs of the controls stay under `--jobs-dir`.

```sh
uv run --locked wb check-task tasks/l1-basket-total --jobs-dir "$PWD/runs/readiness"
uv run --locked pytest -q --run-integration tests/integration
```

The first command prints a JSON report with `"ready": true` and exits 0 (about 75 seconds
on the baseline host). The integration controls also check that a task whose no-op run
passes is rejected; they fail, rather than skip, when Docker or the image is missing
or its helper is stale.

## Direct Codex controls

[The native job example](examples/codex/job.yaml) runs the trivial task using
`SessionSafeCodex` and `DeadlineDockerEnvironment`, with one attempt and no retry.
Its absolute `jobs_dir` is `/tmp/workflow-bench-codex`, so Harbor's artifact copy
uses the intended host directory regardless of the task's working directory.
It explicitly disables ambient authentication and points Codex at an unused
loopback port inside the container. These commands use Docker, with no credentials
or model calls:

```sh
uv run --locked harbor run -c examples/codex/job.yaml
uv run --locked wb compare /tmp/workflow-bench-codex/codex-empty-provider
uv run --locked pytest -q --run-integration tests/integration/test_codex_direct.py
uv run --locked wb preflight --help
```

The empty-provider control produces a task `fail`, judged from its missing answer,
including when Codex reaches its finite timeout; it is not an infrastructure error.
The integration suite also proves fake-Codex wiring/isolation and stops a detached
late writer on timeout and cancellation. Repeat the native job with a fresh
`--job-name` because Harbor resumes existing job directories.

Native Harbor owns configuration: agent `model_name`, `kwargs.version`,
`kwargs.reasoning_effort` (CLI `-k reasoning_effort=low`) and `kwargs.config`
(Codex TOML mapping); MCP servers belong to the task. Both example jobs set
`kwargs.config.model_reasoning_summary: auto` as one source for the effective
Codex config in either harness. This requested summary setting is part of the
measured configuration. The example deliberately has no live credentials. An
authorized subscription job must replace its empty-provider
config, select permitted provider networking, set an explicit
`agents[].env.CODEX_AUTH_JSON_PATH` in the job,
and keep finite Trial limits. It must first pass readiness and a fresh
`wb preflight --auth-path <authorized-auth.json>` check. Preflight exits 0 with
`allowed: true`, or 1 with a safe rejection reason; it does not launch a model or
authorize a Trial. Protocol/decision checks are verified with fixtures; a live
subscription read and model smoke require separate owner authorization.

An authorized local smoke on 2026-10-13 completed one real Codex Trial on
`l1-basket-total`: the separate verifier returned `pass`, and `wb compare`
reported one pass with no infrastructure error. It used Codex CLI 0.162.1,
`openai/gpt-6.1-sol`, low reasoning, ChatGPT subscription authentication, and a
task copy whose agent network policy allowed provider access while the verifier
kept the task's no-network baseline. The ignored local evidence is in
`runs/m1a-06-codex/codex-live-smoke-20261013`, with reports at
`runs/m1a-06-compare.json` and `runs/m1a-06-compare.md`. This is one smoke
result, not a reliability estimate.

## Direct Sapiens configuration

[The Sapiens job example](examples/sapiens/job.yaml) uses the same pinned `agents`
image and `DeadlineDockerEnvironment`, an absolute `jobs_dir`, one attempt and no
retry. It supplies both Harbor's reasoning option and Sapiens' required
`config.model_reasoning_effort` with `low`, plus `openai/gpt-6.1-sol` as the model.
Its empty loopback provider and explicit empty credential settings make it a
model-free configuration/control example. The fast configuration test verifies
Harbor builds `SapiensInstalledAgent` with these settings; the Sapiens execution
controls are a separate integration path. Its `kwargs.config.model_reasoning_summary`
requests `auto` through the same effective Codex config as the direct example;
Harbor's separate `kwargs.reasoning_summary` option does not reach Sapiens.

Run the opted-in Sapiens controls with:

```sh
uv run --locked pytest -q --run-integration tests/integration/test_sapiens_controls.py
```

Their real-Codex case uses a test-image loopback endpoint that rejects every
request with HTTP 401 and has no model. Codex 0.162.1 keeps reconnecting to an
unused loopback socket despite zero configured
retries; a definite rejection lets the control verify Sapiens' model-failure outcome
within the finite Trial limit. No provider credential is used.

The adapter observes Sapiens' public state until all turns, workloads and run
activity are quiet for two consecutive Pulse ticks. It reports the sum of last
cumulative token counts over all validated Codex sessions and their session count
in `wb compare`; absent or malformed usage remains unknown. Pinned Sapiens may
raise reasoning effort to `xhigh` internally in deep mode, regardless of the
job's configured base effort. The example uses normal mode.

`trial.log` labels Docker phase lines `env=agent` or `env=verifier`. After a
separate verifier runs, it records a host-side `phase=verifier` line from validated
`evaluation.json` with the verdict, criterion count and failed criterion ids.
Missing or invalid evaluation is logged as `unavailable`; it does not change the
Trial outcome. Sapiens Trials also log each adapter `doctor`/`chat` CLI attempt
with exit code, duration and a masked output excerpt of at most 200 characters,
plus observed turn and workload state changes from `/api/state`. The submitted
chat instruction is excluded from CLI lines. The existing
`agent/sapiens-host.txt` captures host stdout and stderr. These are diagnostics;
the pinned host revision exposes no log-level option in `python -m sapiens --help`.

An authorized local smoke on 2026-10-14 ran one Sapiens Trial on `l1-basket-total`
with Sapiens revision `71e93cb3de00183c263ec440919b313cf92ed8af`, Codex CLI
0.162.1, `openai/gpt-6.1-sol`, low reasoning and ChatGPT subscription authentication.
The separate verifier passed all three criteria, and `wb compare` reported one pass,
75,971 input tokens (56,064 cached), 891 output tokens and three Codex sessions.
The recorded sessions all used low effort; no delegation was observed. The terminal
state was `Completed`, with no observed premature finish.
The ignored local Harbor evidence is in
`runs/m1b-05-sapiens/sapiens-live-smoke-20261014`, with reports at
`runs/m1b-05-compare.json` and `runs/m1b-05-summary.json`. This single smoke result
does not estimate reliability or a per-Trial subscription charge.

## Report

Reporting reads saved Harbor job directories offline and needs no Docker, model or
credentials. Each argument is one job directory, `<jobs-dir>/<job-name>`.

```sh
uv run --locked wb compare "$PWD"/runs/readiness/check-*
uv run --locked wb compare --format markdown "$PWD"/runs/readiness/check-*
uv run --locked wb compare --format summary /tmp/workflow-bench-codex/codex-empty-provider
uv run --locked wb compare --transcript "$PWD"/runs/m1a-06-codex/codex-live-smoke-20261013
uv run --locked wb compare --transcript "$PWD"/runs/m1b-05-sapiens/sapiens-live-smoke-20261014
uv run --locked wb compare --prices prices/openai-api-2026-10-14.json "$PWD"/runs/m1b-05-sapiens/sapiens-live-smoke-20261014
```

The first command prints a JSON report and exits 0: one outcome per Trial and, per
task and configuration, counts, pass rate over `pass`/`fail`, `pass_hat_k` for fixed
`k = 3` (null below three valid Trials), failed and unknown criterion counts from
evaluations confirmed by a separate Harbor verifier result, session
effort and reasoning-summary presence, and medians. Configuration includes the
requested reasoning-summary and web-search settings. Unknown and infrastructure
outcomes remain separate. When a task has at least two configurations, the report
labels their comparison `comparable` or lists all reason codes for unequal or missing
conditions; it gives no better/worse verdict. The per-level section reports covered
tasks, mean task pass rate over those tasks, unknown/infra counts and criterion failures.
Level is `unknown` if the recorded task directory is missing, exceeds the bounded
digest read (4096 entries or 64 MiB), or its Harbor digest no longer matches the Trial
lock. Markdown presents the same descriptive metrics and marks observed session counts
when session evidence is missing.

Each JSON Trial also has `delegation`: `null` when no Sapiens state snapshot was
saved, otherwise a status and the number of participating Sapi, delegations,
specialists created, and decision steps by node. A truncated or invalid source
collection leaves its dependent metrics `null` (unknown). Each task × configuration
pair has `delegation: {known, delegated, unknown}`; it is `null` when no Trial
has a snapshot. Markdown adds a `Delegated` column (`x/n`, plus unknown Trials)
and a per-Trial delegation section. The state snapshot is produced inside the
agent environment and is diagnostic; it does not affect outcomes or comparability.

Each Trial and task × configuration pair also has `repeated`: `null` without
collected `artifacts/window-evidence`, otherwise observation-window diagnostics.
`window` reports the driver's validated status (`not_started`, `running`,
`completed`, `failed`, or a safe `invalid`/`too large` marker), actual elapsed
seconds and delivered drops/snapshots. Planned duration, tail and action counts
come from `environment/schedule.json` only when the saved Trial lock's Harbor
Task digest still matches the local Task. Missing, changed or invalid plans leave
those fields, observed updates and reaction latency unknown; the manifest does
not retain the plan. Preserve that Task directory alongside a saved repeated job
to reproduce these metrics.

`observed_updates` counts changed watched-path digests between consecutive samples
through `duration + tail`; the first sample establishes a baseline. It counts
changed samples, so simultaneous path changes count once. `reaction_latency_sec`
contains one value per actual drop and its known-value median: seconds to the
first changed sample at or after that drop, strictly before the next drop and
through the window end, or `null`. Unsafe/truncated watched-path observations
leave these measurements unknown. They describe evidence, not task correctness.

`mechanism` prefers saved Sapiens routines (`count`, sorted `minutes`). Otherwise
it examines saved Codex `exec_command`, `shell` and `shell_command` function-call
`cmd`/`command` arguments. Native `custom_tool_call` named `exec` also supports the
single literal wrapper `text(await tools.exec_command({cmd:"..."}));` with a
JSON double-quoted command, optional whitespace/semicolon and quoted `"cmd"` key.
Other native JavaScript inputs remain `unknown`; the report never executes them.
Reads are bounded to 4096 commands and 8192 characters per argument, command or
native input. The bounded lexical patterns recognize command-start
`crontab`/`cron`/`crond` (including paths and `sudo`) as `cron`; command-start
`nohup`, `setsid`, `sleep`, `python` with an optional version, `bash`, `sh`,
`while` or `for` together with a standalone background `&` as
`background_process`. Cron takes precedence; other readable commands yield
`none_observed`. Missing, invalid, truncated or over-limit sources yield
`unknown`. This heuristic does not prove that the mechanism ran.

Missing or inconsistent observations of the verified plan's watched paths leave
updates and reaction latency unknown; a sampled `missing` file is a valid
observation.

`llm_firings` counts routine-origin turns created strictly after Harbor's
`agent_execution.finished_at`; matching workload records are not counted again.
If turns are unavailable, routine-origin workloads need their own creation time;
an absent timestamp or explicitly malformed origin is unknown (the current export
retains turn creation times). Valid admin origins do not count as firings.
`window_tokens` sums each session's last cumulative input/cached/output totals
when its first event is strictly after that phase end. Rate-only `token_count`
notifications (`info: null`, `rate_limits` object) do not replace cumulative totals;
sessions without totals and malformed actual totals remain unknown. It requires
valid, untruncated Sapiens state and readable session evidence; Codex window LLM usage
is not observable in its agent logs. `tokens_per_firing`, `window_cost_usd`
(with `--prices`) and `cost_per_firing_usd` use those totals; a zero or unknown
firing denominator leaves per-firing values unknown. Pair numeric summaries
contain `median`, `known` and `unknown`; mechanisms have separate known counts
and unknown Trials. Native outcome, verdict, comparability, pass^3, cost and
delegation fields retain their meanings.

Markdown adds an “Observation window” section only with window evidence, with
pair medians and per-Trial rows. Harbor's token and agent time columns cover the
agent phase only. Window evidence is produced inside the agent environment
(candidate-reachable, diagnostic); these metrics cannot establish completeness
or absence of tampering. When a routine is observed, the report states:
“in the current Sapiens, repetition is only via an LLM call per tick”. Summary
mode includes the same Trial `repeated` object; transcripts list Sapiens routine
ids, minutes and `runCount`, and mark routine-origin workloads.

JSON and Markdown include an estimated USD cost per Trial and the
median, total and known Trial count per task × configuration. The tracked
[price file](prices/openai-api-2026-10-14.json) records the Standard short-context
OpenAI API list prices retrieved on 2026-10-14, by Harbor model id. The report
labels estimates with that date and source URL. It uses Harbor's input tokens
(including cached), cached input tokens and output tokens; the same formula applies
to Codex and Sapiens: `((input - cached) × input_rate + cached × cached_rate +
output × output_rate) / 1,000,000`. A missing price, missing token count or cached count greater
than input gives `unknown`; without `--prices`, every cost is `unknown`. Cache-write
tokens and the long-context band are not modelled. These figures estimate API list
price, not a ChatGPT subscription charge.

With the readiness controls above, `oracle` has pass rate 1.0 and `nop` has 0.0. A
directory that is not a Harbor job exits 2. `--format summary` prints one JSON record
per Trial with native phase timing, the same outcome class as the report, verifier
criteria, token counts, artifact status, delegation diagnostics and paths to
diagnostic files.
`--transcript` prints a read-only Markdown conversation for each saved Trial: the
task, Sapiens decision nodes or Codex messages, tool calls and results, time and
tokens when recorded, and the verifier result. Each step shows a bounded,
best-effort-masked reasoning summary, a no-summary marker when the response is
readable, or an unknown marker when response evidence is missing. A Trial footer
shows the requested setting from the saved Trial config (or `unknown`) and the
number of steps with a summary (also `unknown` when sessions are missing or
incomplete). It shows an unavailable marker when the measured summary count is
zero and the setting is not `none`. Encrypted reasoning is never shown. Sapiens
captures a bounded state snapshot in its Harbor agent log for speaker names,
delegations and transitions. Older Trials without that snapshot show missing-data
markers. Node prompts show a short excerpt by default; add `--full-prompts` to
show their full text. The Sapiens state export masks every occurrence of each
string value of at least 16 characters in the run's `auth.json`, plus
`OPENAI_API_KEY` when set; export reads `$CODEX_HOME/auth.json` in the container.
Transcripts use only best-effort pattern masking for credential and account-ID
forms. Every transcript starts with a notice to check it before sharing.

## First L1 report (2026-10-14)

The first five-task L1 run completed 30 Trials in 15 jobs: Sapiens and direct Codex
each passed 3/3 on every task. Both used `openai/gpt-6.1-sol`, base reasoning
`medium`, reasoning summaries `auto`, web search disabled, the same 1800-second
agent limit and provider allowlist, and Codex CLI 0.162.1. Sapiens used pinned
revision `71e93cb3de00183c263ec440919b313cf92ed8af`; no session used `xhigh`.
The ignored local evidence is in `runs/m2-09/`, with the reproducible JSON and
Markdown reports at `runs/m2-09-report.json` and `runs/m2-09-report.md`.
These three attempts per task are descriptive, not a general reliability estimate.
The public IFEval, LiveBench and AIME instances may be present in model training
data; the two logic grids were generated for this run.

## First L2 report (2026-10-14)

The five-task L2 run completed 30 planned Trials in 15 jobs: Sapiens passed
12/15 and direct Codex passed 13/15. Both used `openai/gpt-6.1-sol`, base
reasoning `medium`, summaries `auto`, web search disabled, the same 1800-second
agent limit and provider allowlist, and Codex CLI 0.162.1. Sapiens used pinned
revision `71e93cb3de00183c263ec440919b313cf92ed8af` and delegated in 0/15
assessed Trials. The report also preserves two earlier cancelled `infra_error`
Trials that started before required checks; they are excluded from pass rates and
the procedural violation is documented in the ignored local evidence at
`runs/m3-07/`. Reproducible reports are `runs/m3-07-report.json` and
`runs/m3-07-report.md`. These three attempts per task are descriptive. The
public Terminal-Bench tasks may be present in model training data, and their
rebased task conditions differ from the published benchmark.

## Navigation

| Document | Owner |
|---|---|
| [SPEC](SPEC.md) | Product requirements, flow, outcomes and trust rules |
| [GLOSSARY](GLOSSARY.md) | Canonical domain terms |
| [ARCHITECTURE](ARCHITECTURE.md) | Current components, interfaces, dependencies and parameter sources |
| [AGENTS](AGENTS.md) | Canonical engineering instructions and task workflow |
| [CLAUDE](CLAUDE.md) | Pointer to AGENTS for Claude Code |
| [Code style](docs/development/code-style.md) | Python conventions and review checklist |
| [Task authoring](docs/agents/task-authoring.md) | Task layout, template and readiness rules |
| [Issue tracker](docs/agents/issue-tracker.md) | Local task workspace conventions |
| [Triage labels](docs/agents/triage-labels.md) | Skill triage roles |
