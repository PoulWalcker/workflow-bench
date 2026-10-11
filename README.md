# Workflow Bench

**Статус: WB-02–WB-04 выполнены; реальный native T1 без AI проверен.**
Продуктовая основа — SPEC v0.2 с согласованными уточнениями · 11 октября 2026 года.

Workflow Bench — инструмент для проверки того, как AI исследует доступные
инструменты, создаёт повторно используемый workflow и решает им бизнес-задачу.
Проверяем результат, корректность действий и эффективность. Показываем балл,
вердикт, причины ошибок и затраты, а не только ответ модели «всё сделано».

## Первый MVP

Одно приложение — **симулированный Telegram**. Подготовленные чаты и сообщения,
общие данные для API и виртуального UI с выбранными командами Blindly.
Настоящие аккаунты, рабочий стол, графическое окно и отправка реальных сообщений
не нужны. Работа в симуляции не доказывает совместимость с настоящим Telegram.

Четыре задания: отправка через API; отправка через UI; ответ по условию;
пересылка найденных сообщений без дубликатов. AI получает бизнес-цель, а не
готовый алгоритм. Формат сдаваемой автоматизации задаётся общим контрактом Composer.

```text
Task + инструменты
    → исследование учебного окружения
    → workflow.json (ограниченный native n8n JSON) → n8n
    → выполнение на свежих сценариях → проверки → feedback
    → исправления в пределах лимита
    → выбранная версия → скрытая итоговая проверка → отчёт
```

## Документация

| Файл | Для чего читать |
|---|---|
| [SPEC.md](SPEC.md) | Цель, границы MVP, задачи, процесс и требования к результату |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Стек, дерево проекта, владельцы компонентов и границы изоляции |
| [AGENTS.md](AGENTS.md) | С чего начинает coding-агент и как выполняет одну задачу |
| [Principles.md](Principles.md) | rTernarity, стиль кода, конфигурация, уместные тесты и TDD |
| [GLOSSARY.md](GLOSSARY.md) | Task, Case, Attempt, Replay, Evidence и другие термины |
| [ROADMAP.md](ROADMAP.md) | Существующий план WB-02–WB-15, зависимости и условия перехода |
| [WB-02](docs/implementation/WB-02-bootstrap.md), [WB-03](docs/implementation/WB-03-component-boundaries.md), [WB-04](docs/implementation/WB-04-e1-native-replay.md), [WB-05](docs/implementation/WB-05-e1-trust-and-failures.md) | Первый срез, технические уточнения и test seams для согласования |

## Техническая основа

Выбраны native Harbor Task, Docker, ограниченный native n8n JSON, Python/uv
и Codex Exec первым Composer. Sapiens проверяется на том же T1 сразу после
рабочего Codex-пути. Конкретные версии и совместимость требуют реального запуска;
компоненты и проверки описаны в [ARCHITECTURE.md](ARCHITECTURE.md).

## Как начать реализацию

Прочитать `AGENTS.md` и выполнять назначенную пользователем задачу. Минимальные
технические проверки описаны в ARCHITECTURE §8, инженерные контракты первого
среза — в §10, порядок работ — в ROADMAP. Состояние WB-04 и последующих задач фиксируется в ROADMAP.
Старый тикет `docs/implementation/01-project-structure.md` содержит
прежние требования (в том числе compiler) и не является текущим поручением;
актуальные границы задают SPEC и ARCHITECTURE.

Устанавливается `src/workflow_bench` с native Harbor parser и jsonschema.
Прямые runtime dependencies — Harbor 0.24.0, aiohttp 3.14.5, jsonschema и referencing
(локальное разрешение JSON Schema refs); разрешённые версии и
hashes всех транзитивных зависимостей находятся в `uv.lock`. Harbor устанавливает
в том числе модельные SDK; загрузка Task не вызывает модели или Docker.
`workflow-bench` — имя distribution, `workflow_bench` — импортируемый пакет.
Технический CLI WB-04 запускается как `python -m workflow_bench.cli`.

## Установка и быстрые проверки

Проверено 11 октября 2026 года на macOS arm64:

| Инструмент | Проверенная версия / источник фиксации |
|---|---|
| CPython | 3.12.13 / `.python-version`; baseline >=3.12 в `pyproject.toml` |
| uv | 0.12.4 / существующая установка, не обновлялась |
| uv_build | 0.12.4 / точная версия в `build-system.requires`, проверена изолированная PEP 517 сборка |
| pytest | 9.1.1 / `uv.lock`, dev group |
| Ruff | 0.17.0 / `uv.lock`, dev group |
| Harbor | 0.24.0 / точная прямая зависимость; проверены native Task/config parser |
| jsonschema | 4.26.0 / `uv.lock`; Draft 2020-12 |
| referencing | 0.37.0 / прямая зависимость для проверки локальных refs |

