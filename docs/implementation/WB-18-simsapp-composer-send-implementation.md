# WB-18 — SimsApp composer/send implementation

Статус: **DONE — composer/Send V1; не полный T2**. 12 октября 2026.
Работа основана на `codex/wb17-simsapp-navigation`.

Текущее поручение владельца «Implement WB-18» разрешает composer/Send portion
WB-16 и public UI → observation/FrozenEvidence behavioral controls WB-18.
Private planning tickets остаются неизменными; этот файл отдельно фиксирует
реализацию и результаты. Работа останавливается после WB-18.

## Поведение и файлы

- `simapps/simsapp/app.py`: открытая беседа показывает textbox Message и Send.
  Focus/replace_text сохраняют точную строку, в том числе Unicode code points,
  decomposed Unicode, emoji, whitespace, newline и literal `{{...}}`.
  Draft принадлежит беседе; навигация не очищает его. Одинаковый replacement и
  повторный focus — no-op. Пустой replacement отсутствующего draft не создаёт
  лишнюю запись. Initial composer focus допустим только на conversation screen.
- Send активируется только через fresh locator видимого enabled control.
  Он не требует focus, сохраняет имеющийся focus, атомарно добавляет одно новое
  outgoing message в active conversation и очищает только этот draft, с одной
  revision. Пустота — только empty string. Нет dedup: старое equal-text message
  сохраняется; повторный ввод/Send создаёт второй эффект. Конкурирующие Send с
  одним locator дают один commit и stale rejection.
- `simapps/simsapp/{tools.json,state.schema.json}`: UI profile `simsapp-ui-v1`,
  image prefix `wb-simsapp:wb18`, composer focus и message-sized replacement.
  Search сохраняет меньший query bound из state schema. Full message capacity
  отвергает Send до обеих мутаций. Surrogate/invalid shape/unsupported action,
  wrong focus, stale/hidden/disabled control дают explicit no-effect errors.
- Protected Evidence содержит message ID эффекта и одну transition с append
  message + clear draft. Draft-map deltas копируют значения: поздняя мутация
  состояния не переписывает ранее сохранённые facts. Before/after и текущая
  UI history проходят существующий независимый `read_evidence` ingress.
- `tests/fast/test_simsapp.py`: public UI/FrozenEvidence сценарии composer,
  exact send, bounds, equal text, drafts, duplicate/concurrent sends и invalid
  actions. Старые navigation checks теперь различают history text и composer
  textbox с одинаковым label Message; текущий draft видим только в своей беседе.
- `tests/integration/test_simsapp_navigation.py`: существующие Harbor controls
  переиспользуются для pending Send timeout/cancel. Общие test callers умеют
  выбирать visible controls по role и принимать synthetic initial state.
- `tests/integration/test_simsapp_send.py`: real sandbox UI path для exact Send
  и lost response, direct HTTP/admin bypass, freeze/late denial и MCP inventory.
- `SPEC.md`, `ARCHITECTURE.md`, `README.md`, WB-18 status в `ROADMAP.md`:
  owner facts и проверенные команды. Private planning/design/research не меняются.

## Архитектурное решение текущей работы

Interface остаётся `ui_observe`/`ui_action`; business `send_message` отсутствует
в inventory и запрещён при прямом HTTP. Send implementation находится внутри app,
не получает Task target/expected и не проверяет business correctness за агента.

Расширяется только существующее app-owned состояние/проекция/transition. Simulator
уже сериализует perform и revision под одним lock; Harbor сохраняет reset, scoped
capability, isolation, revoke/drain/freeze, подтверждённый stop и owned cleanup.
Evidence v2 уже поддерживает message ID, list append и draft-map deltas; wire v1,
wire v2, shared ingress и T1 не меняются. Новый app profile/hash отличает расширение
от WB-17 subset. Нет второй БД, journal, lifecycle, runtime или score calculation.

Lost response не откатывает commit и не вызывает автоматический повтор записи.
Real control наблюдает исходную историю со старым equal text и её новое полное
состояние; protected call/effect/response независимо подтверждают ровно один commit.
Unknown transport outcome и известный effect остаются различимыми. Pending Send
при freeze остаётся incomplete/unknown и не может записать позднее. Это controls
среды, не Task Evaluation/terminal claim/полный T2 pass.

## TDD и проверки

Использованы локальные codebase-design, domain-modeling и TDD skills; новые термины,
Seam или ADR не вводились. Behavioral implementation велась вертикально:

