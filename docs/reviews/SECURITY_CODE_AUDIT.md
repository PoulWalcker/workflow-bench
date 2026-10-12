# Аудит безопасности и качества кода

Дата: 12 октября 2026. Snapshot: `57f7b3c` (`main`), рабочее дерево без
незакоммиченных правок кода. Роль: архитектор + разработчик. Изменения в коде
не вносились — только этот документ.

## Область и метод

Полностью прочитаны: `src/workflow_bench/*.py` (cli, contracts, data,
definition, evaluation, execution, experiment, harbor), `simapps/telegram/app.py`,
`environments/build.py`, `tasks/t1-send-message/{task.toml,tests/*,solution/*}`,
схемы `workflow.schema.json`, `metadata.schema.json`, `wire.schema.json#/$defs/evidence`,
корневой и fast `conftest.py`. Документация — выборочно (README, оглавление
ARCHITECTURE, `docs/reviews/COMPLEXITY_REVIEW.md`).

Фактически запущено:

| Команда | Результат |
|---|---|
| `uv run --offline ruff check .` | All checks passed |
| `uv run --offline ruff format --check .` | 50 files already formatted |
| `uv run --offline pytest -q tests/fast` | 253 passed, 23 s |

Не запускалось: integration-тесты (`--run-integration`), Docker, n8n, сборка
образа. Ни одна находка не воспроизведена в живом окружении; уровень уверенности
указан у каждой.

Модель угроз, из которой исходит аудит (по SPEC/AGENTS): **workflow кандидата —
недоверенный ввод**, Task и его автор — доверенные, хост и Docker — доверенные.
Главные активы: приватные кейсы/rubric, ключи control/capability, честность
вердикта и score.

### Шкала критичности

| Уровень | Смысл |
|---|---|
| **Critical** | Утечка приватных данных кандидату, выход из песочницы, подделка score. Чинить немедленно. |
| **High** | Кандидат может повлиять на исход измерения или сорвать его; серьёзный архитектурный дефект. Чинить до WB-07. |
| **Medium** | Реальный риск надёжности/безопасности при определённых условиях, заметный долг поддержки. |
| **Low** | Латентный дефект, smell, гигиена; чинить попутно. |
| **Info** | Наблюдение, без обязательного действия. |

Уверенность: **подтверждено** (следует из кода однозначно), **правдоподобно**
(механизм виден, масштаб/достижимость не проверены), **суждение** (дизайн).

## Сводка

Critical-находок нет. Граница доверия спроектирована тщательно: строгий JSON
(дубликаты ключей, NaN/Infinity), только локальные `$ref`, `O_NOFOLLOW` + `st_nlink`
при приёме артефакта, allowlist типов узлов n8n, отдельный verifier-контейнер,
повторный пересчёт aggregate и reward на хосте, internal-сети для replay,
проверка изоляции перед загрузкой недоверенного JSON, digest-пиннинг образов и
`--require-hashes`.

Основные риски находятся в двух местах: **симулятор** (журнал без лимита и
глобальный lock на сетевом I/O) и **разбор вывода n8n** (claim берётся из
смешанного stdout+stderr). Архитектурный долг — большие оркестрирующие функции
с нетипизированными dict-отчётами, связность с приватными API Harbor и pytest,
неоднородная модель ошибок.

