# WB-07 — первый T1/Codex эксперимент, E2

Статус: **DONE, E2 подтверждён**. После focused review и отдельно разрешённого
повтора живой Codex подтвердил MCP exploration и получил **10/pass/complete**
с первой Attempt: 5/5 development + 5/5 private final, native reward 10.0,
confirmed stop/cleanup. Исходный HTTP-exploration result/evidence сохранён.
Прежний API spending gate ниже остаётся историей Phase A; текущий выбор auth
и результаты описаны в следующем разделе.
План обновлён 12 октября 2026 года; основание — HEAD
`d6b65b0a2c4ce85d3f01673818b31c1d2609aef9` и [WB-06](WB-06-t1-measurement.md).
Первоначальное поручение: реализовать обе фазы в пределах доступных safety gates,
без commit/push. Подготовка Phase A не требует разрешения на модельный запуск.

## Live MCP completion · 12 октября 2026

После вопроса о необходимости live проверки владелец отдельно разрешил повтор.
Новый run — `runs/wb07-live-mcp-t1-20261012-active/report.json`; audit —
`runs/wb07-completion-review/live-audit.json`. Model — прежний `gpt-6.1-sol`,
low reasoning / Codex 0.118.0 / Harbor 0.24.0 / ChatGPT subscription auth.
Конечные limits прежние: 300 s/40 exploration calls на Attempt, максимум две
Attempt, 2400 s run. Фактически **одна Attempt**, correction не понадобилась.

**Actual MCP:** original native session нового run
`attempt-1/creation/harbor/wb-submission-b5bdabd659464e338d48e18cceaa2319/agent/sessions/2026/10/12/`
содержит function calls на строках **23, 27, 87**: `mcp__tools__get_chat`,
`mcp__tools__list_messages`, `mcp__tools__list_messages`. Native `codex.txt`
подтверждает три completed calls без MCP error. Call IDs всех трёх responses
сопоставлены с protected simulator events. Protected exploration: 7 accepted
simulator operations total, complete freeze, pending/violations пусты. MCP
использован для наблюдений; модель также проверяла candidate через разрешённый
HTTP. Exclusive MCP не является новым business criterion или scoring бонусом.

Submitted/selected artifact SHA256 —
`365dbb6c700cd89fa6b4113fe18191875710e4f31836090e220fbc9b444e1f31`.
Он неизменен между collection, acceptance, development и final; manual repair нет.
Selection `first_development_pass` записана до final. Frozen development/final
sets, order, rubric hashes и человеческая instruction совпадают с исходным run.
**5/5 development pass/complete, 5/5 final, score=10/pass/complete**; host
`read_evidence`/aggregate сверены со всеми protected identities/hashes и parsed
native reward `{"reward": 10.0}`. Это повтор того же frozen набора в свежих мирах,
а не новый независимый holdout sample или доказательство общей надёжности.

Creation 235.65 s включая setup/collection, **615062 input / 4109 output tokens**;
native model-call count/USD остаются null, Judge calls=0. Account allowance до/после
26% used (shared/rounded metric, не доказательство нулевого расхода). Live account
check выполнен; неизвестные метрики не превращены в нули или фиктивную цену.

Isolation checks passed, protected-control probe blocked, network allowlist
сохранён. Auth copy доступна только Composer (его shell может её прочитать,
прежний принятый tradeoff); Replay/verifier не получают model auth. Текущие native
host token values не найдены в saved run; этот scan не исключает иные historical
values. Composer и все 10 runtime stops confirmed; cleanup errors/residuals пусты.
13 owned Docker project labels дополнительно проверены: containers/networks/
volumes отсутствуют. Все **276 original source/evidence файлов** после повтора
сохраняют прежние hashes. Original report/reassessment не переписаны.

Первый start `runs/wb07-live-mcp-t1-20261012/` был model-free setup failure
из-за отсутствующего original Replay digest, до Attempt/model call. Для active
run использованы rebuilt app/Composer images после packaging fix; tools profile
побайтно совпадает с original. Новый runtime digest — изменение integration
условий, явно сохранённое в config/manifests; Task/workflow logic/cases/rubric/
scoring для получения успеха не менялись. Technical launcher взят из уже проверенной
reassessment copy с исправленным state-schema path.

