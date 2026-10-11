# WB-07 — первый T1/Codex эксперимент, E2

Статус: **PLANNED**. Phase A — без моделей; Phase B — только после бюджетного gate.
План обновлён 12 октября 2026 года; основание — HEAD
`d6b65b0a2c4ce85d3f01673818b31c1d2609aef9` и [WB-06](WB-06-t1-measurement.md).
Текущее поручение: обновить только этот тикет, без реализации, тестов, моделей,
commit/push. Подготовка Phase A не требует разрешения на модельный запуск.

## Цель и границы

Как можно раньше безопасно выполнить один реальный эксперимент: штатный Codex
adapter Harbor 0.24.0 исследует учебный Telegram, сдаёт reusable native n8n
`workflow.json`, существующий WB-06 путь оценивает его на свежих T1 Case.

Сохранить Task-first и Definition → Experiment → Evaluation, прежний public
export и человеческий `instruction.md` побайтно. Методика, две Attempt,
development feedback, selection до private holdout и scoring остаются
[в WB-06](WB-06-t1-measurement.md); здесь их не переопределять. Judge/runtime LLM
не нужны. Границы доверия и lifecycle — [ARCHITECTURE §3–4, §10](../../ARCHITECTURE.md),
разработка и тестирование — [Principles](../../Principles.md) и [AGENTS](../../AGENTS.md).
Применяются codebase-design, domain-modeling и tdd; новые доменные сущности не нужны.

## Phase A — минимальная интеграция без model calls

В HEAD уже есть native Trial, stop/collection hooks, simulator HTTP tools,
приём артефакта и WB-06 measurement. Codex adapter поддерживает native config,
MCP и JSONL logs. Подключить эти возможности; не создавать второй orchestrator.

1. **Codex/Harbor.** В существующем `harbor.py` разрешить выбор штатного Codex
   и его config точкой сборки вместо жёсткого oracle. Закрепить CLI version/image,
   model/config и отключить resume, личные auth/config/skills и лишние tools.
   Использовать прежний `DeadlineDockerEnvironment`, hooks и collection.
   Изменять adapter только при воспроизводимом дефекте штатного пути, в его seam;
   agent loop, Composer HTTP bridge и копию Trial не писать.
2. **Exploration tools.** Добавить тонкий MCP transport над существующим HTTP
   tool contract. Публиковать операции из `tools.json`; авторизацию, счётчик,
   state и журнал оставить simulator. Admin tools не экспортировать. MCP и прямой
   HTTP используют одну exploration capability и общий лимит; записи не retry
   вслепую. Для каждой Attempt — свежий учебный мир из публичного example.
3. **Workspace и сдача.** Передать public export и путь `/work/workflow.json`
   в чистые workspace/home/Codex config/session storage. При исправлении добавить
   только предыдущий артефакт и разрешённый feedback. Приватные Task-файлы,
   checkout/home пользователя, Docker socket и чужие runs недоступны. Model
   credential передаётся только Composer; сеть допускает только simulator tools
   и выбранный provider. Переиспользовать существующий build/Compose; добавить
   pinned CLI/transport только где нужны. Новый image — лишь если существующее
   окружение не обеспечивает эти условия, без отдельного image framework.
4. **WB-06 и lifecycle.** Расширить существующий `run_measurement` получением
   одной сдачи на Attempt вместо только `ControlledSubmission`; controlled путь
   сохранить на том же цикле. Не вводить новую hierarchy источников/Composer.
   Harbor останавливает writer и MCP/children; затем прежний `accept_artifact`
   фиксирует файл/hash. Replay/verifier и `select_attempts` переиспользуются.
   Cancel/timeout закрывают tools, ограниченно drain/stop/cleanup только свои
   ресурсы; unknown outcome или unconfirmed stop блокируют продолжение без retry.

Предлагаемые seams согласовать перед coding по Principles §5. Добавлять проверки
только для нового поведения, по одному вертикальному срезу; существующие WB-05/06
контроли не дублировать. Моки — на внешнем process/transport, не в собственном
loader/binder/evaluator. В Phase A использовать synthetic credentials и локальный
provider stub, без доступа к настоящему модельному endpoint. Минимальные проверки:

| Interface / среда | Проверка и предел вывода |
|---|---|
| Config/preflight и measurement, fast | Нет разрешения/бюджета → отказ до credentials/setup; управляемая сдача проходит прежнюю policy; unknown не вызывает повтор; missing usage остаётся null. Не доказывает provider enforcement |
| MCP → simulator, без provider | Прочитать чат, пробно отправить и увидеть тот же эффект через HTTP; invalid/forbidden/limit не обходят server scope. Не доказывает работу модели |
| Harbor submission/lifecycle, opt-in Docker | Инертный внешний CLI process сдаёт файл; прежний replay/verifier его проверяет. Проверить private/credential/network isolation и timeout/cancel с child writer: нет поздних записей/эффектов, stop и cleanup подтверждены. Это проверка wiring/lifecycle, не реального Codex reasoning |

