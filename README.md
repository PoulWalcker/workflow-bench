# Workflow Bench

A small research tool for testing whether AI can explore simulated tools, submit a
reusable native n8n workflow, and solve a business task on fresh inputs. Independent
checks report correctness, score, Verdict, errors and measured costs.
The target MVP uses simulated Telegram API and virtual UI; current capabilities and
milestone status are in [ROADMAP](ROADMAP.md). It does not contact real Telegram.

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

These run without Docker/models/credentials. Results and packaging limitations
are preserved in the [WB-02](docs/implementation/WB-02-bootstrap.md) and
[WB-03](docs/implementation/WB-03-component-boundaries.md) tickets.

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

## Verified Docker controls

Prerequisites: Docker/Compose and prepared immutable images. Recorded host baseline:
OrbStack, Docker 29.4.0, Compose 5.1.2, Harbor 0.24.0, n8n/runner 2.41.5. Image pins
belong to [build.py](environments/build.py). Image preparation needs network with an
empty image/cache and is separate from measured execution. Missing Docker/image is
an error, not a successful skip.

Use **new config/output/build directories for every run**. The paths below are
recorded examples; choose unused names when repeating. Pytest deletes existing
`--basetemp`: use only an owned disposable directory, preserving previous evidence.
Do not rebuild tagged images while controls using them are running.

Manual T1 and native boundary controls ([WB-04](docs/implementation/WB-04-e1-native-replay.md),
[WB-05](docs/implementation/WB-05-e1-trust-and-failures.md)):

```sh
uv run --locked --offline python environments/build.py --simapp simapps/telegram --output runs/wb05-final/config.json
uv run --locked --offline python -m workflow_bench.cli --task tasks/t1-send-message --config runs/wb05-final/config.json --output runs/wb05-final/manual-confirm --case fresh-a --case fresh-b --case missing
uv run --locked --offline pytest -q tests/integration/test_manual.py tests/integration/test_trust.py tests/integration/test_delivery.py --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-native --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_lifecycle.py tests/integration/test_isolation.py --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-lifecycle --log-cli-level=INFO
```

T1 5+5 measurement requires a **pre-frozen private Task copy** with `wb_final_cases`
metadata referencing its private final file; public examples are not holdout. See
[WB-06](docs/implementation/WB-06-t1-measurement.md) for its preparation/evidence.
The confirmed manual measurement used an explicitly adjusted runtime total deadline
of 1800 s; builder's technical E1 default of 360 s failed that full control.
This is not an approved model budget.

```sh
uv run --locked --offline pytest -q tests/integration/test_measurement.py --run-integration --e1-config runs/wb06-images/config.json --measurement-task runs/wb06-private/task --basetemp runs/wb06-measurement-confirm --log-cli-level=INFO
```

Model-free stock Codex wiring uses synthetic credentials/internal provider stub;
[WB-07](docs/implementation/WB-07-codex-e2.md) owns outcomes and paid-run blockers.
The native CLI probe below records HTTP 501/agent failure, missing artifact and
confirmed stop; it does not prove model reasoning. Successful inert submissions
are separate integration controls.

```sh
uv run --locked --offline python environments/build.py --simapp simapps/telegram --output runs/wb07-codex-images/config.json --codex-version 0.118.0
uv run --locked --offline python -m workflow_bench.cli --codex --config runs/wb07-codex-images/codex-config.json --task runs/wb06-task-first-correction/task --output runs/wb07-native-codex-stub-second
uv run --locked --offline pytest -q tests/integration/test_codex.py --run-integration --e1-config runs/wb07-codex-images/config.json --measurement-task runs/wb06-task-first-correction/task --basetemp runs/wb07-a-confirm --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_lifecycle.py tests/integration/test_delivery.py --run-integration --e1-config runs/wb07-codex-images/config.json --basetemp runs/wb07-lifecycle-reviewed --log-cli-level=INFO
```

The MCP packaging regression runs without models or credentials. It checks
initialization and tool discovery with `PYTHONPATH` removed, matching native Codex:

```sh
uv run --locked --offline python environments/build.py --simapp simapps/telegram --output runs/wb07-completion-review/images/config.json --codex-version 0.118.0
uv run --locked --offline pytest -q tests/integration/test_codex.py::test_packaged_mcp_discovery_without_ambient_pythonpath --run-integration --e1-config runs/wb07-completion-review/images/config.json --basetemp runs/wb07-completion-review/green-confirm
```

Use fresh build/output directories when repeating these commands.

The separately authorized live repeat after this fix confirmed three MCP calls,
one submission, 5/5 development and 5/5 final, score 10/pass/complete and native
reward 10.0. The verified command below used the frozen reassessment Task (same
intent/cases/rubric, corrected technical launcher) and explicit native auth. It
requires fresh authorization/finite limits for any future repetition.

```sh
uv run --locked --offline python -m workflow_bench.cli --codex --authorize-model --codex-auth "$HOME/.codex/auth.json" --config runs/wb07-completion-review/next-live-config.json --task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --output runs/wb07-live-mcp-t1-20261012-active
```

CLI stdout points to `report.json`; exit 0 means the report was saved, not that the
business Task passed. Reports/manifests/evidence and native logs stay under ignored
`runs/`. API-billed model mode remains closed without verified provider spending
enforcement. ChatGPT mode uses native Harbor `auth.json` support, live subscription
allowance checks, and Harbor's network allowlist. Composer can read its temporary
credential copy; Replay and the verifier never receive it. This mode requires
`authentication="chatgpt"` in Composer config, finite runtime/tool limits, an
explicit auth file, and `--authorize-model`.

The following WB-07 command created one genuine model submission. Its old frozen
Task launcher referenced an obsolete state-schema path; development was reassessed
from saved Evidence with the current technical launcher. Results and limitations
are in [WB-07](docs/implementation/WB-07-codex-e2.md). Use a new output directory
when reproducing, and a frozen private Task with the current technical launcher.

```sh
codex login status
uv run --locked --offline python -m workflow_bench.cli --codex --authorize-model --codex-auth "$HOME/.codex/auth.json" --config runs/wb07-live-implementation/live-config.json --task runs/wb06-task-first-correction/task --output runs/wb07-live-t1-20261012-active
```

## Navigation

| Document | Owner |
|---|---|
| [SPEC](SPEC.md) | Product requirements, terms, accepted decisions and open approvals |
| [ARCHITECTURE](ARCHITECTURE.md) | Responsibilities, current interfaces, dependencies and trust topology |
| [AGENTS](AGENTS.md) | Engineering rules and task-first development workflow |
| [ROADMAP](ROADMAP.md) | Milestones, dependencies, status and acceptance gates |
| [Implementation tickets](docs/implementation/) | Task-specific design/approvals and historical evidence |

[Public artifact contract](src/workflow_bench/resources/workflow.md),
[T1 public input](tasks/t1-send-message/task.json) and
[Telegram tools](simapps/telegram/tools.json) define the current executable profile.
The historical [WB-01 ticket](docs/implementation/01-project-structure.md) does not
assign current work or override SPEC/ARCHITECTURE.