**WB-07 DONE:** actual live MCP exploration, genuine stopped submission, unchanged
selected artifact на 5+5, independent Evaluation/reward и isolation/lifecycle
подтверждены. Дополнительный paid run для закрытия WB-07 не нужен. API-billed mode
по-прежнему закрыт без verified external cap. Следующий milestone — WB-08 Sapiens
с отдельным разрешением/limits. Commit/push не выполнялись.

## Live Phase B · 12 октября 2026

Владелец разрешил существующий ChatGPT Codex allowance вместо API billing gate,
native Harbor auth и максимум две Attempt. Выбран `gpt-6.1-sol`, low reasoning,
Harbor 0.24.0 / Composer Codex 0.118.0; host account reader — Codex 0.162.1.
Конфигурация — `runs/wb07-live-implementation/live-config.json`: 300 s Composer,
40 exploration calls на Attempt, 2400 s общий run, прежние Replay/resource limits.
Live account limits проверяются до/после Attempt; account usage изменился с 25%
на 26% недельного окна (shared account, не точная атрибуция расхода этому run).
Новых API credentials, spending gateway или custom bridge нет.

Использован штатный `CODEX_AUTH_JSON_PATH`: один auth-файл копируется в чистый
Composer home. Composer shell может прочитать эту копию — явный принятый tradeoff.
Personal home не смонтирован; credential не передаётся Replay/verifier. Штатный
Harbor network allowlist ограничивает Composer provider/exploration адресами;
private-control и unrelated-egress probes прошли. Auth tokens не обнаружены в
сохранённых artifacts/logs. CLI требует `--authorize-model` и `--codex-auth`.
API-billed mode без проверенного cap остаётся закрытым.

Connectivity: `runs/wb07-live-connectivity-19a87f48/connectivity.json` — настоящий
ответ `WB_CONNECTIVITY_OK`, 27089 input / 8 output tokens, confirmed stop. Более
ранний local permission failure сохранён в `runs/wb07-live-connectivity-a4738f88/`;
session не записана. Начальный T1 setup в `runs/wb07-live-t1-20261012-first/`
не создал Attempt: старый app digest отсутствовал. Использован доступный prepared
digest из `runs/wb07-phase-a-fixes-images-v4/config.json`, без изменения simApp.

Реальный run — `runs/wb07-live-t1-20261012-active/`, **одна Codex Attempt**.
Оригинал — `attempt-1/creation/harbor/wb-submission-762e479d59aa40a5a4b6d48b2eaaea80/artifacts/work/workflow.json`;
SHA256 `4d48c9bd1feab3c96e96053218242c556461cfa6cefc89f5134693da1b119392`.
Creation — 533712 input (490368 cached), 4211 output tokens, 5 simulator calls,
217.02 s включая setup/collection; native model-call count и USD остаются null.
Account allowance — enforcement source; токены не преобразованы в фиктивную цену.

Все пять development Replay исполнены. Старый frozen WB-06 `test.sh` ссылался на
`/app/telegram/state.schema.json`; текущий image использует `/bench/state.schema.json`.
Изначальный report с unavailable/unknown сохранён. В отдельной reassessment
переиспользован текущий repository launcher, тот же verifier и **сохранённые frozen
Evidence**, без повторных development Replay/model calls и без изменения Task intent,
Case, rubric/scoring или workflow. Development: **5/5 pass/complete**. Existing
`select_attempts` выбрал первый pass; selection записан до private final.

Итог — `verifier-reassessment/report.json` и `verifier-reassessment/final/report.json`:
**5/5 private final, score=10, verdict=pass, completeness=complete**, native reward
`{"reward": 10.0}`; artifact hash неизменен. Stop/cleanup подтверждены, residual
resources/cleanup errors пусты. Второй Attempt и дополнительные model experiments
не выполнялись. Воспроизведение technical recovery сохранено в ignored
`runs/wb07-live-implementation/reassess.py`; исходный failed report не переписан.

