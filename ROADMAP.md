# Workflow Bench — roadmap

Status as of 12 October 2026. Dependencies require verified results, not files.
[SPEC](SPEC.md) owns scope/methodology; [ARCHITECTURE](ARCHITECTURE.md) owns interfaces;
[AGENTS](AGENTS.md) owns engineering rules. Tickets retain evidence and limitations.

## Milestones

| Milestone | Status | Depends on | Acceptance / transition |
|---|---|---|---|
| [WB-02 Bootstrap](docs/implementation/WB-02-bootstrap.md) | DONE | Assigned bootstrap | Reproducible Python/uv package, fast test gate, Ruff and verified setup; no future scaffolding. |
| [WB-03 Component boundaries](docs/implementation/WB-03-component-boundaries.md) | DONE | WB-02 | Native Task loading/public export, safe paths/disclosure and another synthetic Task without registration. |
| [WB-04 Native replay](docs/implementation/WB-04-e1-native-replay.md) | DONE | WB-03 | Manual unchanged T1 executes through real Harbor/n8n/JS runner on fresh inputs; protected facts reach independent verifier. |
| [WB-05 Trust/failure controls](docs/implementation/WB-05-e1-trust-and-failures.md) | DONE | WB-04 | E1 negative matrix completed: private/file/network/evidence/reward attacks, lost response, unknown, timeout/cancel and owned cleanup, including actual processes/metadata. |
| [WB-06 T1 measurement](docs/implementation/WB-06-t1-measurement.md) | DONE for accepted ChatGPT-auth E2 | WB-05 | Approved T1 policy/sets/scoring/selection/feedback verified with manual/negative controls; finite limits/native allowance approved and verified in WB-07. API-billed mode remains closed without verified external cap. |
| [WB-07 Codex, E2](docs/implementation/WB-07-codex-e2.md) | DONE | WB-06 method; permission + auth-appropriate enforced limits | Separately authorized live repeat after MCP packaging fix: native JSONL confirms 3 actual MCP calls; one genuine submission passed 5/5 development and 5/5 private final with unchanged frozen policy, score=10/pass/complete, native reward=10.0. Isolation/stop/cleanup verified; original artifact/frozen reassessment preserved. |
| [WB-08 Sapiens, E3](docs/implementation/WB-08-sapiens-spike.md) | Spike verified including live generation; E3 blocked by generated n8n expression failure | Successful E2; separate permission/limits | Model-free native 5+5 and lifecycle controls passed. Authorized 600 s repeat completed in 455 s with a genuine valid native-collected artifact and four admitted MCP calls. All five development cases failed on `jsonBody` invalid syntax; partial/unavailable result blocked retry/private final. T1 success remains unconfirmed; owner decision required. |
| WB-09 Expansion methodology | TODO | WB-08 result; owner decision if blocked | Agree public UI identity/tree/stale-handle/search/draft/effect rules, T3 branches, T4 provenance/search/bounds and T2–T4 sets/rubrics/aggregation before cases or measurement. |
| WB-10 Shared UI/T2, E4 part | TODO | WB-09 | Real API-write/UI-read and reverse share state; fresh-tree native T2 works on new inputs/trees. Hardcoded paths/IDs, wrong recipients, duplicates and direct UI-only→API fail; unsupported actions explicit. |
| WB-11 T3/T4, E4 part | TODO | WB-10 | Immutable native controls cover T3 templates/no-input/processed and T4 0/1/N, equal-text distinct originals, pre-forwarded/empty/limit cases, sequential stateful UI; no business patches to binder/core or runtime LLM. |
| WB-12 Full flow/report | TODO | WB-11 + agreed methodology | Bounded sequential T1–T4 corrections, stop/feedback/selection-before-final, reset all state, task-owned score/Verdict/completeness and separate creation/replay/Judge/setup costs; deterministic failure controls and real replay prove the path. |
| WB-13 Judge, E5 if needed | TODO | WB-12 + justified-criterion decision | Separate context and validated values/refs; missing/malformed/injected data preserve programmatic facts/null scores; reassessment without Replay. Real authorized connection check; suitability on a pre-labeled set before semantic scoring, or explicit E5 inapplicability when no such criteria. Support remains required. |
| WB-14 Independence, E4 completion | TODO | WB-13 | Small Task on existing Telegram capabilities changes only its directory and passes positive/negative controls. Another small app fixture implements the same tools/control/evidence and real runtime path without core/Composer/n8n changes; not a fifth product Task. |
| WB-15 MVP acceptance | TODO | WB-14 + acceptance permissions/budgets | Evidence for every [SPEC §12](SPEC.md#12-first-release-acceptance) item, clean reproducible setup, real controls and bounded authorized model checks of remaining capabilities; failures/Sapiens blockers explicit and resolved by owner. |

## Gates

E1 = WB-04/05 lifecycle and trust; E2 = WB-07 stock Codex;
E3 = immediate WB-08 Sapiens; E4 = WB-10/11 expressiveness + WB-14 independence;
E5 = WB-13 semantic Judge suitability when needed. Technical E1 is recorded;
E2 is confirmed; E3–E5 and MVP readiness are not established. Model-free Codex wiring, controls or
a low-score AI result do not satisfy successful E2. No manual candidate repair or
extra calls beyond authorized limits to obtain DONE.

WB-07 Phase A required no model calls. WB-06's remaining budget gate is closed
for the accepted ChatGPT-auth E2 path; API-billed mode stays closed.
Phase B's recorded ChatGPT run used concrete owner authorization and live native
subscription allowance checks. API-billed runs still require verified external
spending enforcement; configuration assertions are insufficient. Numeric budget
proposals are not approval. The separately authorized live repeat after the packaging fix confirms actual MCP
exploration and the unchanged T1 evaluation path. API-billed mode remains closed.
UI/protocol extensions and remaining methodology use the owners/deadlines in
[SPEC §13](SPEC.md#13-decisions-still-required). A fundamental native-format failure
must preserve minimal JSON/fixtures/versions/error for the owner, not introduce a DSL.

Use native Harbor first; a custom verifier hook requires a reproducible insufficiency
and only one minimal alternative, never copied Trial/nested Harbor/new orchestrator.
Current E1 uses the native separate verifier. Later tickets are refined from evidence
within these milestone boundaries. Required real checks cannot be closed by mocks,
unavailable credentials/Docker or a successful reference in place of Composer.

## WB-17 implementation result

[WB-17 SimsApp navigation](docs/implementation/WB-17-simsapp-navigation-implementation.md):
**DONE — bounded navigation V1**, with protected Evidence, 5 real model-free Harbor
controls, 303 fast tests and 37 selected T1 regressions. Send, full T2, NAV/V2 and
WB-18–WB-22 implementation remain outside this slice.

## WB-18 implementation result

[WB-18 composer/Send](docs/implementation/WB-18-simsapp-composer-send-implementation.md):
**DONE — bounded SimsApp UI V1**, 311 fast tests, 10 real model-free controls,
3 final Send confirmations and 37 selected T1 compatibility checks. Atomic exact
message/draft transition, explicit errors/stale locators, lost response and pending
Send stop/freeze verified. No shared lifecycle/wire/T1 change; no T2 Cases/verifier,
NAV/Static App Model/V2, n8n extensions or model calls. Work stops after WB-18.
