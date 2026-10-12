# WB-05 — E1: доверие, отрицательные контроли и остановка

Статус: **DONE** (12 октября 2026). Технический E1 закрыт вместе с WB-04.
Этап 1 [ROADMAP](../../ROADMAP.md).

## Цель и наблюдаемый результат

На работающем пути WB-04 доказать, что неправильный workflow не проходит проверку,
кандидат не может читать приватные данные или подменять факты, а потеря ответа,
missing reward и неподтверждённый stop не превращаются в успех либо нулевой score.
Успешное завершение этого тикета вместе с WB-04 закрывает технический E1.

## Основание

- [SPEC §8–10](../../SPEC.md): полнота, факты, ошибки/unknown, доверие;
  §12 п. 4–6 и 9: отрицательные контроли, реальные обходы, stop и cleanup.
- [ARCHITECTURE §3–5](../../ARCHITECTURE.md): сдача/native-профиль, capability,
  сеть/файлы/stop, Evidence и reward; E1 — в ROADMAP.
- [Engineering rules](../../AGENTS.md): реальные проверки, честная оценка,
  конечность операций и отсутствие слепых повторов.

## Зависимости

[WB-04](WB-04-e1-native-replay.md) дал реальный воспроизводимый сквозной контроль.
Базовая изоляция уже действует. Для fault-контролей используются только
синтетические приватные маркеры и собственные ресурсы эксперимента.

## Что входит

1. На том же runtime/verifier подготовить отрицательные native workflow и
   управляемые faults по таблице. Проверить заявленные ограничения фактическими
   попытками, в том числе из n8n и его JS runner.
2. Исправить обнаруженные дефекты только в пределах E1. Для регрессии сначала
   закрепить падающее поведение; не менять expected вслед за ошибочным workflow.
3. Проверить закрытие capabilities, принятые операции, остановку процессов и
   адресный cleanup. Сохранить неизвестность там, где факт нельзя подтвердить.
4. Проверить преобразование Evaluation ↔ Harbor reward для полной технической
   числовой fixture и неполного результата. Числовая fixture проверяет parser,
   а не задаёт веса/пороги T1. При неутверждённой методике T1 остаётся без score.
5. Сохранить компактную сводку E1: каждый контроль → команда → expected → факт
   → evidence/статус. Приватные данные и сырые runs остаются вне Git; README
   получает лишь реально проверенные команды и prerequisites.

## Что явно не входит

Модели, Judge, полный UI/Telegram, T2–T4, интеграции Composer и полный repair loop.
UI-only→API будет реально проверен в WB-10; здесь проверяются ограничения
существующего T1-профиля и недоступность control/чужого run. Не создавать UI ради
преждевременного покрытия E4. Не добавлять второй verifier-путь без причины WB-04.

## Затрагиваемые компоненты

Интеграционные fixtures проекта и T1, capabilities/control/journal симулятора,
изоляция replay/runner/verifier, приём артефакта, преобразование evaluation/reward,
stop/cleanup Harbor binding. Новые бизнес-правила core не получает.

## Уместные проверки поведения

### Техническое уточнение и согласованные test seams

Используется единственный путь, полученный WB-04, и контракты
[ARCHITECTURE §4–5](../../ARCHITECTURE.md). Не вводить второй verifier.
S3–S5 из WB-04 расширяются отрицательными примерами ниже; их подтверждение
не выводится из проверки JSON Schema. Дополнительные seams:

| Interface | Поведение / что обнаруживает | Чего не доказывает | Настоящий запуск или подмена |
|---|---|---|---|
| S6: tools/control → frozen evidence | Capability scope/revoke, commit при потере ответа, монотонный журнал, запрет новых эффектов после freeze; неизвестное не становится no_effect | Реальную контейнерную сеть при локальном тесте transport | Настоящий simulator; управляемый fault после commit. Real replay/runner probes подтверждают доступ и изоляцию отдельно |
| S7: Harbor lifecycle → RunResult | Start/exec/verifier failure, timeout/cancel, stop_confirmed и residual resources; отсутствие auto-retry; соседние ресурсы сохранены | Моки не доказывают остановку процессов | Быстрые ошибки на внешнем exec/control transport; обязательные реальные start/cancel/cleanup контроли |
| S8: Evaluation → native verifier reward | Числовая fixture проходит parser; null/missing остаётся неполнотой; stale/поддельный reward не принимается | Методологию score T1 и качество Judge | Реальный helper локально; настоящий Harbor parser/verifier в integration, без модели |

Конкретные точки fault: недоступная среда до start; ошибка внешнего exec;
разрыв tool-ответа **после записи**; зависшая принятая операция на drain;
отказ stop; timeout/ошибка verifier; отсутствие reward после сохранения evaluation.
Локальная подмена находится на внешнем IO seam, наши evaluator/binder не мокаются.
Управляемая инъекция не включает подмену факта, который должна доказать проверка.
Ожидаемые state deltas и статусы заданы вручную по публичному правилу Task.

Особенно проверить существующие особенности Harbor: ошибки collection/stop могут
лишь логироваться; `/logs/verifier` агентской фазы нельзя принимать за доверенный
reward; automatic `/logs/artifacts` остаётся кандидатским вводом. Пробы включают
stale reward, symlink на этапе передачи, попытку фоновой перезаписи и mismatch
identity. При утрате доверия completeness=invalid, а не fail качества модели.

TDD после согласования: воспроизвести один дефект → падающий regression на seam →
минимальное исправление → адресный настоящий контроль и положительный T1, если
изменился общий путь. Отрицательный workflow не исправляется ради green.
Явно запрошенная integration без Docker/image должна завершаться ошибкой preflight,
не skip. Сводка E1 связывает каждую строку исходной таблицы ниже с командой,
ожиданием, наблюдением и evidence; ни одна строка не теряется при группировке seams.

| Контроль | Ожидаемый результат |
|---|---|
| Неверный получатель/текст, дубликат, постороннее изменение | Предметные критерии фиксируют fail по trusted state/journal; `exit 0` и заявление success не помогают |
| Запомненный учебный ID/текст вместо input | На новом input неизменный неправильный workflow проваливается; правильный контроль по-прежнему проходит |
| Missing/невалидный файл, symlink/path traversal, недопустимые nodes/options | Артефакт не исполняется; missing/invalid и причина зафиксированы; host не читает произвольный путь и не чинит JSON |
| Чтение приватных tests/solution/итоговых fixtures и искусственного секретного маркера | Попытки из среды сдачи, replay и runner отклонены; те же сведения отсутствуют в public export и build context |
| Выход к control/admin, другому run/case, host/Internet, Docker socket | Доступ реально отклонён в replay и runner на выбранном Docker host; candidate capability не даёт reset/export/freeze; разрешённые tools остаются работоспособны |
| Подмена evidence/reward и refs/идентичности bundle | Кандидатский файл не становится доверенным источником; mismatch run/case/version или неполнота обнаружены; при утрате доверия measurement invalid, не pass |
| Потеря ответа после commit | Журнал и snapshot подтверждают эффект, runtime хранит transport unknown/ошибку; стенд не повторяет запись. Контроль без доказанного подтверждения не заявляет полный успех; вариант со слепым повтором выявляется как нарушение/дубль |
| Timeout и явная отмена во время выполнения | Новые tool-действия закрыты, принятые завершены либо явно unknown; проверены n8n, runner и процессы среды сдачи. Прекращение ожидания не считается stop; при отсутствии подтверждения `stop_confirmed=false` |
| Повторное использование/истечение capability | После revoke и лимита новые эффекты не возникают; кандидат не выбирает чужие run/case/actor полями запроса |
| Срыв старта среды или verifier, пропавшие обязательные факты | Infrastructure error/incomplete и score=null, а не нулевое качество модели; известный критический fail сохраняется, неполнота не даёт pass |
| Harbor reward: числовая fixture и missing | Число корректно читается; null не записывается как число. Отсутствующий стандартный reward сохраняется как incomplete/error оценки, не candidate failure. Если обоснованно выбран hook, проверить rewards=None |
| Cleanup после успеха, ошибки и отмены | Удалены только ресурсы этого run; собственный контрольный соседний ресурс остаётся; неуспешная очистка и незавершённая работа отражены явно |