**Ограничение исходного run (устранено отдельным live повтором выше):** Codex самостоятельно исследовал simulator прямыми HTTP calls;
native MCP config передан, но MCP tool calls в trajectory не установлены.
Эти факты не подтверждали MCP exploration и тогда оставляли WB-07 IN PROGRESS. Codex 0.118.0
также записал nonfatal model-catalog decode errors (`max` reasoning enum); их нельзя
приписывать AI business performance. Успешный business Evaluation не скрывает эти
harness limitations. Fast suite — 286 passed; Ruff check/format и diff-check — exit 0.
Commit/push не выполнялись.

## Focused completion review · 12 октября 2026

Проверка исходного run завершена без model calls/Replay. Evidence review —
`runs/wb07-completion-review/audit.json`; исходные 276 файлов не изменены.

- Original session JSONL содержит 15 `exec_command`, **0 MCP tool calls**.
  Protected exploration подтверждает 5 разрешённых HTTP операций (2 get_chat,
  2 list_messages, 1 send_message), ещё 5 запросов отклонены. Freeze complete,
  pending/violations пусты. MCP config был передан, но это не означает discovery.
- Причина воспроизведена настоящим pinned Codex 0.118.0 в offline container с
  локальным HTTP responder: MCP child не наследует `PYTHONPATH`, поэтому
  `python -m workflow_bench.mcp` завершается `ModuleNotFoundError`. Optional MCP
  startup позволял продолжить без этих tools. Inert control наследовал ambient
  environment и не обнаруживал дефект. `native-red.log` сохраняет воспроизведение;
  `required=true` использовался только как диагностический probe.
- Минимальный fix — image builder публикует `/app` через Python site `.pth`,
  вместо ambient `PYTHONPATH`. Native config/adapter/CLI version не меняются.
  Regression `test_packaged_mcp_discovery_without_ambient_pythonpath` сначала
  failed на старом image, затем passed на новом. Настоящий Codex в том же offline
  probe теперь включает `mcp__tools__get_chat`, `list_messages`, `send_message`
  в provider request (`native-green.log`); HTTP 501 от responder намеренный,
  model turn/реальная exploration этим не доказаны. Технический handoff явно
  указывает tools MCP для exploration; человеческий Task intent не изменён.
- Все 8 collected/accepted workflow copies имеют original SHA256
  `4d48c9bd1feab3c96e96053218242c556461cfa6cefc89f5134693da1b119392`.
  Все 18 staged development inputs побайтно равны original: Case, execution,
  frozen Evidence, rubric, index/purpose. Frozen Task intent/public contract,
  development/final sets, rubric и `verify.py` равны reassessment copies; manifest
  hashes совпадают. Только `test.sh` заменил obsolete state-schema path.
  Real `read_evidence` подтвердил identities/hashes/freeze всех 10 Case;
  real aggregator сверён с сохранёнными Evaluation/native reward 10.0.
  Повтор оригинального verifier локально на saved inputs дал побайтно эквивалентные
  JSON values для development/final. Reassessment не делал development Replay;
  private final были пятью свежими Replay после сохранённой selection.
- Original `isolation.json` подтверждает blocked protected-control probe;
  сохранённый network policy ограничивает egress provider/simulator. Native auth
  передан только Composer; Replay compose не содержит model auth, personal home
  не смонтирован (успешные runtime setup checks). Composer shell мог читать свою
  auth copy — прежний принятый tradeoff. Текущие native token values не найдены
  в сохранённом original run; такой scan не исключает другие historical tokens.
  10 runtime stop records и Composer stop confirmed, cleanup errors/residuals
  пусты; дополнительно проверены 15 original Docker project labels — owned
  containers/networks/volumes отсутствуют. Exploration capability file удалён.
