# Workflow Bench

A small research tool for testing whether AI can explore simulated tools, submit a
reusable native n8n workflow, and solve a business task on fresh inputs. Independent
checks report correctness, score, Verdict, errors and measured costs.

The current benchmark is T1, an API-only simulated Telegram task. SimsApp provides
a separate virtual UI with navigation, drafts and Send; its full T2 benchmark and
navigation experiments remain planned. See [ROADMAP](docs/ROADMAP.md) for capabilities,
limitations and release gates. Benchmark execution does not contact real Telegram
or control a physical desktop.

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

## Local checks

These commands run without Docker, models or credentials:

```sh
uv run --locked --offline pytest -q
uv run --locked --offline pytest --collect-only -q
uv run --locked --offline ruff check src tests simapps environments tasks
uv run --locked --offline ruff format --check src tests simapps environments tasks
uv build --force-pep517 --offline
```

Default pytest excludes integration/model collection/setup; explicit integration
requires `--run-integration`. `--run-model` remains unimplemented and is rejected.
A Task verifier/Evaluation control needs opt-in but no Docker/config:

```sh
uv run --locked --offline pytest -q tests/fast/test_evaluation.py tests/integration/test_t1_evaluation.py --run-integration
```

## Docker controls

Prerequisites: Docker/Compose and prepared immutable images. Checked host baseline:
OrbStack, Docker 29.4.0, Compose 5.1.2, Harbor 0.24.0, n8n/runner 2.41.5. Image pins
belong to [build.py](environments/build.py). Image preparation needs network with an
empty image/cache and is separate from measured execution. Missing Docker/image is
an error, not a successful skip.

Use **new config/output/build directories for every run**. Paths below are examples;
choose unused names when repeating. Pytest deletes existing `--basetemp`: use only
an owned disposable directory. Do not rebuild tagged images while controls using
them are running. App builds use unique tags and record immutable image IDs.

Manual T1 and native boundary controls:

```sh
uv run --locked --offline python environments/build.py --simapp simapps/telegram --output runs/t1-images/config.json
uv run --locked --offline python -m workflow_bench.cli --task tasks/t1-send-message --config runs/t1-images/config.json --output runs/t1-manual --case fresh-a --case fresh-b --case missing
uv run --locked --offline pytest -q tests/integration/test_manual.py tests/integration/test_trust.py tests/integration/test_delivery.py --run-integration --e1-config runs/t1-images/config.json --basetemp runs/t1-boundary-controls --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_lifecycle.py tests/integration/test_isolation.py --run-integration --e1-config runs/t1-images/config.json --basetemp runs/t1-lifecycle-controls --log-cli-level=INFO
```