| ID | Уровень | Уверенность | Кратко |
|---|---|---|---|
| [SEC-1](#sec-1) | High | подтверждено / масштаб правдоподобен | Неограниченный журнал событий симулятора: кандидат превращает fail в «unavailable» |
| [SEC-2](#sec-2) | Medium | правдоподобно | Claim и `process_status` разбираются из вывода, на который влияет кандидат |
| [SEC-3](#sec-3) | Medium | подтверждено | Глобальный `asyncio.Lock` держится во время чтения тела и записи ответа |
| [SEC-4](#sec-4) | Medium | суждение | Приватные материалы и публичный пакет лежат в одном `output_root` |
| [SEC-5](#sec-5) | Medium | подтверждено | Пробелы hardening контейнеров (root, pids, tmpfs, debug-логи) |
| [SEC-6](#sec-6) | Low | подтверждено | TOCTOU и лексическая (не inode) защита приватных путей |
| [SEC-7](#sec-7) | Low | подтверждено | Передача workflow и capability через argv `sh -c` |
| [SEC-8](#sec-8) | Low | подтверждено | Секреты в env и compose-файле; fault-injection в боевом симуляторе |
| [ARC-1](#arc-1) | High | суждение | God-функции оркестрации и нетипизированные dict-отчёты без контракта |
| [ARC-2](#arc-2) | Medium | подтверждено | Переопределение приватных методов Harbor и внутренностей pytest |
| [ARC-3](#arc-3) | Medium | подтверждено | Неоднородная модель ошибок; CLI теряет диагностику |
| [ARC-4](#arc-4) | Medium | подтверждено | Проглатывание `CancelledError` без `uncancel()`; дубли watcher |
| [ARC-5](#arc-5) | Low | подтверждено | Симулятор и образ скрыто зависят от пакета хоста |
| [BUG-1](#bug-1) | Low | подтверждено | Латентные `UnboundLocalError` в `harbor.py` и `experiment.py` |
| [BUG-2](#bug-2) | Low | подтверждено | Исключения в `finally` маскируют исходную ошибку replay |
| [SML-1](#sml-1) | Low | подтверждено | Валидатор схемы пересобирается на каждый вызов; квадратичный парсер вывода |
| [SML-2](#sml-2) | Low | подтверждено | Магические индексы, legacy-имена `wb04`, хардкод таймаутов |
| [SML-3](#sml-3) | Low | подтверждено | Доменная логика и дубли в `cli.py`; preflight из CLI всегда отклоняется |
| [SML-4](#sml-4) | Low | подтверждено | Отчёт утверждает факты литералами; мёртвое поле `violations` |
| [SML-5](#sml-5) | Low | подтверждено | Кодировка файлов не указана явно |
| [TST-1](#tst-1) | Medium | подтверждено | Нет adversarial-тестов для симулятора и разбора вывода n8n |
| [REP-1](#rep-1) | Medium | подтверждено | `workflow-bench.zip` добавлен в индекс git |
| [REP-2](#rep-2) | Low | подтверждено | README как журнал изменений с противоречивыми числами |

Связь с [COMPLEXITY_REVIEW.md](COMPLEXITY_REVIEW.md): находки S1 (staged replacement
следует по symlink), S2 (нет progress-логов), S3 (дубли cancellation), позиционные
`private_paths` и собственный экспорт lock-файла там уже описаны; здесь они
упоминаются только как контекст и не дублируются.

---

## Безопасность и граница доверия

### SEC-1

**High — неограниченный журнал событий симулятора позволяет кандидату сорвать оценку.**
Уверенность: механизм подтверждён чтением; объём, достижимый за `execute_timeout_sec`,
не измерялся.

Где: [app.py](../../simapps/telegram/app.py):223–270, 281–360;
[wire.schema.json](../../src/workflow_bench/resources/wire.schema.json) `$defs.evidence.events`
(нет `maxItems`); [harbor.py](../../src/workflow_bench/harbor.py):442–448.

Проблема. Каждый запрос к `/tools/{name}` — в том числе без capability (`forbidden`)
или после исчерпания `max_calls` (`limit_exceeded`) — добавляет в `self.events`
три события. Счётчик `self.calls` растёт только для допущенных вызовов, поэтому
отклонённые запросы ничем не ограничены. `operation` берётся из URL без проверки
по списку инструментов. Журнал хранится в памяти и целиком попадает в evidence.

Сценарий. Workflow из Code-узла (генерирует N items) и HTTP Request-узла
(запрос на каждый item) отправляет десятки тысяч запросов за 45 s. Evidence
превышает `MAX_EVIDENCE_BYTES` (32 MiB) → `control_too_large` → кейс без evidence
→ отчёт `unavailable`/`invalid` вместо определённого `fail`. Другой исход — OOM
симулятора при `memory_mb=1024`. Кандидат, который заведомо проваливается,
получает «инфраструктурную ошибку»: score `None`, повод для перезапуска, искажённая
статистика.

Рекомендация.
1. Ввести жёсткий лимит всех входящих запросов (например, `max_requests = 4 × max_calls`).
   Превышение — не новые события, а один счётчик и одно нарушение
   `request_flood` в `violations`, которое verifier трактует как определённый fail
   (critical code), а не как unknown.
2. Отклонять неизвестные `operation` до записи события (`404` без журнала или с
   агрегированным счётчиком).
3. Добавить `maxItems` для `events` в `wire.schema.json`, согласованный с лимитом.
4. Регрессионный тест: 1000 запросов без capability → размер evidence ограничен,
   вердикт `fail`, а не `unknown`.

### SEC-2

**Medium — claim и `process_status` берутся из вывода, на который влияет кандидат.**
Уверенность: правдоподобно; зависит от того, попадает ли `console.log` Code-узла
или иной управляемый текст в вывод `n8n execute` при external runners.

Где: [execution.py](../../src/workflow_bench/execution.py):186–202, 249–291.

Проблема. Команда собирает `stdout` и `stderr` вместе (`2>&1`), а `_cli_data`
выбирает **последний** JSON-объект, начинающийся с новой строки и содержащий
`"mode": "cli"`. Если кандидат может напечатать строку вида
`{"mode":"cli","data":{"status":"success","resultData":{"lastNodeExecuted":"BenchResult",...}}}`,
он подменит `process_status=completed` и `claim`. Критерий `refusal` в
[verify.py](../../tasks/t1-send-message/tests/verify.py):89–99 частично опирается на claim
(вторая половина требует настоящего события `not_found`, это ограничивает ущерб).

Рекомендация.
- Не смешивать потоки: stdout и stderr в разные файлы, парсить только stdout.
- Брать результат из источника, который кандидат не контролирует: n8n
  `--output=<file>` или чтение execution из БД n8n после завершения, а не
  эвристический поиск по тексту.
- Если парсинг остаётся — требовать ровно один кандидат-объект; при нескольких
  считать claim `unknown`.
- Тест: вывод с поддельным JSON перед/после настоящего → claim не принят.

### SEC-3

**Medium — глобальный lock симулятора держится во время сетевого I/O.**
Уверенность: подтверждено.

Где: [app.py](../../simapps/telegram/app.py):225–245 (`await request.read()` под lock),
281–360 (`response.prepare/write_eof` под lock), 152–157 (freeze ждёт lock).

Проблема. Медленный клиент (медленное тело или медленное чтение ответа)
сериализует все остальные вызовы и задерживает `freeze` на `call_timeout` за
каждый такой запрос. Это slowloris-паттерн внутри одного replay: время дренажа
и итоговая полнота evidence зависят от поведения кандидата.

Рекомендация. Читать и валидировать тело **до** захвата lock; под lock держать
только изменение состояния и запись событий; отправлять ответ после выхода из
lock, записывая событие `response` отдельным коротким захватом. Таймаут чтения
тела сохранить.

### SEC-4

**Medium — приватные и публичные материалы в одном корне запуска.**
Уверенность: суждение (архитектурный риск для WB-07).

Где: [experiment.py](../../src/workflow_bench/experiment.py):123–149 —
`output_root/native-task/` (полная копия Task с `tests/cases.json`, `rubric.json`,
`bench-input/*/case.json` с `expected`) и `output_root/public/` (пакет для Composer).

Проблема. Сейчас Composer не запускается, но при подключении WB-07 любой mount
`output_root` или его родителя ради доступа к `public/` раскроет эталоны. AGENTS.md
прямо требует, чтобы ограничения обеспечивались средой, а не соглашением о путях.

Рекомендация. Разделить корни: `runs/<id>/private/` (0700, только хост и verifier) и
`runs/<id>/public/` (то, что может монтироваться). Экспортировать публичный пакет в
отдельный каталог вне дерева с приватными данными и проверять это тестом
(«ни один файл из `private_paths` не достижим из корня public-mount»).

### SEC-5

**Medium — пробелы hardening контейнеров.** Уверенность: подтверждено.

Где: [harbor.py](../../src/workflow_bench/harbor.py):540–615;
[build.py](../../environments/build.py):56–64.

- Образ `wb-telegram` без `USER`: симулятор (`main`) работает от root
  (смягчено `cap_drop: ALL`, `no-new-privileges`, `read_only`).
- Нет `pids_limit` и `ulimits` у n8n/runner, где исполняется код кандидата.
- `tmpfs: ["/tmp"]` без `size` — запись в tmpfs расходует память контейнера; volume
  `database` без квоты.
- `N8N_RUNNERS_LAUNCHER_LOG_LEVEL=debug` у runner — лишний объём логов, возможное
  попадание токенов.
- `N8N_SSRF_PROTECTION_ENABLED=false` осознанно (симулятор в internal-сети), но
  решение не задокументировано рядом с кодом.

Рекомендация. `USER 65534` в Dockerfile (или `user:` в compose для `main`);
`pids_limit: 256`; `tmpfs: ["/tmp:size=64m"]`; уровень логов runner `info`;
однострочный комментарий о причине отключения SSRF-защиты.

### SEC-6

**Low — TOCTOU и лексическая защита приватных путей.** Уверенность: подтверждено.

Где: [data.py](../../src/workflow_bench/data.py):122–130;
[definition.py](../../src/workflow_bench/definition.py):96–173.

- `read_bytes` и `_regular_file` проверяют `is_symlink()`/`stat()`, затем открывают
  файл по пути — окно подмены. `accept_artifact` уже делает правильно (`O_NOFOLLOW`
  + `fstat` открытого дескриптора) — подход не переиспользован.
- `_public_reference` сравнивает пути лексически и с учётом регистра. На
  регистронезависимой APFS (macOS по умолчанию) `wb_public = "Tests/x.json"` проходит
  проверку `reserved`. Hardlink на приватный файл не обнаруживается (нет проверки
  `st_nlink`, как в `accept_artifact`). Ущерб ограничен: файл должен пройти схему
  `task.schema.json`, автор Task доверенный — это защита от ошибок, а не от атаки.
- Список `reserved` содержит имена документов репозитория (`SPEC.md`, `ROADMAP.md`, …) —
  продуктовый код знает о служебной документации.
- `_regular_file` проверяет все родительские каталоги на symlink. На macOS `/tmp`
  и `/var` — symlink, поэтому неразрешённые пути вида `/tmp/task` отклоняются
  (CLI делает `.resolve()`, прямые вызовы библиотеки — нет).

Рекомендация. Один хелпер `open_regular(path) -> bytes` на `os.open(..., O_NOFOLLOW)`
+ `fstat` + `st_nlink == 1` + лимит размера для всех доверенных чтений. Приватность
определять по `(st_dev, st_ino)` или `os.path.samefile` плюс сравнение `casefold()`.
Список имён документации из `reserved` убрать — достаточно allowlist публичных
файлов.

### SEC-7

**Low — workflow и capability передаются через argv.** Уверенность: подтверждено.

Где: [execution.py](../../src/workflow_bench/execution.py):229, 242–246.

Связанный workflow (с capability) кодируется в base64 и подставляется в строку
`sh -c`. Пока артефакт ≤ 64 KiB (`x-max-bytes`), строка ≈ 90 KiB — ниже
`MAX_ARG_STRLEN` Linux (128 KiB). Однако `bind_workflow` допускает до
`MAX_JSON_BYTES` (4 MiB): крупный `case.input` даст `E2BIG` и статус `unknown`
вместо понятной ошибки. Capability также видна в списке процессов хоста
(`docker compose exec …`) на время команды.

Рекомендация. `service_exec` в Harbor 0.24 не принимает stdin, поэтому минимальное
исправление — ограничить bound-файл лимитом канала (≈64 KiB до кодирования) и
выдавать явный `bound_too_large`. Если понадобятся большие входы — передавать
порциями (`printf %s '<chunk>' >> /tmp/workflow.b64`, каждая < 64 KiB) или
добавить поддержку stdin для `service_exec` upstream.

### SEC-8

**Low — секреты в env/compose; fault-injection в боевом коде.** Уверенность: подтверждено.

Где: [harbor.py](../../src/workflow_bench/harbor.py):539, 554–576, 616–618;
[app.py](../../simapps/telegram/app.py):129–142.

- `WB_CONTROL_KEY` и `N8N_RUNNERS_AUTH_TOKEN` видны через `docker inspect` любому
  пользователю группы docker. Для локального MVP приемлемо — зафиксировать как
  принятый риск.
- `docker-compose.yaml` создаётся с umask по умолчанию и только потом получает
  `chmod 0600` — окно, когда файл с ключами читаем.
- Операция `fault` (`drop_response`, `stall_before_commit` до 3600 s) доступна
  в продуктивном симуляторе любому держателю control-ключа.

Рекомендация. Создавать файл сразу с `0600` (`os.open(..., O_CREAT|O_EXCL, 0o600)`);
включать `fault` только флагом окружения тестового режима; передать ключи через
Docker secrets/файл в tmpfs, если модель угроз расширится на многопользовательский хост.

---

## Архитектура и дизайн

### ARC-1

**High — god-функции оркестрации и нетипизированные dict-отчёты.**
Уверенность: суждение.

Где: [experiment.py](../../src/workflow_bench/experiment.py) `_run_manual` (≈220 строк,
вложенная `prepared` с `nonlocal`), `_run_measurement` (≈170 строк);
[harbor.py](../../src/workflow_bench/harbor.py) `run_native_trial` (≈150 строк, три
вложенных hook-замыкания), `check_isolation`.

Проблема. Одна функция копирует Task, переписывает пути, экспортирует пакет,
пишет manifest, создаёт входы verifier, управляет replay, собирает метрики и
формирует отчёт. `report.json`, `manifest.json`, `selection.json`, `execution.json`
собираются как `dict` литералами со строковыми ключами и **не валидируются** ни
одной схемой (в отличие от evaluation/evidence). Ключи вроде `"completeness"`
вычисляются в двух местах разной логикой (`run_manual` — строки 283–295,
`aggregate_evaluation` — evaluation.py:203–213). Опечатка в ключе не будет поймана
ни ruff, ни тестами, а потребители отчёта (будущий WB-07, дашборды) зависят от его
формы.

Рекомендация (без нового фреймворка).
- Выделить из `_run_manual` три шага с явными входами/выходами: `stage_task(...)`,
  `prepare_case(...)`/`replay_case(...)` и `build_report(...)`.
- Ввести `@dataclass(frozen=True)` для `RunReport`, `ReplayRecord`, `Manifest`
  с методом `to_json()`; добавить их в `wire.schema.json` и валидировать перед
  записью тем же `validate_contract`.
- Одно место для правила completeness.

### ARC-2

**Medium — связность с приватными API Harbor и pytest.** Уверенность: подтверждено.

Где: [harbor.py](../../src/workflow_bench/harbor.py):52–71 переопределяет
`DockerEnvironment._collect_buffered_output` (приватный метод);
[tests/conftest.py](../../tests/conftest.py):27–38, 88 подменяет
`pytest.FixtureDef.execute` и читает `request._pyfuncitem`.

Проблема. Работа зависит от внутренней сигнатуры зависимостей. Harbor
запиннен (`harbor==0.24.0`), но pytest — `>=9.1.1`: любое минорное обновление
может молча сломать гейт integration/model-тестов (тесты начнут выполняться без
`--run-integration` или упадут при сборе). README сам признаёт эту зависимость.

Рекомендация. Для pytest — заменить гейт на штатные механизмы:
`pytest_ignore_collect` + маркеры + `pytest_collection_modifyitems` уже покрывают
сбор; запрет запроса integration-фикстур из fast-тестов проще обеспечить тем,
что эти фикстуры живут только в `tests/integration/conftest.py` (pytest не даст их
запросить вне каталога). Для Harbor — отправить upstream issue/PR о гарантированном
kill процесса по таймауту; до тех пор держать contract-тест, проверяющий сигнатуру
переопределяемого метода, и не ослаблять пин версии.

### ARC-3

**Medium — неоднородная модель ошибок; CLI теряет диагностику.**
Уверенность: подтверждено.

Где: [definition.py](../../src/workflow_bench/definition.py):26–93 (`DataError as
DefinitionError`, `StrEnum` объявлен после использования, часть кодов — строки
вне enum: `purpose_mismatch`, `missing_final_cases`, `overlapping_cases`);
[harbor.py](../../src/workflow_bench/harbor.py) — `RuntimeError("stop_unconfirmed")` и
другие строковые коды; [cli.py](../../src/workflow_bench/cli.py):140–162.

Проблема. Три параллельных способа сообщать об ошибке (`DataError` с кодом,
`ArtifactError` с кодом, `RuntimeError` с текстом). CLI распознаёт коды только у
первых двух; всё остальное (в том числе все ошибки Harbor/Docker-слоя) превращается
в `unexpected_error` без traceback — даже в debug-режиме и даже в локальный файл.
Отладка падений integration-прогона требует чтения кода.

Рекомендация. Один базовый `BenchError(code, material)` с подклассами
`DataError`, `ArtifactError`, `EnvironmentError_`; все `RuntimeError("code")`
заменить на `EnvironmentError_("code")`. Коды — один `StrEnum` на модуль.
В CLI писать полный traceback в `output_root/error.log` (локальный файл, не stdout),
сохраняя безопасное однострочное сообщение в консоли.

### ARC-4

**Medium — проглатывание отмены без `uncancel()`; дубли watcher.**
Уверенность: подтверждено.

Где: [experiment.py](../../src/workflow_bench/experiment.py):46–106, 617–656.

Проблема. Watcher вызывает `task.cancel()`, а `run_manual` перехватывает
`CancelledError` и возвращает отчёт. С Python 3.11 у задачи остаётся
`cancelling() > 0`; без `task.uncancel()` любые последующие `asyncio.timeout()`
и `TaskGroup` в той же задаче ведут себя некорректно (структурная конкурентность
считает задачу отменяемой). Сейчас после возврата программа завершается, поэтому
дефект латентный, но `run_manual` — публичный Interface, который WB-07 будет
вызывать в цикле. Дублирование механики уже отмечено в COMPLEXITY_REVIEW S3.

Рекомендация. Один хелпер `async with cancellable(cancel, deadline):` (≈20 строк),
который при перехвате собственной отмены вызывает `task.uncancel()` и
различает «отменили мы» / «отменили извне». Тест: после `run_manual` с выставленным
`cancel` в той же задаче выполняется `asyncio.timeout(1)` без ложной отмены.

### ARC-5

**Low — симулятор и образ скрыто зависят от пакета хоста.** Уверенность: подтверждено.

Где: [app.py](../../simapps/telegram/app.py):17–30;
[build.py](../../environments/build.py):27–28.

Симулятор импортирует `workflow_bench.data/contracts`, а `build.py` копирует в образ
ручной allowlist из четырёх модулей. Новый импорт в `data.py` (например, из
`definition`) сломает образ только на этапе integration. Кроме того, `app.py`
читает `tools.json`, схемы и `e1.schema.json` при импорте модуля (побочные эффекты
на import).

Рекомендация. Выделить общий код в подпакет `workflow_bench/wire/` (без зависимостей
на Harbor) и копировать в образ подпакет целиком; fast-тест, импортирующий
`app.py` в изолированном `sys.path` только с этим подпакетом. Загрузку файлов
перенести в `serve()`.

---

## Корректность (латентные дефекты)

### BUG-1

**Low — латентные `UnboundLocalError`.** Уверенность: подтверждено, не достижимо
в текущем потоке.

- [harbor.py](../../src/workflow_bench/harbor.py):289–313 — `expected_cases`
  определяется только если существует `index.json`, но используется в ветке
  `"aggregate" in evaluation`.
- [experiment.py](../../src/workflow_bench/experiment.py):73–101 — `report`
  определяется только при `output_root.is_dir()`, а возвращается при отмене.

Рекомендация. Инициализировать до ветвления (`expected_cases = None` + явный
`DataError("missing_index")`; `report = None`) и покрыть веткой теста.

### BUG-2

**Low — исключения в `finally` маскируют исходную ошибку.** Уверенность: подтверждено.

Где: [execution.py](../../src/workflow_bench/execution.py):301–316;
[experiment.py](../../src/workflow_bench/experiment.py):242–244.

`finally` в `replay` читает `stop.json` и пишет `execution.json`; в `_run_manual`
`finally` выполняет `context.control("export")`. Если они падают (нет файла,
control недоступен, `control_too_large` из SEC-1), исходное исключение replay
теряется, а отчёт показывает вторичную причину. Кроме того, `context.finish()`
сам возвращает `stopped`, но затем то же значение повторно читается из файла.

Рекомендация. `finish()` возвращает структуру `{stop_confirmed, errors}` вместо
записи-и-чтения файла; вторичные ошибки в `finally` ловить и добавлять в `errors`,
не заменяя основное исключение (или использовать `ExceptionGroup`).

---

## Code smells

### SML-1

**Low — лишняя работа на каждый вызов.** Уверенность: подтверждено.

- [data.py](../../src/workflow_bench/data.py):106–139 — `validate_contract` при
  каждом вызове читает `wire.schema.json` из пакета, выполняет `check_schema`,
  обходит все `$ref` и строит новый `Draft202012Validator`. Вызывается в циклах по
  кейсам и критериям, в симуляторе — на каждый control-запрос.
  Рекомендация: `functools.lru_cache` на `resource_schema` и на построение
  валидатора по имени `$def`.
- [execution.py](../../src/workflow_bench/execution.py):186–202 — `_cli_data` для
  каждой строки, начинающейся с `{`, делает срез `output[offset:]` (копия до 4 MiB)
  → O(n²) по памяти/времени. Рекомендация: `raw_decode(output, offset)` без среза
  (метод принимает индекс), а с учётом SEC-2 — вообще отказаться от эвристики.

### SML-2

**Low — магические значения и устаревшие имена.** Уверенность: подтверждено.

- `materials.private_paths[0|1|2]` в 8 местах (известно из COMPLEXITY_REVIEW,
  rank 6) — заменить именованными полями `cases`, `rubric`, `final_cases`.
- Префикс `wb04` в runtime-идентификаторах (`wb04-manual-`, `wb04-replay-`,
  `wb04-profile-`, glob `wb04-replay-*/execution.json`, тег `wb-telegram:wb04`,
  маркер `WB04_PRIVATE_MARKER`) — название этапа зашито в протокол. Вынести в одну
  константу `RUN_PREFIX = "wb"`.
- Изменяемый тег `wb-telegram:wb04` в `task.toml`, тогда как config пиннит digest:
  два источника истины об образе.
- Хардкоды: таймаут `docker()` 10 s ([harbor.py](../../src/workflow_bench/harbor.py):127),
  360 s сборки и дефолты config в [build.py](../../environments/build.py):84, 97–116,
  `max_attempts: 2` в трёх местах, `AbortSignal.timeout(1000)` в пробе изоляции.
- `docker ps --format {{.ID}}` может вернуть несколько ID через `\n`; код
  передаёт строку в `docker inspect` как один аргумент.

### SML-3

**Low — `cli.py` содержит доменную логику.** Уверенность: подтверждено.

[cli.py](../../src/workflow_bench/cli.py):17–73: правило «три порта различны»
продублировано (строки 20 и 35–39); `model_preflight` — бюджетная политика,
не относящаяся к разбору аргументов. Из CLI функция вызывается с
`authorized=False`, поэтому `--model-preflight` **всегда** завершается
`model_not_authorized` (или более ранней ошибкой), а ветка `return {...}` из CLI
недостижима. Если это намеренный gate — назвать флаг `--check-budget` и
документировать ожидаемый отказ; логику перенести в `workflow_bench/budget.py`,
проверку портов — в одну функцию `E1Config.from_json`.

### SML-4

**Low — отчёт утверждает факты литералами; мёртвые поля.** Уверенность: подтверждено.

- [experiment.py](../../src/workflow_bench/experiment.py):263–264 —
  `"isolation_confirmed": True`, `"database_fresh": True` записываются константой.
  Сейчас верно (иначе `check_isolation` бросил бы исключение), но связь неявная:
  при изменении `check_isolation` отчёт продолжит утверждать проверку.
  `check_isolation` должен возвращать факты, которые и попадают в отчёт.
- [app.py](../../simapps/telegram/app.py):181 — `"violations": []` всегда пуст; всё
  управление critical-кодами идёт через критерии. Либо использовать поле (см. SEC-1,
  `request_flood`), либо убрать из контракта.
- [verify.py](../../tasks/t1-send-message/tests/verify.py):187–202 — запасной результат
  кейса не содержит `critical_violations`, остальные — содержат; потребители
  вынуждены писать `.get(...)`.

### SML-5

**Low — кодировка не указана.** Уверенность: подтверждено.

Ни один `write_text`/`read_text` в `src/`, `simapps/`, `tasks/` не передаёт
`encoding`, при этом JSON пишется с `ensure_ascii=False`, а кейсы содержат
кириллицу и эмодзи. В UTF-8 локали (macOS, Docker-образы Python 3.12) работает;
в иной локали хэши и содержимое отчётов будут отличаться. Рекомендация:
`encoding="utf-8"` везде (ruff правило `PLW1514` из `PL`, если включить).

---

## Тесты

### TST-1

**Medium — нет adversarial-тестов для точек, где вход контролирует кандидат.**
Уверенность: подтверждено (`tests/fast/test_simulator.py` содержит 2 теста,
`_cli_data` напрямую не тестируется).

Не покрыто:
- поток запросов без capability / сверх `max_calls` / с неизвестной `operation`
  (SEC-1);
- медленное тело запроса и медленный читатель ответа (SEC-3);
- вывод n8n с поддельным JSON-объектом, несколькими объектами, мусором в stderr (SEC-2);
- отмена `run_manual` с последующим `asyncio.timeout` в той же задаче (ARC-4).

Сильные стороны набора: проверка отказа от NaN/дубликатов, «closed branch»,
credential-ссылок, сохранения ввода как данных; integration-контроль изоляции и
доверия. Рекомендация — добавить перечисленные сценарии на уровне существующих
публичных Interface (`Telegram.tool` через `aiohttp` test client, `replay` с
фейковым `ExecResult`), без новых моков внутренностей.

---

## Репозиторий и документация

### REP-1

**Medium — `workflow-bench.zip` добавлен в индекс.** Уверенность: подтверждено
(`git status`: `AD workflow-bench.zip`).

Архив (≈37 KB, старые редакции AGENTS/ARCHITECTURE/SPEC/README/ROADMAP) staged, но
удалён из рабочего дерева. Следующий `git commit` занесёт бинарный снимок устаревших
документов в историю. Рекомендация: `git restore --staged workflow-bench.zip` и
добавить `*.zip` в `.gitignore`.

### REP-2

**Low — README как журнал изменений.** Уверенность: подтверждено.

README одновременно приводит «206 passed», «216 passed», «251 passed», «253 passed»,
«277 passed», «282 passed» для разных этапов; фактически сейчас 253. ARCHITECTURE.md
весит ≈140 KB и смешивает действующие контракты с историей (D1 в COMPLEXITY_REVIEW).
AGENTS.md требует обновлять документ-владелец факта, а не копировать описание.
Рекомендация: в README оставить только команды и ссылки; результаты прогонов —
в отчётах `docs/reviews/` или в истории git, не в README.

---

## План исправлений

| Порядок | Действие | Находки | Объём |
|---|---|---|---|
| 1 | Unstage `workflow-bench.zip` | REP-1 | минуты |
| 2 | Лимит запросов и событий в симуляторе + critical `request_flood` + тест | SEC-1, TST-1, SML-4 | малый |
| 3 | Разнести stdout/stderr, брать результат из файла/БД n8n, тест на подделку | SEC-2, SML-1 | малый–средний |
| 4 | Убрать сетевой I/O из-под lock симулятора | SEC-3 | малый |
| 5 | Разделить private/public корни запуска до WB-07 | SEC-4 | средний |
| 6 | Hardening: `USER`, `pids_limit`, размер tmpfs, лог-уровень runner | SEC-5 | малый |
| 7 | Единая иерархия ошибок, traceback в `error.log` | ARC-3 | малый |
| 8 | Хелпер отмены с `uncancel()` | ARC-4 | малый |
| 9 | Разбить `_run_manual`/`run_native_trial`, типизировать и валидировать отчёты | ARC-1, SML-2, BUG-1, BUG-2 | средний |
| 10 | Гейт тестов на штатных механизмах pytest | ARC-2 | малый |
| 11 | Попутно: единый безопасный reader, кэш схем, `encoding`, имена `wb04` | SEC-6, SML-1, SML-5, SML-2 | малый |

Пункты 2–5 стоит закрыть до подключения Composer (WB-07): после этого кандидат —
реальная модель, а не контролируемый файл, и находки SEC-1…SEC-4 становятся
достижимыми без участия автора бенчмарка.