- Rebuilt image/config — `runs/wb07-completion-review/images/`; prepared future
  config `next-live-config.json` сохраняет model/resource limits. При следующем
  setup обнаружено отсутствие original Replay image digest; до model calls
  старт остановлен (`runs/wb07-live-mcp-t1-20261012/`, no Attempt). Для нового
  run выбраны rebuilt app/Composer digests; exported tool profile побайтно равен
  original (SHA256 `164347f6011e201c51eceaf5188cdf345c05ea47663d676ba1b82849e2533a53`).
  Original config/evidence не переписаны.
  Fast suite: 286 passed; targeted Docker regression: 1 passed;
  Ruff check/format и diff-check: exit 0.

**Открытый пункт на момент review:** после fix требовалась отдельно разрешённая live проверка actual
Codex MCP exploration в native JSONL, с прежними isolation/stop/cleanup gates.
Original 10/pass/complete остаётся подтверждённым HTTP-exploration результатом;
model-free discovery нельзя подменить им или объявить live MCP успехом.
Владелец затем отдельно разрешил новый live T1 с прежними конечными limits;
его результат будет записан отдельно, без переписывания original observation.

## Цель и границы

Как можно раньше безопасно выполнить один реальный эксперимент: штатный Codex
adapter Harbor 0.24.0 исследует учебный Telegram, сдаёт reusable native n8n
`workflow.json`, существующий WB-06 путь оценивает его на свежих T1 Case.

Сохранить Task-first и Definition → Experiment → Evaluation, прежний public
export и человеческий `instruction.md` побайтно. Методика, две Attempt,
development feedback, selection до private holdout и scoring остаются
[в WB-06](WB-06-t1-measurement.md); здесь их не переопределять. Judge/runtime LLM
не нужны. Границы доверия и lifecycle — [ARCHITECTURE §3–6](../../ARCHITECTURE.md),
разработка и тестирование — [Engineering rules](../../AGENTS.md).
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

Предлагаемые seams согласовать перед coding по AGENTS “Behavioral TDD”. Добавлять проверки
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

## Реализация и evidence · 12 октября 2026 года

`composer.submit_codex` получает одну сдачу через штатный Codex adapter и native
Trial. `run_measurement(submit=...)` использует прежние приём, selection, feedback,
development и final. `mcp.py` переводит stdio JSON-RPC в существующий HTTP contract;
state, scope, лимит и журнал принадлежат simulator. Новые доменные сущности,
frameworks и Python-зависимости не добавлены. Три seams подтверждены пользователем.

Builder с `--codex-version 0.118.0` собрал digest-pinned app/Composer images;
Harbor 0.24.0, n8n/runner 2.41.5, Docker 29.4.0 / Compose 5.1.2, OrbStack.
Model-free config допускает только synthetic credential и локальный provider stub.
Composer/provider подключены к internal Docker network без host ports;
реальные provider endpoints недоступны. Public export прежний, business instruction
не изменён; техническая native инструкция лишь указывает публичный каталог и
путь сдачи. Private Task, verifier input и control credential не передаются Composer.

Timeout/cancel probe воспроизвёл дефект lifecycle: убийство host `docker exec`
оставляло child writer живым во время `finally` штатного adapter; стандартный
Docker stop grace дополнительно позволял позднюю запись. В существующем
`DeadlineDockerEnvironment` collector при отмене сначала закрывает tools и
останавливает Composer, затем завершает host process/collector. Composer имеет
stop grace 1 s. Отдельные реальные timeout/cancel контроли прошли: 2 passed,
51.14 s (`runs/wb07-a-lifecycle-fifth.log`). Предыдущие неуспешные прогоны сохранены.

Первый полный инертный контроль получил 5/5 development и 5/5 private final,
score=10/pass/complete: 1 passed, 424.56 s (`runs/wb07-a-seventh.log`). Это
контрольный файл, а не результат модели. Подтверждающий прогон дополнительно
проверяет parseable native JSON и блокирование реально слушающего private host
endpoint: `runs/wb07-a-confirm.log`, 3 passed, 462.40 s (включая timeout/cancel).
Повтор итогового diff проверяет также сводные нулевые model calls и наличие
обоих services при inspection: `runs/wb07-a-reviewed.log`, 3 passed, 462.38 s.
Facts — `runs/wb07-a-reviewed/`: 5+5 pass, score=10, native reward=10.0,
model_calls=0, tokens/USD=null, selection до final, stop/cleanup подтверждены.

