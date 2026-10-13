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
This checkout contains no integration tests.

## Navigation

| Document | Owner |
|---|---|
| [SPEC](SPEC.md) | Product requirements, flow, outcomes and trust rules |
| [GLOSSARY](GLOSSARY.md) | Canonical domain terms |
| [ARCHITECTURE](ARCHITECTURE.md) | Current components, interfaces, dependencies and parameter sources |
| [AGENTS](AGENTS.md) | Canonical engineering instructions and task workflow |
| [CLAUDE](CLAUDE.md) | Pointer to AGENTS for Claude Code |
| [Code style](docs/development/code-style.md) | Python conventions and review checklist |
| [Issue tracker](docs/agents/issue-tracker.md) | Local task workspace conventions |
| [Triage labels](docs/agents/triage-labels.md) | Skill triage roles |
