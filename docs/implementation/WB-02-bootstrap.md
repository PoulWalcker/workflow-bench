# WB-02 — минимальная основа репозитория и среды

Статус: **DONE** · 11 октября 2026 года. Этап 1 [ROADMAP](../../ROADMAP.md).
S1 согласован пользователем и проверен безопасными локальными probes.
Фактические версии, команды, результаты и ограничения — в [README](../../README.md).

## Цель и наблюдаемый результат

Из чистого checkout можно воспроизвести Python/uv-среду, установить минимальный
пакет и выполнить быстрые проверки. README описывает только действительно
работающие команды. Benchmark, компоненты E1 и модельные интеграции ещё не созданы.

## Основание

- [SPEC §11](../../SPEC.md): Python/uv, воспроизводимость зависимостей.
- [ARCHITECTURE §1 и §6](../../ARCHITECTURE.md): обязанности и будущее размещение;
  дерево не является требованием создать все модули сразу.
- [Engineering rules](../../AGENTS.md): минимальность, конфигурация,
  Ruff, разделение проверок и проверенные команды.

## Зависимости

Текущие документы и запрос на реализацию этого тикета. WB-01 не является
зависимостью. Перед изменением повторно проверить checkout и пользовательский diff.

## Что входит

1. Проверить доступные Python/uv и выбрать совместимые версии как техническое
   решение задачи. Создать минимальные `pyproject.toml`, lockfile и устанавливаемый
   Python-пакет; зависимости добавлять только для текущих проверок.
2. Настроить Ruff (lint и format) и pytest, отделив будущие
   интеграционные/model-backed проверки от default-запуска. Не выдавать отсутствие
   бизнес-тестов за проверку поведения benchmark.
3. Настроить исключения Git для среды, `runs/`, credentials и локальных артефактов;
   существующее содержимое пользователя не удалять и индекс не исправлять.
4. Проверить восстановление среды и импорт установленного пакета, в том числе
   без зависимости от cwd. Обновить README командами установки и быстрых проверок,
   их prerequisites и честными ограничениями текущей реализации.

## Что явно не входит

Организация всех компонентов; пустые experiment/execution/evaluation/adapters;
Task-каталоги, Docker images, Harbor/n8n, симулятор, CLI benchmark, CI-платформа,
Composer/Judge, оплачиваемые вызовы. Не добавлять второй formatter/type checker
или внешние подсистемы на будущее.

## Затрагиваемые компоненты

Только упаковка минимального пакета, конфигурация инструментов разработки,
исключения Git и README. Будущие продуктовые обязанности задаёт WB-03.

## Уместные проверки поведения

### Техническое решение для coding-сессии

Минимальный устанавливаемый `src/workflow_bench` без продуктовых модулей.
Build backend — `uv_build`; runtime dependencies WB-02 пусты, dev group содержит
только pytest и Ruff. Python 3.12 — рекомендуемый baseline на основании
[ARCHITECTURE §6](../../ARCHITECTURE.md), а не уже проверенная установка.
Patch Python, uv, build backend и dev versions выбраны установкой и проверками
этой задачи; результаты принадлежат README. `uv.lock` фиксирует разрешённые версии;
для изолированной сборки backend закрепляется в build-system отдельно от lock.
При статической проверке документов `python3` сообщил 3.10.11; это не проверка
доступности других интерпретаторов. Python/uv проверены при реализации WB-02.
Никаких Harbor/jsonschema/aiohttp в bootstrap: исторические сроки их появления — WB-03/04.

Ниже **предложение design-сессии**, не файл установки.
Реализованный `pyproject.toml` содержит project/build metadata и проверенные зависимости.
Python baseline имеет один источник в `project.requires-python`; Ruff выводит
target version из него, отдельный `target-version` не нужен.

```toml
[project]
requires-python = ">=3.12"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-config", "--strict-markers", "--import-mode=importlib"]
markers = [
  "integration: real Harbor/n8n control; requires --run-integration",
  "model: paid model control; requires explicit permission and finite limits",
]

[tool.ruff]
line-length = 88
src = ["src"]

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "UP", "B"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"
```