1. Composer read/focus/replace/preservation: red из-за отсутствующего textbox → green.
2. Exact Send: red из-за отсутствующего Send и ограничения текста 256 → implementation;
   независимый FrozenEvidence выявил aliasing draft delta → owned snapshots → green.
3. Capacity rejection: red из-за фактического append сверх 100 → atomic no-effect green.
4. Navigation regression выявила потерю прежнего query bound после расширения wrapper;
   bound возвращён для resolved Search control → green.
5. Duplicate, invalid и concurrent actions проверены через тот же public Interface
   и FrozenEvidence; не добавлялся код только ради искусственного red.

Одна ранняя проверка invalid actions ошибочно сравнивала весь UI после разрешённого
Back с открытой беседой. Исправлена независимая expectation: navigation допустима,
messages/conversations/drafts должны сохраниться. Неудачные red результаты не
считаются успешной verification.

Команды запускались с локальными `UV_CACHE_DIR="$PWD/.uv-cache"` и
`UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"` по README. Docker 29.4.0, Harbor 0.24.0;
immutable app IDs и все конечные runtime limits сохранены в config. SimsApp
`max_calls=100`, прочие limits — builder defaults; T1 — неизменённые defaults.

```sh
uv run --locked --offline pytest -q tests/fast/test_simsapp.py
uv run --locked --offline pytest -q
uv run --locked --offline ruff check src tests simapps environments tasks
uv run --locked --offline ruff format --check src tests simapps environments tasks
uv run --locked --offline python environments/build.py --simapp simapps/simsapp --output runs/wb18-acceptance/simsapp/config.json
# max_calls установлен в 100 в единственном runtime config.
uv run --locked --offline pytest -q tests/integration/test_simsapp_navigation.py tests/integration/test_simsapp_send.py --run-integration --e1-config runs/wb18-acceptance/simsapp/config.json --basetemp runs/wb18-acceptance/simsapp-controls --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_simsapp_send.py --run-integration --e1-config runs/wb18-acceptance/simsapp/config.json --basetemp runs/wb18-acceptance/send-confirm --log-cli-level=INFO
uv run --locked --offline python environments/build.py --simapp simapps/telegram --output runs/wb18-acceptance/telegram/config.json
uv run --locked --offline pytest -q tests/integration/test_manual.py tests/integration/test_isolation.py tests/integration/test_t1_evaluation.py tests/integration/test_lifecycle.py -k 'manual or network_files or t1_evaluation or pending_drain or lost_response' --run-integration --e1-config runs/wb18-acceptance/telegram/config.json --basetemp runs/wb18-acceptance/t1-controls --log-cli-level=INFO
```

Подтверждено:

- SimsApp fast: **25 passed, 4.80 s**.
- Default fast suite: **311 passed, 37.06 s**; без network/Docker/models.
- Real SimsApp suite: **10 passed, 231.70 s**. Включает 5 navigation regressions,
  2 pending Send timeout/cancel controls, normal/lost-response Send и MCP inventory.
  Stop/cleanup подтверждены; pending controls дают incomplete freeze намеренно.
- Ruff check: **PASS**; Ruff format check: **52 files already formatted**.
- Image preparation SimsApp и Telegram: **PASS**.

- Финальный Send confirm после дополнительного assertion исходной equal-text
  history: **3 passed, 38.05 s**.
- T1 compatibility: **37 passed, 8 deselected, 2 warnings, 301.09 s**. Включает
  реальный native n8n на fresh-a/fresh-b/missing, separate independent verifier,
  read bounds, network/files/cross-run isolation, cancellation, pending drain,
  lost response и blind retry. Два upstream Harbor Task.checksum DeprecationWarning;
  intentional cancellation control пишет ERROR о завершённом с ошибкой manual run
  и успешно проверяет остановку; это ожидаемый negative control, не скрытый сбой.

Факты сохраняются под ignored `runs/wb18-acceptance/`, без копирования в repository
или новый log tree. `git diff --check` прошёл; scoped diff проверен целиком:
нет dependency/core/T1 изменений, machine paths, secrets, будущих scaffold или
изменений private planning tickets. Блокеров WB-18 нет.

## Пределы и остановка

Проверяется bounded synthetic SimsApp V1 и реальная существующая Harbor topology.
Не доказываются native WhatsApp fidelity, agent reasoning, T2 scoring или SimsApp
native n8n feasibility. WB-19–WB-22, NAV/Static App Model/V2, модели, n8n extensions
не реализуются. E3/release blockers остаются вне WB-18. Commit/push/merge отсутствуют.
