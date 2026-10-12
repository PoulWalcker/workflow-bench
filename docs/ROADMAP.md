# Workflow Bench — roadmap

Status as of 12 October 2026. [SPEC](SPEC.md) owns product scope and methodology;
[ARCHITECTURE](ARCHITECTURE.md) owns interfaces; [README](../README.md) provides setup
and control commands. This roadmap describes capabilities and remaining work.

## Current capabilities

| Area | Status and limits |
|---|---|
| Task definition | Native Task loading, public export, path/disclosure validation and a synthetic Task without registration are implemented. |
| T1 — Telegram API automation | Manual unchanged native n8n workflows run through Harbor on fresh cases, with protected Evidence and independent evaluation. T1 measurement includes development/final separation, selection, feedback and task-owned scoring. |
| Lifecycle and trust | Model-free controls cover isolation, forbidden access, evidence protection, lost responses, timeout/cancel, confirmed stop and owned cleanup. |
| Stock Codex | Exploration, submission and successful T1 development/final evaluation have been demonstrated with ChatGPT authentication. API-billed execution remains closed without verified external spending enforcement. |
| Sapiens | Host/CLI integration, model-free lifecycle controls and live native artifact generation are demonstrated. Successful T1 evaluation remains blocked by a generated n8n expression failure; partial evaluation prevents correction/private final under the current policy. |
| SimsApp UI | Bounded navigation/search/open/history, focus, exact draft replacement and atomic Send are implemented with protected observation/transition facts. Model-free controls cover effects, lost response and stop behavior. |
| SimsApp AX projection | Implemented and checked against sanitized Blindly references: native AX hierarchy, variable contact/result/history fragments and explicit reconstructed interaction annotations. Fast fidelity/behavior checks and all 10 distinct model-free Harbor controls pass; T1 regressions pass. One-result layout, direct result opening and menu Send effects remain reconstructed; native WhatsApp compatibility is unproven. |

Implemented UI actions do not establish a complete T2 benchmark, NAV results or
native UI workflow replay. Controls establish the tested behavior and environment;
they do not prove general model reliability or savings.

## Product direction and scope reconciliation

The next direction is T2 — SimsApp UI Automation: find the intended conversation
through UI and send the exact supplied text once, with explicit no-send behavior
for missing or ambiguous recipients and independent protected verification. T1
remains the existing Telegram API benchmark. Telegram conditional reply/forwarding
and its broader UI expansion are deferred for the next implementation phase.

The broader T1–T4, single-Telegram release requirements in
[SPEC §2](SPEC.md#2-mvp-scope) and [§12](SPEC.md#12-first-release-acceptance) still
require reconciliation with this direction. The bounded SimsApp environment is an
accepted exception, not approval of a new release definition. Remaining decisions
include T2 contracts/scoring, online navigation methodology, map delivery and
measurement, Sapiens progression, Judge obligations and revised release gates.
MVP readiness is not established.

## Planned work and dependencies

| Work | Dependencies and acceptance |
|---|---|
| T2 cases and verifier | Agree business/UI contracts, case sets, rubric and disclosure policy. Prove positive and negative controls from protected Evidence, including missing/ambiguous recipients, exact text, duplicates and unrelated changes. |
| NAV-1 / NAV-2 comparison | Requires T2 verification, agreed map delivery and frozen measurement policy. Compare the same agent/tools on UI V1 without and with a reusable map prepared before evaluation; account for map preparation separately. |
| NAV-3 and NAV-1 on V2 | Requires a frozen V1 map and controlled V2 with a model-free reachability control. Compare the unchanged old map against a mandatory V2 baseline without a map; report recovery costs without supplying V2 repairs. |
| Native SimsApp compatibility | Independent technical experiment through Harbor/n8n and the verifier. Early navigation probes can precede full T2; full business controls require T2 cases/verifier. Preserve a minimal reproducible blocker before proposing contract extensions. |
| Candidate-failure continuation | Requires an approved policy distinguishing trustworthy candidate failures from infrastructure/unknown outcomes. Preserve partial/null scores, finite Attempt limits and complete-development final gating; no automatic retry is currently authorized. |
| Full flow and reporting | Reconcile scope, then integrate the agreed Tasks, corrections, selection-before-final and separate creation/replay/Judge/setup costs. |
| Independence and Judge | Reconcile release obligations. Prove Task-directory-only expansion and a small app through real controls. Judge needs justified semantic criteria, a labeled suitability set and failure controls before scoring. |

NAV conditions are online agent episodes, separate from native workflow Replay.
They preserve the same T2 objective, state, agent, tools and limits across paired
conditions. Native feasibility does not gate NAV, and NAV does not authorize an
online LLM inside accepted Replay. Model execution requires separate authorization
and finite limits; planned work is not an implementation assignment.

## Acceptance gates

| Gate | Status |
|---|---|
| E1 — lifecycle and trust | Established for the tested native T1 environment and controls. |
| E2 — stock Codex | Successful T1 exploration/submission/evaluation demonstrated. Model-free wiring alone does not satisfy this gate. |
| E3 — Sapiens | Blocked: genuine artifact generation is demonstrated, successful T1 evaluation is not. Progression consequences require an owner decision. |
| E4 — expressiveness and independence | Incomplete; Telegram expansion is deferred and proposed SimsApp acceptance needs scope reconciliation, native compatibility and independence controls. NAV completion does not satisfy native E4. |
| E5 — semantic Judge suitability | Pending applicability/support decision and justified criteria; neither success nor inapplicability is established. |

All required real checks need the actual environment. Missing Docker, credentials
or authorized budgets cannot be treated as successful verification. Low model
scores do not justify weaker checks, hidden candidate repairs or additional calls
outside the agreed limits. See [SPEC §13](SPEC.md#13-decisions-still-required) for
decision ownership and deadlines.
