# Workflow Bench

A small research tool for testing AI on business tasks with simulated tools and
independent checks. Product requirements and terms are in [SPEC](SPEC.md); current
capabilities and milestone status are in [ROADMAP](ROADMAP.md).
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
This checkout contains no integration tests.

## Navigation

| Document | Owner |
|---|---|
| [SPEC](SPEC.md) | Product requirements, terms, accepted decisions and open approvals |
| [ARCHITECTURE](ARCHITECTURE.md) | Responsibilities, current interfaces, dependencies and trust topology |
| [AGENTS](AGENTS.md) | Engineering rules and task-first development workflow |
| [ROADMAP](ROADMAP.md) | Milestones, dependencies, status and acceptance gates |
| Implementation tickets (`docs/implementation/` at tag `n8n-replay-final`) | Task-specific design/approvals and historical evidence |

The historical WB-01 ticket (at tag `n8n-replay-final`) does not
assign current work or override SPEC/ARCHITECTURE.
