# Workflow Bench

**Статус: WB-02 и WB-03 выполнены; загрузка native Task и публичный экспорт работают.**
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
среза — в §10, порядок работ — в ROADMAP. WB-04 и последующие задачи остаются TODO.
Старый тикет `docs/implementation/01-project-structure.md` содержит
прежние требования (в том числе compiler) и не является текущим поручением;
актуальные границы задают SPEC и ARCHITECTURE.

Устанавливается `src/workflow_bench` с native Harbor parser и jsonschema.
Прямые runtime dependencies — Harbor 0.24.0, jsonschema и referencing
(локальное разрешение JSON Schema refs); разрешённые версии и
hashes всех транзитивных зависимостей находятся в `uv.lock`. Harbor устанавливает
в том числе модельные SDK; загрузка Task не вызывает модели или Docker.
Команды запуска benchmark пока нет. `workflow-bench` — имя distribution,
`workflow_bench` — импортируемый пакет; CLI не создан.

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
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
```

Результат WB-03: lock соответствует конфигурации; pytest — 99 passed
(23 S1 + 76 S2), collect-only — 99 tests collected; Ruff lint/format — exit 0,
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
- Перед выполнением fixture из gated-каталога повторно проверяется gate;
  прямой запрос такой fixture из fast-теста отклоняется до файла-сигнала setup.

В репозитории есть fast-проверки gate и Definition S2. Настоящие resource fixtures,
integration/model-каталоги и исполняемые benchmark-проверки не созданы. Будущие ресурсы должны
создаваться внутри fixtures после проверки разрешения; import/collection,
параметризация и root autouse setup не должны создавать ресурсы
([Principles §5](Principles.md)). Gate защищает от случайного запуска тестовых
ресурсов и не является доказательством sandbox isolation.

В пустом временном проекте с одними gated probes default pytest честно возвращает
exit 5, без import/setup. Это проверка gate, а не успешная benchmark suite.
`pytest tests/integration --run-integration` сейчас не является рабочим контролем:
каталога нет. Отсутствующие Docker/images/credentials не объявляются зелёным skip.

## Публичный экспорт: S2

[definition.py](src/workflow_bench/definition.py) предоставляет Interface
`load_task(task_path, *, tool_contract) → TaskMaterials` и
`export_public(materials, destination) → PublicPackage`. Все пути абсолютные;
относительные пользовательские пути обрабатывает caller. CLI ещё нет.
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
получение из app image ещё относится к WB-04.

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

Шаблон общего [workflow contract](src/workflow_bench/resources/workflow.md) и его schema
сейчас описывают только сдачу и общий native envelope. Точные node types,
typeVersion/options, bindings, BenchInput/BenchResult и runtime compatibility
предстоит закрепить и проверить в WB-04; envelope не разрешает исполнение сам по себе.

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

## Статус разработки

WB-03 выполнен; его критерии и передача следующему срезу — в
[тикете](docs/implementation/WB-03-component-boundaries.md). WB-04–WB-05 не начаты.
Реальные Harbor Trial/n8n/Composer и Docker sandbox isolation ещё не проверены.
Docker и модели не запускались; рубрики/кейсы не валидируются и не исполняются
Definition. S2 и упаковка не подтверждают готовность benchmark или E1.
