# Workflow Bench

**Статус: WB-02 выполнен; реализована минимальная основа пакета и среды.**
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
среза — в §10, порядок работ — в ROADMAP. WB-03 и последующие задачи остаются TODO.
Старый тикет `docs/implementation/01-project-structure.md` содержит
прежние требования (в том числе compiler) и не является текущим поручением;
актуальные границы задают SPEC и ARCHITECTURE.

Устанавливается минимальный `src/workflow_bench`, без runtime dependencies.
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
uv run --locked ruff check conftest.py src tests
uv run --locked ruff format --check conftest.py src tests
```

Результат: lock соответствует конфигурации; pytest — 23 passed, collect-only —
23 tests collected; Ruff lint/format — exit 0, без lint-исключений.
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
10 секунд. Поведение gate реализовано в корневом `conftest.py`:

- Default и default collect-only не импортируют `tests/integration` и `tests/model`.
- Явный integration-каталог, файл или node ID без opt-in отклоняются до setup,
  включая collect-only и отбор через `-m`. Markers не ослабляют классификацию пути.
- Integration opt-in позволяет синтетическую fixture; collect-only с opt-in
  не запускает её. Model path/marker остаются закрыты.
- `--run-model` отклоняется с exit 4 как нереализованный режим, до collection,
  в том числе вместе с `--run-integration` или `--collect-only`.
- Перед выполнением fixture из gated-каталога повторно проверяется gate;
  прямой запрос такой fixture из fast-теста отклоняется до файла-сигнала setup.

В репозитории пока есть только fast-проверки gate. Настоящие resource fixtures,
integration/model-каталоги и бизнес-тесты не созданы. Будущие ресурсы должны
создаваться внутри fixtures после проверки разрешения; import/collection,
параметризация и root autouse setup не должны создавать ресурсы
([Principles §5](Principles.md)). Gate защищает от случайного запуска тестовых
ресурсов и не является доказательством sandbox isolation.

В пустом временном проекте с одними gated probes default pytest честно возвращает
exit 5, без import/setup. Это проверка gate, а не успешная benchmark suite.
`pytest tests/integration --run-integration` сейчас не является рабочим контролем:
каталога нет. Отсутствующие Docker/images/credentials не объявляются зелёным skip.

## Проверка упаковки и восстановления

После установки импорт проверен с изолированным `sys.path` из другого cwd:

```sh
.venv/bin/python -I -c 'import os, tempfile; os.chdir(tempfile.gettempdir()); import workflow_bench; from importlib.metadata import version; print(version("workflow-bench")); print(workflow_bench.__file__)'
uv build
uv build --force-pep517
```

Обе сборки завершились exit 0: созданы sdist и wheel версии 0.1.0.
Предупреждение uv о кэше внутри checkout проверено просмотром обоих архивов:
кэш, Python-среда и служебные документы в них отсутствуют. Wheel содержит только
пакет и distribution metadata; sdist — пакет, README и project metadata.

Следующая команда также выполнена: она копирует только материалы установки в
новый временный checkout, восстанавливает отдельную non-editable среду из lock,
затем устанавливает собранный wheel в ещё одну среду. Оба импорта выполняются
вне checkout и возвращают 0.1.0 из `site-packages`; временные файлы удаляются
только внутри созданного этой командой каталога.

```sh
.venv/bin/python - <<'PY'
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root = Path.cwd()
environment = dict(os.environ, UV_CACHE_DIR=str(root / ".uv-cache"),
                   UV_PYTHON_INSTALL_DIR=str(root / ".uv-python"))
code = 'import workflow_bench; from importlib.metadata import version; print(version("workflow-bench")); print(workflow_bench.__file__)'
with tempfile.TemporaryDirectory(prefix="wb02-verify-") as temporary:
    scratch = Path(temporary)
    project = scratch / "project"
    project.mkdir()
    for name in ("pyproject.toml", "uv.lock", ".python-version", "README.md"):
        shutil.copy2(root / name, project / name)
    shutil.copytree(root / "src", project / "src",
                    ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["uv", "sync", "--locked", "--offline", "--no-editable"],
                   cwd=project, env=environment, check=True, timeout=60)
    python = project / ".venv" / "bin" / "python"
    subprocess.run([str(python), "-I", "-c", code], cwd=scratch,
                   check=True, timeout=10)
    wheel_env = scratch / "wheel-venv"
    subprocess.run(["uv", "venv", "--offline", "--python", str(python), str(wheel_env)],
                   env=environment, check=True, timeout=30)
    wheel_python = wheel_env / "bin" / "python"
    wheel = root / "dist" / "workflow_bench-0.1.0-py3-none-any.whl"
    subprocess.run(["uv", "pip", "install", "--offline", "--no-deps",
                    "--python", str(wheel_python), str(wheel)],
                   env=environment, check=True, timeout=30)
    subprocess.run([str(wheel_python), "-I", "-c", code], cwd=scratch,
                   check=True, timeout=10)
PY
```

Git-исключения проверены через `git check-ignore --no-index` на синтетических
именах `.env.probe`, `credentials/probe.json`, `runs/probe/result.json`, среды,
кэшей и wheel; настоящие секреты не создавались. `uv.lock`, `.python-version`,
исходники, тесты и `.env.example` не игнорируются.

## Не делаем в MVP

Не переносим старый `benchmarking` целиком; не создаём второй Harbor или движок
workflow; не подключаем настоящий Telegram; не строим UI-панель, plugin registry,
планировщик, универсальный DSL или систему Static App Models.

## Статус разработки

Реальные Harbor/n8n/Composer проверки ещё не выполнены. Документационные примеры
не являются готовыми Task или доказательством изоляции. Docker и модели в WB-02
не запускались; упаковка и gate не проверяют поведение benchmark. WB-03–WB-05
не реализованы. Блокировок WB-02 нет; первоначальный запрет записи глобального
кэша и недоступность сети в sandbox обойдены проектными каталогами и разрешённой
загрузкой зависимостей без изменения глобальных инструментов.