**Phase A готова**, когда этот путь и новые ограничения подтверждены без model
calls, controlled/manual regression сохранён. Отсутствие Docker/images при запросе
интеграционной проверки — blocker, не успешный skip. Model запуск остаётся отдельным
явным режимом; default pytest и collection его не запускают. Не создавать отдельную
model test framework или suite, если достаточно одного воспроизводимого CLI run.

## Gate перед Phase B — необходимая безопасность

Использовать существующие Harbor timeouts/resources, simulator capability limits
и provider spending controls. Один файл запуска содержит конечные лимиты по
[WB-06](WB-06-t1-measurement.md), версии и retry/config; численные предложения WB-06
ещё не утверждены. Бюджет общий для обеих Attempt и всех внутренних retries.

Обязательно до первого model call:

- Явное разрешение владельца на конкретные model/harness/config и конечные расходы.
- Проверенный внешний spending constraint для выделенного credential/project:
  cap и оставшийся объём, область учёта и отсутствие постороннего расхода известны.
  Constraint действует независимо от shell/Codex, включая прямые API calls;
  credential не может сам увеличить лимит. Alert и локальный timeout не заменяют cap.
- Конечные deadlines, resource/tool limits и способ остановки; calls/tokens и
  доступные native/provider ограничения записаны с честной областью enforcement.
  Если WB-06 предложение нельзя обеспечить или наблюдать, до запуска согласовать
  реально поддерживаемые quotas/ограничения, как предусмотрено WB-06. Не обещать
  hard per-call/token control по неполной телеметрии.

Документированную задержку provider enforcement и возможный небольшой перерасход
раскрыть владельцу при утверждении малого бюджета, предусмотреть запас. Не требовать
математического доказательства нулевого перерасхода или отмены уже принятого remote
вычисления. Нужен реально включённый независимый spending control, а не декларация
`finalized=true`/`enforcement` в config. Семантика — [официальные Spend limits](https://developers.openai.com/api/docs/guides/spend-limits).

**Блокеры сейчас:** нет утверждённых расходов/разрешения; внешний cap выбранного
credential/project не проверен; `model_preflight` только валидирует план и всегда
возвращает `execution_enabled=false`, `enforcement_verified=false`. Реальная
доступность calls/token controls выбранной CLI/provider также не подтверждена.
Это блокирует Phase B, а не model-free Phase A. Если независимый cap недоступен
или не верифицируется, записать конкретный provider/account/config и недостающую
возможность; реальный запуск оставить закрытым. Budget gateway/ledger не строить.

## Phase B — один разрешённый реальный эксперимент

1. После Phase A и gate зафиксировать приватную Task с прежними development/final,
   public export, profile/rubric/case hashes/order, pinned версии и утверждённый
   config. Выполнить один run с максимум двумя Attempt по WB-06, без дополнительных
   платных probes или попыток «до успеха».
2. Codex действительно исследует разрешённый simulator и сдаёт workflow через
   Harbor. На свежих Case прежний runtime/verifier оценивает неизменные байты;
   selection/feedback/holdout выполняет только существующий WB-06 цикл.
3. Сохранить report и ссылки на штатные Harbor JSONL/session usage, artifact,
   Evidence/Evaluation и stop. Creation обеих Attempt, replay и setup/cleanup
   раздельны; missing metrics = null, деньги только по сохранённым известным ценам.
   Не складывать повторяющиеся cumulative usage и не доверять Harbor `or 0`
   как доказательству нулевого расхода. Unknown model outcome не повторять;
   при неизвестном остатке не запускать вторую Attempt без подтверждения бюджета.

**Техническая интеграция подтверждена**, если реальный Codex получил tools,
исследовал simulator, сдал принятый файл, существующий evaluation путь вернул
честный результат и stop подтверждён. Score ниже 10 — результат AI, а не сам по
себе дефект интеграции. Missing/invalid файл, auth/tools/stop failure отражаются
как точные непрошедшие части пути; unknown не объявляется успехом.

**Успешный E2 и WB-07 DONE** по-прежнему требуют [ROADMAP](../../ROADMAP.md):
выбранный неизменный workflow проходит все пять свежих private final,
score=10/pass/complete, native reward сверён; exploration, isolation, metrics и
stop подтверждены. Готовая Phase A или технический успех с низким score этого
статуса не дают. При fail сохранить результат, без ручной починки и изменения
критериев; дальнейший model run требует нового разрешения/лимитов.

Воспроизводимость: lock/pinned images, явный config/private Task, новый output
на run, фактические команды/результаты и ограничения в игнорируемом `runs/`.
Использовать проверки из [README](../../README.md); новые команды записать после
их реализации и проверки. Перед завершением implementation проверить diff;
README/ARCHITECTURE/ROADMAP обновлять только по изменившимся подтверждённым фактам.
Sapiens, UI, Judge, WB-12 и инфраструктура будущих экспериментов здесь не нужны.