Настоящий pinned Codex CLI также запущен **только против локального stub**:
`runs/wb07-native-codex-stub-second/`. Provider вернул HTTP 501, native adapter —
`NonZeroAgentExitCodeError`; workflow отсутствует, одна Attempt, дальнейший шаг
blocked, stop подтверждён. Это сохранённый неуспех wiring probe, не model experiment
и не подтверждение reasoning/MCP модели. Первый probe setup также сохранён отдельно.
Harbor scrubbing заменял литерал `false`, принимая AUTH flag за секрет; передача
логически эквивалентного `False` сохраняет native JSON. Adapter не скопирован.

Usage collector сохраняет raw session refs и последнее cumulative total одной
сессии, не складывает повторяющиеся totals. Missing/ambiguous/malformed usage =
null; calls неизвестны, USD возможен только при известных input/cache/output и
явных конечных ценах. Model-free calls=0 подтверждены изолированной сетью;
null token metrics не берутся из Harbor `or 0`. Неизвестный остаток creation budget
блокирует следующую Attempt. Native timing refs и stop/cleanup сохраняются отдельно.

**Phase B остаётся закрытой:** конкретные model/budget не авторизованы,
независимый cap выделенного provider project/credential и остаток не проверены;
enforceable calls/token quotas не подтверждены. Проверенный config не является
доказательством cap: `--codex` отклоняет model mode до setup/credentials, даже
`authorized=True` в программном preflight не обходит отсутствие enforcement.
Нет оплаченных вызовов, реального AI workflow и E2 результата. Для продолжения
нужны отдельная конкретная авторизация и проверенный внешний spending constraint,
согласование доступных quotas; budget gateway/ledger не реализован.