Prerequisites: доступный `uv` (проверена указанная версия) и доступ к PyPI и
загрузке Python при первом восстановлении. Системный `python3` 3.10.11 не
используется для проекта. Установка uv здесь не выполняется. Команды ниже —
из корня checkout, в shell с синтаксисом POSIX; Python и кэш остаются в проекте,
`--no-bin` не создаёт глобальных ссылок на интерпретатор.

```sh
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
uv python install 3.12.13 --no-bin
uv sync --locked
uv lock --check --offline
uv run --locked pytest -q
uv run --locked pytest --collect-only -q
uv run --locked ruff check src tests simapps environments tasks
uv run --locked ruff format --check src tests simapps environments tasks
```

В WB-04 быстрый pytest — 206 passed (101 S1 + 76 S2 + 29 S3/S5); Ruff lint/format — exit 0,
без lint-исключений.
Форматирование ограничено созданным Python-кодом: Ruff 0.17 также обрабатывает
Markdown; первоначальный `ruff format --check .` завершился exit 1 на примерах
в ARCHITECTURE и ещё не отформатированном новом коде. Новый код отформатирован,
архитектурные документы не переписывались.

Повторное `uv sync --locked --offline` прошло с заполненным кэшем. Для чистого
кэша требуется сеть; lock фиксирует версии и hashes, но не содержит дистрибутивы
зависимостей или Python. Другие ОС и версии Python/uv совместным запуском не проверены.

## Что проверяет S1

`tests/fast/test_gate.py` запускает настоящий pytest в временных проектах через
штатный pytester. Probes создают только локальные файлы-сигналы import/setup;
не обращаются к Docker, сети или моделям. Каждый дочерний запуск имеет timeout
10 секунд. Поведение gate реализовано в `tests/conftest.py`:

- Default и default collect-only не импортируют `tests/integration` и `tests/model`.
- Явный integration-каталог, файл или node ID без opt-in отклоняются до setup,
  включая collect-only и отбор через `-m`. Markers не ослабляют классификацию пути.
- Integration opt-in позволяет синтетическую fixture; collect-only с opt-in
  не запускает её. Model path/marker остаются закрыты.
- `--run-model` отклоняется с exit 4 как нереализованный режим, до collection,
  в том числе вместе с `--run-integration` или `--collect-only`.
- Для function/module/package/session fixtures gate проверяется до setup
  и получения cached value. Непомеченный fast-тест не может получить integration
  fixture даже с opt-in; model fixtures запрещены. Проверены запрос аргументом,
  через `request.getfixturevalue` и локальную fixture, включая повторное получение
  после разрешённого integration setup. Collect-only не выполняет setup.

Техническое исправление S1: на время pytest Config gate оборачивает
`pytest.FixtureDef.execute` и восстанавливает метод через `config.add_cleanup`.
Локальный `pytest_fixture_setup` недостаточен: pytest выбирает conftests по узлу
scope fixture и не вызывает этот hook для cached value. Потребляющий тест берётся
из `request._pyfuncitem`, поскольку `request.node` может быть Module, Package
или Session. Это зависимость от внутреннего устройства pytest, проверенная на
зафиксированной в lock версии 9.1.1; совместимость других версий не заявляется.

В репозитории есть fast-проверки gate и Definition S2. Настоящие resource fixtures,
Реальный integration-контроль WB-04 расположен в `tests/integration`; model-каталог
не создан. Ресурсы должны
создаваться внутри fixtures после проверки разрешения; import/collection,
параметризация и root autouse setup не должны создавать ресурсы
([Principles §5](Principles.md)). Gate защищает от случайного запуска тестовых
ресурсов и не является доказательством sandbox isolation.

В пустом временном проекте с одними gated probes default pytest честно возвращает
exit 5, без import/setup. Это проверка gate, а не успешная benchmark suite.
`pytest tests/integration --run-integration` требует подготовленного `--e1-config`;
проверенная полная команда приведена ниже. Отсутствующие Docker/images/credentials не объявляются зелёным skip.

## Публичный экспорт: S2

[definition.py](src/workflow_bench/definition.py) предоставляет Interface
`load_task(task_path, *, tool_contract) → TaskMaterials` и
`export_public(materials, destination) → PublicPackage`. Все пути абсолютные;
относительные пользовательские пути обрабатывает caller или CLI WB-04.
`TaskMaterials` содержит настоящий Harbor `Task`, публичные JSON-деревья,
постановку, проверенные приватные пути и hashes прочитанных материалов.
`PublicPackage` возвращает законченный каталог и относительные имена/SHA-256.
Имена файлов имеют одного владельца: `PUBLIC_PACKAGE_FILES` в
[contracts.py](src/workflow_bench/contracts.py). Loader/exporter используют этот
фиксированный набор; доверенные шаблоны Composer/workflow получают имена при
экспорте. Постановка Task не проходит шаблонную подстановку. Коды ошибок принадлежат
`DefinitionErrorCode`; `DefinitionError.code` сохраняет строковый контракт.
Деревья JSON после загрузки не мутируются. Полные условия вызовов и безопасные
коды `DefinitionError` описаны в docstrings этих функций.

