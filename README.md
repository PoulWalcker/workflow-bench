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
using them. Building needs Docker and network access; the installed Codex CLI starts
without network. Pins and the tag are listed in
[ARCHITECTURE](ARCHITECTURE.md#parameter-sources). Checked with Docker 29.4.0 on
macOS arm64.

```sh
docker compose -f environments/agents/compose.yaml build --pull
docker run --rm --network none workflow-bench-agents:codex-0.162.1 codex --version
```

The second command prints `codex-cli 0.162.1`. The image also carries the evaluation
helper from `src/workflow_bench`, with dependencies at their `uv.lock` versions; rebuild
it after changing that package or the lock. `wb check-task` reports
`stale:agents_helper` and the integration preflight fails when the image's helper
differs from the checkout.

## Task readiness

Tasks follow the [task authoring regulation](docs/agents/task-authoring.md). Checking one
needs Docker and the `agents` image, but no model or credentials; the native Harbor
jobs of the controls stay under `--jobs-dir`.

```sh
uv run --locked wb check-task tasks/l1-basket-total --jobs-dir runs/readiness
uv run --locked pytest -q --run-integration tests/integration
```

The first command prints a JSON report with `"ready": true` and exits 0 (about 75 seconds
on the baseline host). The integration controls also check that a task whose no-op run
passes is rejected; they fail, rather than skip, when Docker or the image is missing
or its helper is stale.

## Direct Codex controls

[The native job example](examples/codex/job.yaml) runs the trivial task using
`SessionSafeCodex` and `DeadlineDockerEnvironment`, with one attempt and no retry.
It explicitly disables ambient authentication and points Codex at an unused
loopback port inside the container. These commands use Docker, with no credentials
or model calls:

```sh
uv run --locked harbor run -c examples/codex/job.yaml
uv run --locked wb compare runs/codex/codex-empty-provider
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
(Codex TOML mapping); MCP servers belong to the task. The example deliberately has
no live credentials. An authorized subscription job must replace its empty-provider
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

## Report

Reporting reads saved Harbor job directories offline and needs no Docker, model or
credentials. Each argument is one job directory, `<jobs-dir>/<job-name>`.

```sh
uv run --locked wb compare runs/readiness/check-*
uv run --locked wb compare --format markdown runs/readiness/check-*
```

The first command prints a JSON report and exits 0: one outcome per Trial and, per
task and configuration, counts, pass rate and medians. With the readiness controls
above it shows `oracle` with pass rate 1.0 and `nop` with 0.0. A directory that is not
a Harbor job exits 2.

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