Команды воспроизведения — [README](../../README.md#verified-docker-controls).
Output/config/basetemp должны быть новыми; факты и failed/unknown outcomes
сохраняются в игнорируемом `runs/`, не перезаписываются успешным результатом.

Fast suite итогового diff: 264 passed, 25.81 s
(`runs/wb07-fast-final-confirmed.log`). Malformed enum config сначала воспроизвёл
TypeError (2 failed в `runs/wb07-config-red.log`), затем безопасный preflight
отказ подтвердился focused test. T1 instruction/rules/scoring, Python dependency
set и lock не менялись. Полный diff проверяется также на responsibility boundaries,
portability, test independence, лишние abstractions, секреты и посторонние изменения;
пользовательские staged ZIP, отдельный audit document и параллельная редакция
основных документов не входят в эту работу и сохранены.

WB-04/05 regression command из README: 58 passed, 1115.29 s
(`runs/wb07-regressions.log`). После последнего collector fix дополнительно
проверены lifecycle/collection: 12 passed, 284.77 s
(`runs/wb07-lifecycle-reviewed.log`).
WB-06 manual measurement: 1 passed, 394.63 s
(`runs/wb07-manual-regression.log`): прежний unchanged workflow,
5/5 development + 5/5 private final, score=10/pass/complete, native reward=10.0.
В `runs/wb07-manual-regression-config.json` только технический total deadline
явно увеличен до 1800 s, как в прежнем WB-06 контроле.

Review regression unknown budget сначала разрешила две Attempt при строке
`"unknown"` (1 failed в `runs/wb07-budget-known-red.log`); green принимает лишь
явный boolean True. Malformed UTF-8 native session сначала прерывала сбор
метрик (`runs/wb07-usage-red.log`); теперь raw ref сохраняется, usage остаётся null.

Ruff check и format --check для `src tests simapps environments tasks` — exit 0
(`runs/wb07-ruff-final-confirmed.log`, `runs/wb07-ruff-format-final-confirmed.log`,
40 files formatted). Scoped implementation diff
проверен полностью: дополнительных Python dependencies/lock changes, business
ветвлений в core, второго Trial/n8n runtime, машинных путей или API key literals
нет. Synthetic fixture/reference workflow остаются только в control image.
Collector patch ограничен доказанным cancellation дефектом pinned Harbor seam;
private-method coupling отмечено в ARCHITECTURE и покрыто контролями.
Проверка Git diff подтверждает неизменность `tasks`, `simapps/telegram`,
`pyproject.toml` и `uv.lock`; параллельные documentation edits сохранены.
Финальный Docker metadata audit по 237 сохранённым owned project IDs:
остаточных containers/networks/volumes нет (`runs/wb07-cleanup-audit.json`).
Чужие resources не удалялись. Не выполнены provider/account cap verification,
реальный model experiment и доказательство остановки remote computation.
Warnings успешных suites — upstream Harbor `Task.checksum` deprecation.
Ни commit, ни push не выполнялись.

## Recorded model-free commands

Moved from the former README; prerequisites and unused-output rules remain in README. The manual regression runtime total was explicitly 1800 s, not a model budget.

```sh
uv run --locked --offline python environments/build.py --output runs/wb07-codex-images/config.json --codex-version 0.118.0
```

```sh
uv run --locked --offline python -m workflow_bench.cli --codex --config runs/wb07-codex-images/codex-config.json --task runs/wb06-task-first-correction/task --output runs/wb07-native-codex-stub-second
```

```sh
uv run --locked --offline pytest -q tests/integration/test_codex.py --run-integration --e1-config runs/wb07-codex-images/config.json --measurement-task runs/wb06-task-first-correction/task --basetemp runs/wb07-a-confirm --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_manual.py tests/integration/test_trust.py tests/integration/test_delivery.py tests/integration/test_lifecycle.py tests/integration/test_isolation.py tests/integration/test_t1_evaluation.py --run-integration --e1-config runs/wb07-codex-images/config.json --basetemp runs/wb07-regressions --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_measurement.py --run-integration --e1-config runs/wb07-manual-regression-config.json --measurement-task runs/wb06-task-first-correction/task --basetemp runs/wb07-manual-regression --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_codex.py --run-integration --e1-config runs/wb07-codex-images/config.json --measurement-task runs/wb06-task-first-correction/task --basetemp runs/wb07-a-reviewed --log-cli-level=INFO
uv run --locked --offline pytest -q tests/integration/test_lifecycle.py tests/integration/test_delivery.py --run-integration --e1-config runs/wb07-codex-images/config.json --basetemp runs/wb07-lifecycle-reviewed --log-cli-level=INFO
uv run --locked --offline pytest -q
uv run --locked --offline ruff check src tests simapps environments tasks
uv run --locked --offline ruff format --check src tests simapps environments tasks
```

## Phase A — исправления независимого review (2026-10-12)

Проверен текущий working tree вместе с незакоммиченным WB-07. Применены
`codebase-design`, `domain-modeling`, `tdd`; повторный независимый review проверил
security/spec и engineering/architecture. Найденные им остаточные ошибки
(expiry после saturation, native trajectory fallback, cleanup persistence и
bounded result serialization) также исправлены. Phase B не запускалась; paid
mode остаётся закрытым. Model calls, commits и pushes не выполнялись.

| Finding | Статус | Минимальное исправление и подтверждение |
|---|---|---|
| Task-first / instruction | Fixed | Нейтральный MCP `tools`, handoff через stock Harbor template, неизменённый `instruction.md`; builder получает явный simApp, общие протокольные пути/имена ресурсов. Реальный inventory Composer → fresh Replay работает без Telegram/T1. |
| Unsafe session ingestion | Fixed | Bounded no-follow snapshots перед собственным и native Harbor parsing; candidate trajectory не используется для fallback. FIFO, links, oversized/malformed files и nonempty trajectory directory проверены; реальный Docker FIFO control завершился с unknown usage и confirmed stop. |
| SEC-1 / evidence flooding | Fixed | Journal ограничен лимитом wire contract; excess traffic отвергается без роста событий. Protected summaries сохраняют существующее unauthorized-send нарушение. Flooded native workflow остаётся `fail / duplicate_send`; новое critical criterion или штраф не введены. |
| SEC-3 / state lock | Fixed | Request reads и response transport вне lock; admission повторно проверяется, freeze сохраняет pending stage без двойного effect/late changes. Slow-body/slow-response regressions green. |
| SEC-2 / n8n result | Fixed | Candidate stdout/stderr не разбираются как result. Отдельный trusted process читает единственную matching execution свежей native SQLite; bounded input/serialization/output, native execution ID. Forged/missing/array/oversized controls сохраняют unknown claim; реальные native positive/negative controls green. |
| Primary errors | Fixed | Cleanup/export/log failures не заменяют исходную cancellation/exception. Реальная остановка собственного simulator во время cancellation сохраняет `cancelled`, cleanup без residuals; persistence fault tests green. |
| Protected control probe | Fixed | Проверяется inspected management IP + configured port из Composer main/provider и replay/runner; HTTP 403 также означает доступность. Реальный inventory control использует 8189, reachability false. |
| SEC-4 / shared host root | Disproven as current exposure | Общий закрытый host root сам по себе не даёт sandbox доступ. Composer получает allowlisted upload; mount inspection запрещает посторонние host mounts, replay не имеет bind mounts. Private/home/credential controls проверяют реальные поверхности. Новое разделение корней не требуется для подтверждённой границы. |

Протокольные `/work/workflow.json`, BenchInput/BenchResult, schema versions,
container service names, pinned native dependency paths и journal limits сохранены:
это действующие контракты, а не business assumptions. T1 instruction, public data,
development/final inputs и rubric frozen copy побайтно совпадают с предыдущим
контролем; изменена только техническая доставка/schema path и чтение защищённого
summary для уже существующего unauthorized-send критерия. `pyproject.toml` и
`uv.lock` не изменены.

Подтверждённые проверки (без моделей):

- Default `.venv/bin/python -m pytest -q -p no:cacheprovider`: **282 passed**.
- Fast + explicit T1 verifier integration: **311 passed**.
- Ruff check и format --check (`src tests simapps environments tasks`): exit 0;
  `git diff --check`: exit 0.
- Native inert Composer 5 development + 5 final и manual T1: **2 passed**,
  `runs/wb07-phase-a-measurement-control`; development/final `pass`, final score 10,
  native reward проверен, cleanup_errors/residual_resources пусты.
- Native flooding + прежние negative controls: **6 passed**,
  `runs/wb07-phase-a-flood-controls`.
- Primary cancellation + failed protected export: **1 passed**,
  `runs/wb07-phase-a-export-green` (red reproduction сохранён отдельно).
- Independent inventory app, normal submission и native session/trajectory FIFO:
  **2 passed**, `runs/wb07-phase-a-inventory-confirm`; fresh Replay использует новый
  input/world, instruction unchanged и фактический control port 8189.
- Финальный inventory Replay через `read_evidence` / FrozenEvidence: **1 passed**,
  `runs/wb07-phase-a-inventory-evidence`; native SQLite result и evidence validation
  проверены вместе на окончательном исходном коде.

Для повторения используйте новые owned output/basetemp. Builder теперь требует
`--simapp simapps/telegram` для T1 или
`--simapp tests/integration/fixtures/inventory/simapp` для synthetic fixture.
Последние конфигурации: `runs/wb07-phase-a-fixes-images-v4/config.json` и
`runs/wb07-inventory-fixture-images-v2/config.json`. Failed pre-fix controls сохранены
как evidence; они не считаются успешной проверкой.

Оставшиеся ограничения: session guard и SQLite collector привязаны к закреплённым
Harbor/n8n версиям и требуют повторных реальных controls при обновлении. Эти проверки
доказывают wiring/isolation/lifecycle и независимую Evaluation, не качество reasoning
реальной модели и не provider spending enforcement. WB-07/E2 не объявляется DONE.