Новая Task той же формы подключается своим путём: `instruction.md`, native
`task.toml`, публичный JSON по `metadata.wb_public`, приватные файлы по
`wb_cases`/`wb_rubric` и native verifier script. Core не регистрирует Task и не
интерпретирует имена её бизнес-операций. Публичный tool contract передаётся явно;
WB-04 получает его штатным exec из подготовленного app image.

Техническое решение WB-03: собственные схемы материалов/metadata/tools версии
1.0 лежат в устанавливаемых [resources](src/workflow_bench/resources/).
`task.json` сохраняет форму ARCHITECTURE §6: input_schema, example, feedback;
лишние поля в публичных envelopes отклоняются. Tools envelope содержит
`schema_version="1.0"`, `app_image`, `profile`, `tools`; app/profile совпадают
с `wb_app_image`/`wb_tool_profile`. Поля операций определяет
[tools.schema.json](src/workflow_bench/resources/tools.schema.json); core проверяет
их форму, уникальность имён и вложенные schemas, не предметную семантику.
Для input и tools поддержан Draft 2020-12 с fragment-ссылками на embedded `$defs`;
набор внешних схем в WB-03 пуст. HTTP/file refs отклоняются, включая неиспользуемые;
локальные refs должны разрешаться в schemas до приёма данных.
Каждый прочитанный файл ограничен 4 MiB до декодирования; JSON — UTF-8 без duplicate
keys и нечисловых/бесконечных значений.

Composer получает только instruction.md, task.json (весь учебный example.state
и публичные правила feedback), tools.json, workflow.md, workflow.schema.json,
composer.md. Cases.state/expected, rubric, tests/solution, native config,
служебные документы и личные файлы не экспортируются. Экспорт собирает allowlist
из снимков в памяти и ресурсов пакета, не обходит исходное дерево. Caller задаёт
новое имя destination с существующим parent и исключительно владеет этим именем
на время вызова; exporter пишет во временный сосед и публикует через rename.
При ошибке его временный каталог удаляется, существующий destination сохраняется.
Task во время загрузки должна оставаться стабильной. Это правила доверенного
host Interface, не sandbox-защита от конкурентной подмены filesystem.

Проверенная команда S2 (обычные временные файлы, настоящий native parser и validator):

```sh
uv run --locked pytest -q tests/fast/test_definition.py
```

76 проверок покрывают разрешённый учебный state, исключение приватного marker из
реальных input/state/expected, cases/rubric/tests/solution и личных файлов;
неверные схемы/пример, повреждённый JSON, duplicate keys, NaN/Infinity,
traversal/absolute metadata paths, symlink и его parent, FIFO/каталоги,
отсутствующие материалы, совпадение приватного пути с instruction, безопасную
ошибку глубоко вложенного native config, ссылки в tool schemas,
несовпадение профиля, конфликт destination и cleanup
при сбое записи. Последний контроль подменяет только файловую запись для ошибки
ОС; loader/exporter не подменяются. Вторая синтетическая Task проходит по пути
из другого cwd без регистрации. Импорты core просмотрены: предметных зависимостей
от Telegram/Sapiens нет. S2 не доказывает настоящий Harbor Trial или исполнение n8n.

Точный текущий T1-профиль задают [workflow contract](src/workflow_bench/resources/workflow.md)
и schema: четыре семейства nodes, версии/options, BenchInput/BenchResult. Это
проверенный профиль n8n 2.41.5, без заявления о выразительности будущих T2–T4.

## Проверка упаковки

В WB-03 выполнена изолированная PEP 517 сборка:

```sh
uv build --force-pep517 --offline
```

Wheel и sdist содержат пакет с ресурсами; кэши, среды, tests, служебные документы
и личные файлы исключены. Из собранного wheel установлен пакет в отдельный временный
`--target` через `uv pip install --offline --no-deps`; Python `-I` из другого cwd
импортировал именно этот установленный пакет и выполнил native load/public export
на синтетической fixture. Dependencies брались из проверенной locked `.venv`.
Это проверка поставки ресурсов wheel, не восстановление зависимостей с чистого кэша.

Первый `uv build --force-pep517` без offline не прошёл из-за DNS в sandbox;
повтор с offline использовал кэш и завершился exit 0. Попытка восстановить отдельную
wheel-среду только из кэша через `uv pip install --offline` также не прошла:
resolver не нашёл registry distributions части зависимостей. Для чистой установки
по-прежнему нужна сеть. Default fast pytest сети не требует.