Сетевые probes используют контролируемые тестовые адреса/сервисы без обращения
к настоящему Telegram или desktop. Эмуляция fault позволяет воспроизвести сбой,
но ключевые эффекты, отказы доступа и остановка проверяются на настоящем
Harbor/n8n. Моки подходят только для дополнительных ветвей локальной обработки.

## Критерии готовности

Все применимые строки таблицы выполнены с ожидаемым поведением и доступным
evidence; после исправлений положительный сквозной контроль продолжает работать.
Версии/настройки изоляции и границы подтверждённого stop записаны. Доверенные
факты отделены от заявлений workflow, техническая числовая fixture — от методики
T1. Быстрые проверки и реальные E1-контроли запускаются отдельно.
Нет незакрытого обязательного контроля под видом skip из-за отсутствия Docker.
E1 выполнен; Codex ещё не разрешён без WB-06 и отдельного разрешения/лимитов.

## Что останавливает работу и требует решения

Кандидат читает приватные данные, пишет trusted evidence или обходит сеть;
остановка не подтверждается; недоступен обязательный реальный контроль;
передача missing reward теряет неполноту; нужен собственный orchestrator или
изменение согласованной архитектуры. Локально устранимый дефект исправить и
перепроверить; иначе сохранить минимальный воспроизводитель и конкретный вопрос.
Известный провал неверного workflow — ожидаемый контроль, а не blocker стенда.

## Передать следующей задаче

WB-06 получает сводку E1, закреплённые версии/профиль, команды и evidence,
доступные метрики и ограничения, фактические технические пределы и список
методических решений для T1. Численные значения E1 не переносятся автоматически
в бюджеты E2. Поздние тикеты уточняются по этим фактам, без объявления уже
готовыми Composer, UI, исправлений, Judge или MVP.

## Реализация и evidence, 12 октября 2026

Исходный HEAD: `46a5cc84df67d49d9eb56552ac3a3eeeeb6348c6`. WB-04 и исправления
AUD-S1/S2/F1–F3 проверены до основной реализации: 216 fast tests и 3 настоящих
integration tests на заново собранном image текущего HEAD. Старый config ссылался
на отсутствующий image: первый real запуск завершился ошибкой до старта, не skip.
После подготовки образа baseline прошёл. CODE_QUALITY_AUDIT прочитан в начале;
REMEDIATION_PLAN отсутствовал. Audit также отсутствовал при финальном осмотре
рабочего дерева; эти внешние документы не восстанавливались и не редактировались.
Существующее AD-состояние ZIP сохранено. Commit/push не выполнялись.

S3–S8 явно согласованы пользователем в этой сессии. Установленные codebase-design,
domain-modeling и tdd применены без установки/обновления. Термины SPEC сохранены.
Red → green зафиксирован для W1, W2, cleanup residuals, отказа revoke, lost response,
pending drain, unknown exec, reward helper, повреждённых facts, явного cancel,
подделки evaluation до verifier, конечного native stop/kill-reap и безопасных CLI
logs. Реальная red-проба stale reward показала принятие кандидатского reward;
после очистки фазового каталога regression прошёл.

