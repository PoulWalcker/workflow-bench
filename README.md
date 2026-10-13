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
helper from `src/workflow_bench`; rebuild it after changing that package.

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
passes is rejected; they fail, rather than skip, when Docker or the image is missing.

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
