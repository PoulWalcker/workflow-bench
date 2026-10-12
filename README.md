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

## WB-08 Sapiens spike

The model-free Sapiens host/CLI path reuses Harbor and the existing T1 evaluation.
[WB-08](docs/implementation/WB-08-sapiens-spike.md) records the upstream pin,
license, demonstrated capabilities and limits. Genuine generation remains a
separate authorized model step. No desktop submodules or Sapiens modifications.

The recorded image preparation used the fetched checkout at
`/private/tmp/wb08-sapiens-source`, revision
`71e93cb3de00183c263ec440919b313cf92ed8af`. Supply your own checkout of that exact
revision with `--source`; only committed public runtime files enter the image.
Use a fresh output directory. Each build retains a unique image tag and records
its immutable image ID in the output config. The prepared Codex config supplies the immutable
base image, Codex version and common runtime configuration.

```sh
uv run --locked --offline python environments/build_sapiens.py --source /private/tmp/wb08-sapiens-source --codex-config runs/wb07-completion-review/images/codex-config.json --output runs/wb08-unique-builder/config.json
uv run --locked --offline pytest -q tests/integration/test_sapiens.py -k 'stops_host or stock_codex_failure' --run-integration --e1-config runs/wb07-completion-review/images/config.json --sapiens-config runs/wb08-unique-builder/config.json --basetemp runs/wb08-final-stop-controls --log-cli-level=INFO
```

The test control temporarily substitutes an inert external Codex process. A real
Codex app-server checks actual MCP discovery without a model turn, and the real MCP
transport calls the simulator. Its submitted workflow is synthetic: 5+5 control
success proves wiring/Evaluation, not Sapiens generation. Separate controls cover
timeout, external cancellation, native CLI cancellation, host disconnection and
real Codex failure against the isolated local provider stub. Test images are removed;
run evidence and the production image are retained.

The full 5+5 repeat in `runs/wb08-final-controls` passed before a concurrent image
retagging mistake broke the remaining setups. The builder now uses unique tags;
all five affected checks passed with its retained image. Historical configs referencing
the deleted image index require fresh image preparation before repetition. The ticket
preserves the historical commands and the successful 5+5 report.

The earlier production entry point was also exercised model-free. The local HTTP stub returns
501 rather than a model response; expected results are a terminal failure, missing
artifact, null score and confirmed stop/cleanup:

```sh
uv run --locked --offline python -m workflow_bench.cli --sapiens --config runs/wb08-sapiens-images/config.json --task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --output runs/wb08-native-stock-model-free
```

For a live experiment, `--sapiens` uses the same `--authorize-model` and explicit
`--codex-auth` requirements as stock Codex, with finite configuration and live
subscription allowance checks. Do not reuse prior authorization. Prepared live
configuration alone is not permission, verified authentication or a model result.

The separately authorized WB-08 live run used the unchanged frozen T1 and
`gpt-6.1-sol` / low. Its first Attempt made two actual MCP calls but hit the
240-second submission timeout without a workflow. Harbor confirmed stop/cleanup;
the unknown result blocked a second Attempt. E3 is not complete. See the ticket
for the live report and native-session retention fix (five real Docker controls passed).

The separately authorized 600-second repeat completed native CLI submission in
455 seconds, collected a genuine valid workflow and retained three internal Codex
sessions. It made four admitted MCP calls. All five development cases then failed
with n8n `ExpressionExtensionError: invalid syntax` in `jsonBody`, before replay
tool calls. The unavailable/partial evaluation blocked a second Attempt/private final;
score remains null. Live artifact generation is demonstrated; successful T1 E3 is
still unconfirmed. No further model run or candidate repair was performed.

```sh
uv run --locked --offline python -m workflow_bench.cli --sapiens --authorize-model --codex-auth "$HOME/.codex/auth.json" --config runs/wb08-prepared-live-600/config.json --task runs/wb07-live-t1-20261012-active/verifier-reassessment/task --output runs/wb08-live-t1-600-20261012
```

## WB-17 SimsApp navigation controls

SimsApp V1 exposes only `ui_observe` and `ui_action` navigation. It preserves drafts
and messages; composer/Send and a complete T2 benchmark belong to later tickets.
[WB-17](docs/implementation/WB-17-simsapp-navigation-implementation.md) records model-free acceptance.
The app builder now assigns unique tags and records the immutable image ID, so a
new preparation does not retag a previous control's app image.

The confirmed control used `max_calls=100` in the prepared runtime JSON; the
builder's T1 default of 8 is insufficient for this navigation/control sequence.
Set that field in the single runtime config before running. All other runtime
limits retain the builder defaults. Use fresh config/output directories each time:

```sh
uv run --locked --offline python environments/build.py --simapp simapps/simsapp --output runs/wb17-final/simsapp-confirm/config.json
# Set max_calls to 100 in the prepared config.json.
uv run --locked --offline pytest -q tests/integration/test_simsapp_navigation.py --run-integration --e1-config runs/wb17-final/simsapp-confirm/config.json --basetemp runs/wb17-final/simsapp-controls --log-cli-level=INFO
```

These controls use existing Harbor isolation/transport/stop and protected Evidence
with an honest `ui_control` identity. They do not submit a workflow or run a model.
The independent checks read `FrozenEvidence`; timeout/cancel stop actual children,
and pending facts remain incomplete. T1 real regression commands and results are
recorded in WB-17. Native UI/n8n compatibility remains WB-22 work.

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