## Не делаем в MVP

Не переносим старый `benchmarking` целиком; не создаём второй Harbor или движок
workflow; не подключаем настоящий Telegram; не строим UI-панель, plugin registry,
планировщик, универсальный DSL или систему Static App Models.

## Реальный технический контроль WB-04

Проверенная среда: macOS arm64, OrbStack, Docker 29.4.0, Compose 5.1.2,
Harbor 0.24.0, n8n и external runners 2.41.5. Образы n8n/runner и базовый Python
закреплены digest в `environments/build.py`. Сборка копирует публичный allowlist
и устанавливает зависимости по версиям/hashes из uv.lock. Task tests, solution,
checkout, home, Docker socket и credentials в образ не попадают. Подготовка
образов отделена от исполнения; ей нужны Docker и сеть при пустом image/cache.

Из корня checkout с экспортированными выше UV-переменными:

```sh
uv run --locked python environments/build.py --output runs/wb04/config.json
uv run --locked pytest -q tests/integration/test_manual.py --run-integration --e1-config runs/wb04/config.json --log-cli-level=INFO
uv run --locked python -m workflow_bench.cli --task tasks/t1-send-message --config runs/wb04/config.json --output runs/wb04/manual --case fresh-a --case fresh-b --case missing
```

Проверено 12 октября 2026 года: 3 integration tests passed, CLI exit 0.
Один source workflow дал правильные эффекты на fresh-a/fresh-b и отказ без
записи на missing; применимые критерии pass, completeness complete.

Config/output должны быть новыми путями; повтор использует новый output.
Config содержит immutable images, порты и конечные технические лимиты. Сборка
предлагает setup 90s, submission 20s, execute 45s, tool 5s, control/drain 10s,
verifier 30s, cleanup 25s, total 360s, CPU 1, RAM 1024 MiB, max_calls 8. Эти значения
относятся к инженерному E1 и не задают методику измерения AI.

`solve.sh` только сдаёт ручной файл через штатный oracle. До oracle upload
проверяется отсутствие приватных материалов; штатная `/solution` существует
только для доставки ручного контроля в submission. Submission останавливается
до приёма байтов. Для каждого case Harbor создаёт свежую replay среду и SQLite
volume; n8n import/execute запускает реальный JS через external runner. Binder
изменяет только literal JSON text BenchInput. Один исходный hash используется
для обоих новых chat IDs/texts и отсутствующего чата; одинаковые display names
не влияют на адресацию. Кейсы разработки опубликованы в репозитории, это не holdout.

n8n и runner имеют read-only root, tmpfs, CPU/RAM limit, cap_drop/no-new-privileges,
внутренние сети без host ports и bind mounts. Control слушает только management IP
симулятора, loopback port хоста и требует отдельный секрет. До workflow upload
проверяются реальные mounts/networks, недоступность control из n8n/runner и
отсутствие tests/solution/checkout/socket/control-secret. SSRF protection n8n
отключена для локального HTTP tool; сетевую границу обеспечивают Docker internal
networks. Это базовая изоляция, расширенные escape/fault-контроли остаются WB-05.

После revoke/freeze и подтверждённого stop host получает snapshots и журнал
acceptance/effect/response. Protected bundle помещается в staged native Task tests
до штатного separate verifier upload. Новый no-network verifier UID 65534 читает
root-owned, недоступные для записи inputs и не исполняет кандидат. Custom
BaseVerifier hook не понадобился: используется публичный VERIFICATION_START и
штатная доставка tests. Verifier проверяет фактические адресат, текст, кратность,
сохранность и журнал; claim/exit не заменяют критерии.

`report.json` разделяет execution/claim/criteria, содержит hashes/bindings и refs
на protected evidence и native Harbor/n8n logs. `manifest.json` фиксирует версии,
материалы, конфигурацию и отсутствие model calls. Score = null, verdict = unknown:
методика scoring ещё не утверждена. Harbor 0.24.0 ожидает reward-файл и записывает
`RewardFileNotFoundError`; evaluation сохраняется, фиктивный численный reward не
создаётся. Его deprecation warning Task.checksum также не подавляется.
CLI 2.41.5 не выводит native execution ID (проверен установленный execute.js):
native ID недоступен; replay ID и logs связывают исполнение. ID из свежей БД
не угадывается и отдельный accessor БД не добавляется.
Остановка и адресный cleanup подтверждаются Docker metadata; все runs вне Git.

## Статус разработки

Статус и результаты WB-04 — в [тикете](docs/implementation/WB-04-e1-native-replay.md).
WB-05 остаётся TODO: fault injection/потеря ответа, расширенные file/network
отрицательные контроли, missing/unknown, stop/cleanup failures. Composer, Judge,
repair loop, T2–T4 и полный scoring не реализованы. Модели не запускались.