E4/E7/E9/F выявляют ошибки Python, I приводит импорты к одному порядку,
UP удерживает синтаксис выбранного Python, B ловит распространённые ошибки.
Не включаем ALL и конфликтующие с formatter стилистические группы.
88 колонок — цель formatter, а не искусственный запрет длинного URL (E501
не включён). Предварительных ignore/per-file-ignores нет; политика исключений
принадлежит AGENTS “Code quality and portability”.
[Ruff configuration](https://docs.astral.sh/ruff/configuration/),
[uv build backend](https://docs.astral.sh/uv/concepts/build-backend/).

Gate pytest реализуется по [Engineering rules](../../AGENTS.md), а не одним
marker. Небольшой `conftest.py` — конфигурация тестового запуска, не продуктовый
компонент. Пустые fast/integration/model каталоги и бессодержательные тесты
не создаются. Без тестов фиксируем pytest exit 5, а не заявляем покрытие benchmark.
Проверка импортируемости установленного пакета — smoke упаковки отдельной
командой из другого cwd, не тест внутренней структуры пакета.

### Согласованный test seam S1

| Interface | Поведение / что обнаруживает | Чего не доказывает | Настоящий запуск или подмена |
|---|---|---|---|
| Установка пакета и конфигурация pytest | Восстановление lock, импорт вне checkout; default/collect-only/явный integration path без opt-in не выполняют resource setup; model mode закрыт | Бизнес-поведение, n8n и Docker isolation | Реальная локальная установка и pytest с безопасным временным probe, без сетевых/контейнерных вызовов в probe |

Порядок: сначала минимальная упаковка и проверка среды; gate — один безопасный
падающий probe → минимальная реализация gate → следующий обход. При согласовании
допустим отдельный поведенческий тест gate, но не тесты на каждый import/getter.
Остальные проверки ниже — smoke/инструменты, а не искусственные unit tests.

- Восстановление зависимостей из lockfile и импорт установленного пакета в
  изолированной среде/из другого рабочего каталога.
- Ruff проходит на созданном коде; быстрый запуск не вызывает Docker и модели,
  не требует credentials. Если тестов ещё нет, это явно отражено, а не скрыто
  бессодержательным `assert True` или отключением ошибок.
- Проверка Git-исключений для синтетических имён credentials и результатов
  без создания настоящих секретов.

## Критерии готовности

Все заявленные команды реально выполнены и воспроизводимы по README; lockfile
соответствует конфигурации; нет машинных путей и будущих зависимостей.
Diff ограничен основой проекта. Ни установка Harbor, ни интеграция не объявлены
проверенными. Отчёт содержит команды, результаты и непроверенные prerequisites.

## Что останавливает работу и требует решения

Нет доступного способа установить/воспроизвести согласованную среду; выявлено
противоречие требуемой версии Python с нужными зависимостями; требуются изменения
пользовательских файлов или внешнего окружения за пределами поручения.
Сохранить конкретную ошибку и минимальный вопрос. Отсутствие Docker не блокирует
bootstrap, но не считается успешной проверкой E1.

## Передать следующей задаче

WB-03 получает минимальный установленный пакет, фактические команды и ограничения
среды. Не передавать список пустых модулей как выполненную архитектуру.

## Historical setup and gate evidence

Moved from the former README during documentation consolidation; these are historical checks, not new runs.

### Setup baseline

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

### Gate verification

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
([Behavioral TDD](../../AGENTS.md#behavioral-tdd)). Gate защищает от случайного запуска тестовых
ресурсов и не является доказательством sandbox isolation.

В пустом временном проекте с одними gated probes default pytest честно возвращает
exit 5, без import/setup. Это проверка gate, а не успешная benchmark suite.
`pytest tests/integration --run-integration` требует подготовленного `--e1-config`;
проверенная полная команда находится в README. Отсутствующие Docker/images/credentials не объявляются зелёным skip.