T1 5+5 measurement requires a **pre-frozen private Task copy** with `wb_final_cases`
metadata referencing its private final file. Prepare it according to
[SPEC's T1 policy](docs/SPEC.md#accepted-t1-measurement) and the
[Task layout](docs/ARCHITECTURE.md#2-task-materials-and-data-boundaries); public examples
are not holdout. The paths below assume that copy is at `runs/private-t1/task`.
A full manual measurement previously required `total_timeout_sec=1800` in the
runtime config; the builder's technical E1 default of 360 s was insufficient.
This is not an approved model budget.

```sh
uv run --locked --offline pytest -q tests/integration/test_measurement.py --run-integration --e1-config runs/t1-images/config.json --measurement-task runs/private-t1/task --basetemp runs/t1-measurement-controls --log-cli-level=INFO
```

## Composer integrations

Stock Codex and Sapiens share Harbor, native n8n execution and the T1 evaluator.
Model-free controls use synthetic credentials and an isolated provider stub; they
prove wiring and lifecycle behavior, not model reasoning. These examples require
the private Task copy described above:

```sh
uv run --locked --offline python environments/build.py --simapp simapps/telegram --output runs/codex-images/config.json --codex-version 0.118.0
uv run --locked --offline pytest -q tests/integration/test_codex.py --run-integration --e1-config runs/codex-images/config.json --measurement-task runs/private-t1/task --basetemp runs/codex-controls --log-cli-level=INFO
```

The Codex controls include MCP discovery with `PYTHONPATH` removed, matching the
native CLI environment. A stub returning HTTP 501 must yield agent failure, missing
artifact and confirmed stop; successful inert submissions are separate controls.

For Sapiens, provide a local checkout at revision
`71e93cb3de00183c263ec440919b313cf92ed8af` using `--source`. Only committed public
runtime files enter the image; no desktop submodules or Sapiens modifications are
required. Set `SAPIENS_SOURCE` to that checkout's path before running:

```sh
uv run --locked --offline python environments/build_sapiens.py --source "${SAPIENS_SOURCE:?Set SAPIENS_SOURCE to the pinned checkout}" --codex-config runs/codex-images/codex-config.json --output runs/sapiens-images/config.json
uv run --locked --offline pytest -q tests/integration/test_sapiens.py --run-integration --e1-config runs/codex-images/config.json --sapiens-config runs/sapiens-images/config.json --measurement-task runs/private-t1/task --basetemp runs/sapiens-controls --log-cli-level=INFO
```

Sapiens controls cover MCP discovery, synthetic workflow submission, timeout,
cancellation, host disconnection and Codex failure. Each Sapiens build retains a
unique image tag and records its immutable image ID. Stale configs referencing
removed images require fresh preparation.

Live experiments require a separately prepared Composer config, explicit model
authorization and finite limits. ChatGPT mode uses `authentication="chatgpt"`,
Harbor's native single-file auth injection, live subscription allowance checks and
a network allowlist. Supply the auth file with `--codex-auth` and authorization with
`--authorize-model`, selecting `--codex` or `--sapiens`. Composer can read its temporary
credential copy; Replay and the verifier never receive it. Prepared configuration
alone is not permission or verified authentication. API-billed mode remains closed
without verified external spending enforcement. See
[configuration sources](docs/ARCHITECTURE.md#6-experimentconfiguration-interfaces) and
[SPEC's lifecycle rules](docs/SPEC.md#9-errors-and-lifecycle).

CLI stdout points to `report.json`; exit 0 means the report was saved, not that the
business Task passed. Reports, manifests, evidence and native logs stay under
ignored `runs/`. Model outcomes and current limitations are summarized in
[ROADMAP](docs/ROADMAP.md).

## SimsApp UI controls

SimsApp exposes `ui_observe` and `ui_action`: navigation, focus, exact draft
replacement and activation of the supported Send control. Drafts persist per
conversation; Send atomically appends one outgoing and clears only the sent draft.
It never exposes a business `send_message` tool. The UI projection uses the
[sanitized WhatsApp AX fixture package](simapps/simsapp/fixtures/README.md), with
explicit reconstruction and fidelity limits; this is a simulator, not native
WhatsApp compatibility.

The required sanitized AX assets remain private local input; provision the existing
fixture package before building SimsApp. No synthetic fallback or fixture
regeneration occurs. Observations expose native AX roles, scoped `ref` and
`simulation` annotations for supported actions, identity hints and exact draft
values. Search is AXStaticText/AXSearchField, composer is AXTextArea and Send is an
annotated AXMenuItem. See [projection contracts and fidelity limits](docs/ARCHITECTURE.md#5-evidence-and-evaluation-interfaces).

Local fidelity and behavior checks need neither original research nor Docker:

```sh
uv run --locked --offline python simapps/simsapp/fixtures/check.py
uv run --locked --offline pytest -q tests/fast/test_simsapp.py tests/fast/test_simsapp_ax.py tests/fast/test_simsapp_fixtures.py
```

Set `max_calls=100` in the prepared runtime JSON before running these controls;
the builder's T1 default of 8 is insufficient for their UI sequences. All other
runtime limits retain the builder defaults. Use fresh directories each time:

```sh
uv run --locked --offline python environments/build.py --simapp simapps/simsapp --output runs/simsapp-images/config.json
# Set max_calls to 100 in the prepared config.json.
uv run --locked --offline pytest -q tests/integration/test_simsapp_navigation.py tests/integration/test_simsapp_send.py --run-integration --e1-config runs/simsapp-images/config.json --basetemp runs/simsapp-controls --log-cli-level=INFO
```

These controls use Harbor isolation/transport/stop and protected Evidence with a
`ui_control` identity. They do not submit a workflow or run a model. Independent
checks read `FrozenEvidence`; lost Send responses preserve exactly one commit,
timeout/cancel stop actual children, and pending facts remain incomplete. MCP
discovery is checked in a separate isolated model-free container. Full T2
Cases/verifier, NAV experiments and native UI/n8n compatibility remain planned.

## Navigation

| Document | Owner |
|---|---|
| [SPEC](docs/SPEC.md) | Product requirements, terms, accepted decisions and open approvals |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Responsibilities, current interfaces, dependencies and trust topology |
| [AGENTS](AGENTS.md) | Engineering rules and task-first development workflow |
| [ROADMAP](docs/ROADMAP.md) | Capabilities, planned work, dependencies and acceptance gates |

[Public artifact contract](src/workflow_bench/resources/workflow.md),
[T1 public input](tasks/t1-send-message/task.json) and
[Telegram tools](simapps/telegram/tools.json) define the current executable benchmark
profile. [SimsApp tools](simapps/simsapp/tools.json) define the separate UI profile.
