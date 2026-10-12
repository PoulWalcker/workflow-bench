# WB-17 — SimsApp navigation implementation

Статус: **DONE — navigation V1; не полный T2**.

## Реализация и evidence — 12 октября 2026

Поручение владельца на WB-17 согласовало только navigation portion W1–W3,
ui_control/Evidence v2 и перечисленные здесь public navigation seams. Полные
scope/release amendments, Send, NAV и численная методология остаются отдельными.
SPEC содержит узкое WB-17 исключение; ARCHITECTURE описывает реализованные Interfaces.

- `simapps/simsapp/app.py`, `tools.json`, `state.schema.json`: одно state;
  chat_list/search/conversation; literal case-sensitive substring по имени/hint;
  полная выдача 0/1/N; история только открытой беседы; fresh scope/revision refs;
  activate/focus/replace_text/Clear/Back, no-op и no-effect ошибки.
- `src/workflow_bench/simulator.py`: перенесён существующий сервер capability,
  reset/issue/revoke/drain/freeze/export и трёх стадий journal. Telegram оставляет
  свою бизнес-семантику; SimsApp supplies свою. Нет копии lifecycle или второй БД.
  Typed Application Interface имеет два действительных adapters, без registry/base class.
- Wire v2 — только ui_control/control, protected observation и transition deltas.
  V1 тело сохранено; новые общие поля используют refs к существующим формам.
  FrozenEvidence ingress самостоятельно проверяет chain/refs/revisions/actor;
  incomplete/unknown не становятся fabricated complete.
- Harbor использует прежнюю topology/stop/export, с honest `wb-control-` scope.
  Scripted caller выполняется в существующем изолированном sandbox, без native
  WorkflowArtifact/Replay, online harness или нового orchestrator. Builder копирует
  shared module и использует unique app tags, сохраняя прежние image tags.

Behavioral red → green: сначала полный navigation control; затем fabricated
transition, query limit/no-effect, UI-only bypass, incomplete observation, закрытие
admission по call limit и fabricated complete/unknown response. Уже реализованные
0/1/N, fresh/reset, initial screens/order/drafts и capacity подтверждены отдельными
регрессиями. Проверяющие controls не импортируют renderer/search; читают только
публичный UI и protected FrozenEvidence с независимыми synthetic expectations.

Ранние неудачные реальные controls сохранены под `runs/wb17-navigation/`:
сначала отсутствовала ui_control resource identity, затем startup обнаружил ошибку
имени WB_TOOLS_PORT после переноса. Исправлено; owned cleanup подтверждён. Две
последующие image подготовки обнаружили случайную строку в Dockerfile template;
исправлено до успешных финальных сборок. Эти попытки не считаются PASS.

Финальный SimsApp control config: `runs/wb17-final/simsapp-confirm/config.json`,
max_calls=100; остальные конечные лимиты из builder config, models отсутствуют.
Real suite: **5 passed, 126.44 s** в `runs/wb17-final/simsapp-controls/`:
positive+negative access/freeze, lost response+readback, timeout, cancellation,
fresh world с отказом старой capability/scope. Подтверждены реальный child process,
stop sandbox/runner, cleanup и неизменность frozen facts после возможного late commit.
Timeout/cancel намеренно дают incomplete freeze с pending, а не полный quality pass.
Независимый checker применён к финальному export; source facts хранятся один раз.

```sh
uv run --locked --offline pytest -q tests/fast/test_simsapp.py tests/fast/test_simulator.py
uv run --locked --offline pytest -q tests/integration/test_simsapp_navigation.py --run-integration --e1-config runs/wb17-final/simsapp-confirm/config.json --basetemp runs/wb17-final/simsapp-controls --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_manual.py tests/integration/test_isolation.py tests/integration/test_t1_evaluation.py tests/integration/test_lifecycle.py -k 'manual or network_files or t1_evaluation or pending_drain or lost_response' --run-integration --e1-config runs/wb17-final/telegram-confirm/config.json --basetemp runs/wb17-final/t1-controls --log-cli-level=INFO
```

Команды запускаются с локальными UV_CACHE_DIR/UV_PYTHON_INSTALL_DIR по README.
Docker 29.4.0 / Harbor 0.24.0; реальный HTTP transport, без mocks изоляции/stop.
Local transport substitution используется только в fast tests и не служит proof
изоляции. Никаких credentials/live models, реального Telegram/WhatsApp/desktop,
commits/push/merge или WB-18–WB-22 реализации.


Финальные regression results:

- Default `pytest -q`: **303 passed, 35.86 s**, без Docker/model collection.
- T1 selected integration suite: **37 passed, 8 deselected, 304.71 s**;
  includes реальные manual native n8n + separate verifier на fresh-a/fresh-b/missing,
  100/101 message read bounds, network/files/cross-run isolation, manual cancellation,
  expired/pending drain, lost response без retry/с blind retry; остальные проверки
  independently exercise T1 Evaluation. Два upstream Harbor Task.checksum
  DeprecationWarning, без ошибок. T1 Cases/solution/policy/profile не изменены.
- `ruff check src tests simapps environments tasks`: **PASS**.
- `ruff format --check src tests simapps environments tasks`: **51 files formatted**.
- `git diff --check`: **PASS**; legacy Evidence v1 JSON body сравнен с HEAD и равен.
  Scoped diff проверен: нет новых dependencies, machine paths/credentials в коде,
  будущих scaffold/modules, business ветвлений в core или unrelated code edits.

Файлы данного среза:
`simapps/simsapp/{app.py,tools.json,state.schema.json}`;
`src/workflow_bench/{simulator.py,contracts.py,harbor.py,evaluation.py}`;
`src/workflow_bench/resources/wire.schema.json`;
`simapps/telegram/app.py`; `environments/build.py`;
`tests/fast/test_simsapp.py`; `tests/integration/test_simsapp_navigation.py`;
`SPEC.md`, `ARCHITECTURE.md`, `README.md`, текущие строки `ROADMAP.md`,
`docs/implementation/WB-16-simsapp-t2-contract.md` и данный WB-17 тикет.
Исходные пользовательские ROADMAP/design/research изменения сохранены; будущие
WB-18–WB-22 файлы не редактировались и не реализованы.

Блокеров WB-17 нет. Предел доказательства: только bounded synthetic navigation V1,
HTTP UI transport и существующий Harbor sandbox; это не send/T2 business pass,
не live-app fidelity, не качество агента и не доказательство native UI workflow
совместимости. E3/release и дальнейшие W4–W7 решения остаются отдельными.
Работа остановлена после WB-17; commit/push/merge не выполнялись.

Implementation commit scope: исходные пользовательские design/research и WB-16/17
тикеты не включаются. В ROADMAP включается только отдельная запись результата WB-17;
прочие исходные roadmap правки сохраняются локально.