Технические решения и coupling к Harbor принадлежат [ARCHITECTURE §4](../../ARCHITECTURE.md#4-harbor-lifecycle-and-trust-topology).
W1 закрыт обратной достижимостью BenchResult, W2 — ceil native limits при точном
внешнем deadline, W3 — structured cleanup errors/residual resources. Числовая
fixture `7.25` не задаёт веса, thresholds или агрегацию T1. У T1 score=null,
verdict=unknown; известные критерии сохраняются, missing reward — отдельная
неполнота assessment. Повтор оценки не повторяет действия.

Команды и prerequisites — в [README](../../README.md#verified-docker-controls).
Группы ниже обозначают точные команды оттуда: **fast**, **native**, **lifecycle**.
Сырые evidence/logs/config/manifest находятся только в игнорируемом `runs/`.

| Исходный контроль | Команда / regression | Ожидание и наблюдение / evidence |
|---|---|---|
| Неверные получатель/текст, дубль, постороннее изменение | native: `test_negative_native_effect_cannot_pass`; fast: preservation fixture | Native effects проверяются отдельным Task verifier; адресат/текст/кратность и дополнительный send дают fail. Изменение старого состояния отдельно выявляет preservation. Защищённые bundles в `runs/wb05-final-negative-confirm/test_negative_native_effect_ca*/run/task/tests/bench-input/` |
| Запомненный учебный input | native: вариант memorized; positive T1 fresh-a/fresh-b/missing | Идентичная неправильная логика на новом input проваливает multiplicity; правильный контроль остаётся рабочим |
| Missing/invalid, traversal/symlink, nodes/options | fast: Definition/Execution; native: collection symlink и artifact-parent canary | Missing/unsafe/invalid отклоняются до replay; source symlink отклоняется receiver. Native collection не следует candidate parent symlink к синтетическому host canary; исходный marker сохранён, штатный файл принят. W1 Trap запрещён. Native result/logs в `test_symlink_during_native_col*/run/harbor/` и `test_candidate_artifact_parent0/` |
| Приватные tests/solution/fixtures/marker | fast: public export; lifecycle: isolation; native: JS escape probes | Синтетический private marker положен только в tests. Submission/replay/runner не читают private paths; попытки Code node проходят через настоящий JS runner. Public export/build allowlists исключают tests/solution/checkouts/home |
| Control/admin, чужой run, host/Internet, Docker socket | lifecycle: network/files/cross-run; native: unauthorized/JS probes | Отказ в реальных n8n/runner; denied control, другой tools IP, host listener, unrouted external address и socket. Scope подменой actor/run в body не меняется. Internal networks/no bind mounts подтверждены metadata; разрешённые tools работают. `isolation.json` |
| Подмена evidence/reward, refs/identity | native: file/symlink/background stale reward; fast: phase gate/envelope; numeric fixture | Agent-phase файлы удалены после stop; fake evaluation до verifier игнорируется. Mismatch и повреждённые refs/events/revisions invalid, без business verdict. Native rewards не заменяют отсутствующий evaluation |
| Потеря ответа после commit | native: lost response; lifecycle: observation/blind retry | Один commit и response failed при runtime failed; partial, score=null. Разрешённое чтение наблюдает эффект. Преднамеренный слепой retry создаёт два commit/дубль; штатный replay пишет один раз. `lost-response-evidence.json` и protected native bundle |
| Timeout/cancel во время исполнения | lifecycle: children [False/True] и manual submission cancel | Активные n8n exec и submission `sleep 600` зафиксированы Docker top до cancel; среды сдачи, n8n и runner stopped, собственные контейнеры/сети/volume удалены. Timeout и cancel сохранены; unconfirmed stop не подменяет исходную причину. `execution.json`, `stop.json`, `processes-before-cancel.txt`, `submission-before-cancel.txt` и cancelled/null report |
| Reuse/expiry capability | lifecycle: revoke/max_calls/cross-run, expiry/drain | Новый send после revoke/лимита/expiry не меняет state. Freeze pending фиксирует unknown; late commit запрещён, повтор export совпадает. `pending-evidence.json` |
| Start/verifier failure, missing facts | lifecycle: failed image/verifier error/timeout; fast: missing evidence/expectation | Неуспех infrastructure → unavailable/partial и null, без candidate zero; known fail при неполноте сохраняется. Native logs/result и failed-start report сохранены |
| Numeric/missing Harbor reward | native: numeric и forged/missing; positive T1 | Настоящий Harbor parser прочитал 7.25; отсутствующий reward не заменён числом. T1 сохраняет evaluation и RewardFileNotFoundError/reward_status=incomplete |
| Cleanup success/error/cancel | обе real группы; lifecycle: stop refusal/cleanup fault и соседний run | Подтверждены собственные удаления после успеха, faults и cancel. При управляемом отказе transport реально остаются owned containers/networks/volume; их IDs сохранены в `cleanup-failure.json`, затем удалены исходным Harbor handle. Соседний run продолжает работать |

### Фактически выполненная verification

Каждый из 29 уникальных integration controls имеет подтверждённый green;
это объединение отдельных запусков, не заявление о единой suite из 29 tests.
Индекс результатов: `runs/wb05-e1-summary.json` (29 expected, 29 confirmed,
missing=[]). Команды ниже выполнены из корня checkout с UV cache/install paths
из README. `uv run --locked --offline` обозначен как `uv run` для краткости.

| Команда | Фактический результат / log |
|---|---|
| `uv run pytest` | 233 passed, 24.94 s; `runs/wb05-final-fast.log` |
| `uv run ruff check src tests simapps environments tasks` | exit 0, All checks passed |
| `uv run ruff format --check src tests simapps environments tasks` | exit 0, 31 files already formatted |
| `uv lock --check --offline`; `git diff --check` | exit 0; lock неизменён, 97 packages |
| `uv run python environments/build.py --output runs/wb05-final/config.json` | exit 0; allowlisted build context удалён, immutable app image сохранён |
| `uv run pytest -q tests/integration/test_manual.py tests/integration/test_trust.py --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-native --log-cli-level=INFO` | 14 passed, 2 failed, 764.71 s; все 3 WB-04 manual/read controls passed. Два новых fixture-сбоя исправлены и перепроверены ниже; этот запуск не объявляется полностью passed |
| `uv run pytest -q tests/integration/test_trust.py::test_negative_native_effect_cannot_pass --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-negative-confirm --log-cli-level=INFO` | exit 0, 5 passed, 296.65 s; `runs/wb05-final-negative-confirm.log` |
| `uv run pytest -q tests/integration/test_trust.py tests/integration/test_delivery.py -k 'not negative_native_effect' --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-boundaries-confirm --log-cli-level=INFO` | exit 0, 9 passed, 5 deselected, 343.35 s; `runs/wb05-final-boundaries-confirm.log`. Deselected пять вариантов проверены предыдущей командой |
| `uv run pytest -q tests/integration/test_lifecycle.py tests/integration/test_isolation.py --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-lifecycle --log-cli-level=INFO` | exit 0, 11 passed, 269.37 s; `runs/wb05-final-lifecycle.log`, до добавления submission cancel |
| `uv run pytest -q tests/integration/test_lifecycle.py::test_real_manual_cancellation_stops_submission_process tests/integration/test_lifecycle.py::test_real_verifier_failure_does_not_become_candidate_zero --run-integration --e1-config runs/wb05-final/config.json --basetemp runs/wb05-final-submission-cancel --log-cli-level=INFO` | exit 0, 3 passed, 95.78 s; один новый submission cancel и два повторных verifier controls; `runs/wb05-final-submission-cancel.log` |
| `uv run python -m workflow_bench.cli --task tasks/t1-send-message --config runs/wb05-final/config.json --output runs/wb05-final/manual-confirm --case fresh-a --case fresh-b --case missing` | exit 0, 131.37 s; все критерии pass/not_applicable, три completed replay, cleanup_errors/residual_resources=[], null scores. Stdout содержит JSON ref, stderr без DEBUG; `runs/wb05-final-cli-confirm.*` и `manual-confirm/report.json` |
| Read-only Docker Compose label inspection после завершения controls | 0 benchmark containers/networks/volumes; `runs/wb05-final-resources.json`. Чужие ресурсы не удалялись |

Сохранены и ранние отрицательные результаты проверки стенда. Синхронизация cancel
по console output не наблюдала реально активный процесс: заменена наблюдением
Docker top, затем 2 passed (`runs/wb05-cancel-confirm.log`). В native fixtures
были malformed expression постороннего send и запрещённое n8n обращение
`$json.arguments`; исправлена только упаковка запросов, исходные expected effects
сохранены. Повтор, начатый до исправления второго fixture, дал 13 passed/1 failed
(`runs/wb05-final-trust-confirm.log`); окончательные два green-запуска приведены
выше. Первый artifact-parent canary уже прошёл без изменения production-кода
(`runs/wb05-delivery-red.log`, 1 passed): это подтверждение существующей защиты,
а не выдуманный red. Broad `ruff format --check .` по-прежнему отмечает старые
Python-примеры Markdown; установленная code-only команда прошла. Harbor
Task.checksum deprecation warnings сохранены, не подавлены.

### Проверенное окружение и пределы

Docker 29.4.0 / Compose 5.1.2, Harbor 0.24.0, aiohttp 3.14.5,
pytest 9.1.1, Ruff 0.17.0; n8n/runner 2.41.5. Образы:

- app: `sha256:b4f2655ddc74e113133abc79cf92a5f822f2a2a2f5d693608f15e10473344da3`;
- n8n: `n8nio/n8n@sha256:6f532d3b819cfe66c6a13c5375228f312c53df1abaa11a377eb8c3d3f105c363`;
- runner: `ghcr.io/n8n-io/runners@sha256:32619142405e7f4a02eedffe8584214c7e0b9b09d3753094e4212aee5f4d0045`.

Конфигурация из `runs/wb05-final/config.json`: setup/submission/execute/tool/control/
drain/verifier/cleanup/total = 90/20/45/5/10/10/30/25/360 s; 1 CPU, 1024 MiB,
8 calls; tools/control/broker = 8080/8081/5679, host management port динамический.
У отдельных lifecycle fixtures пределы намеренно сокращены; их фактический config
и native result находятся в соответствующем run. Это технические пределы E1,
не принятые бюджеты E2.

Изоляция доказана для этого Docker host и T1-профиля. Сетевые пробы обращались к
собственному host listener, control/соседнему run и reserved unrouted address;
реальный Telegram/desktop не использовались. Нет заявления об универсальной
защите любого Docker host или нового профиля. Native stop/revoke/freeze проверены
по реальным metadata/facts, включая отрицательные transport injections.
POSIX signal handling и asyncio cancellation допускают конечный cleanup;
SIGKILL/падение Docker daemon не покрываются graceful контрактом. Adapter зависит
от приватного buffered IO метода Harbor 0.24.0; upgrade требует regression и
реальных controls. Native n8n execution ID по-прежнему недоступен (ARCHITECTURE “Artifact and Replay interfaces”); replay IDs/log refs связывают исполнение.

У T1 остаются score=null/verdict=unknown и reward_status=incomplete, поэтому
aggregate report completeness=partial даже при полностью известных criteria.
Это ожидаемое отсутствие утверждённой методики, а не незакрытый технический
контроль. WB-06 должен утвердить методику и конечные модельные лимиты; Codex
эксперимент дополнительно требует отдельного разрешения. Model calls — 0.

### Финальный review

**Standards:** незакрытых findings — 0. Проверены весь source/test diff,
дублирование, ownership, portability, cleanup и отсутствие новых dependencies.
Исправлены найденные deadline/subprocess cleanup и потеря исходного process status.

**Spec:** незакрытых findings — 0. Все строки исходной матрицы имеют подтверждённый
контроль; native Harbor/n8n путь и Task-owned business checks сохранены. Нет
нового scoring, второго orchestrator/verifier, UI, T2–T4 или model runs.

Итог по осям: Standards — 0, Spec — 0; незакрытых критических findings нет.
HEAD остался исходным; commit/push не выполнялись.
