# Workflow Bench — product specification

Current MVP requirements and accepted decisions. Implementation status belongs to
[ROADMAP](ROADMAP.md); technical contracts to [ARCHITECTURE](ARCHITECTURE.md).
Open decisions below do not reopen accepted scope or imply completed implementation.

## Terms

| Term | Meaning |
|---|---|
| Task | One business benchmark package: public intent/input contract, cases, checks, rubric and control. |
| Case | Prepared input, initial simulator state and private expected behavior for one check. Different versions may use it only from freshly restored state. |
| Attempt | One creation/correction ending in a submitted version or recorded submission failure. Manual control submission occupies the same position without being model generation. |
| WorkflowArtifact | Immutable submitted native n8n JSON. Technical binding does not create another business version or Attempt. |
| Replay | One execution of one version on one fresh Case. Multiple Replay are not multiple Attempt. |
| Harbor Trial | Harbor's agent/artifact/optional verification lifecycle unit. A submission Trial corresponds to an Attempt, not every Replay; technical completion does not mean Task success. |
| Evidence | Protected environment facts tied to version and Case: state and action history. Candidate claims and diagnostic logs do not prove effects. |
| Evaluation | Independent assessment of Evidence against Task criteria/rubric, producing criteria, completeness, score when available and Verdict. Reassessment of saved facts is not Replay. |
| Verdict | `pass`, `fail` or `unknown`, distinct from process status, score or a single effect. |
| input / state / expected | Request parameters available to workflow / simulator world observed through tools / private verifier expectations. A public training state does not expose private states. |
| Unknown | Insufficient knowledge of value/outcome. Zero means a known zero, not missing measurement. |

The current scope includes a bounded standalone Simulated SimsApp V1 UI environment
and model-free controls, described in [ARCHITECTURE](ARCHITECTURE.md).
This is a narrow exception to the single-Telegram scope and Sapiens progression
wording below: T1 stays compatible, E3 remains blocked, and the UI environment alone
does not complete T2 or revise release gates. SimsApp owns one business/UI state and
offers only current UI observations and elementary navigation, focus, replacement and Send
actions; tools never receive a Task target or private expected values. Send appends
one outgoing message with the active conversation's exact nonempty draft and clears
only that draft atomically, preserving focus. Unicode, whitespace and newlines are
preserved; no text deduplication or automatic write retry applies. Empty drafts
disable Send. Drafts persist per conversation; navigation preserves business state.
Task-specific draft permissions remain the verifier's responsibility.
UI observations use sanitized Blindly-derived AX templates. Native AX structure
and simulator-supported interactions are distinct: `simulation` explicitly labels
reconstructed actions and draft values. The preserved menu Send and direct result
navigation implement simulator behavior without claiming observed native draft/Send
effects or full WhatsApp compatibility. Fixture publication is not authorized by
runtime integration.
Cases/scoring, NAV/model experiments, UI V2 and native compatibility remain
planned work; current status and scope reconciliation are in [ROADMAP](ROADMAP.md).

## 1. Goal and limits of conclusions

Build a small research tool that tests whether AI can explore an environment and
create a workflow that solves the same business task on new inputs without changing
its logic. Prioritize correctness, then quality and measured costs. Composer's
one-off action cannot replace execution of its submitted artifact. Reducing
maintenance complexity is a project goal; file counts and candidate score do not
measure it.

The observation is one fixed version on one Case. Comparisons measure the complete
model + harness + settings + tools + budget combination, not pure model quality.
Tools and technical binding must not solve the business task for AI.

| Hypothesis | Observation and limit |
|---|---|
| H1: reuse | Unchanged workflow on new parameters/states. Training-only success does not establish transfer beyond tested cases. |
| H2: programmatic UI replay | Fresh-tree search/actions without runtime LLM navigation, within an agreed class of UI changes; no claim about arbitrary redesigns or real Telegram. |
| H3: tool choice | Correctness/cost under API+UI and, where comparable, access profiles. Availability proves neither combination nor optimal choice; T1 versus T3 does not isolate API/UI effects. |
| H4: corrections | Version results, feedback, attempts and total costs. Development improvement does not prove holdout improvement or lower total cost. |

Exploration alone does not prove its causal benefit, one successful run does not
prove general reliability, and virtual UI does not measure real server latency.
Report creation/execution costs; first-release readiness does not require a
one-off-agent baseline or demonstrated savings. Without a comparable baseline at
comparable quality, do not claim amortization. Comparing first/selected versions
on final data after selection remains optional, not an extra mandatory run series.

## 2. MVP scope

The first release includes **all T1–T4**, one simulated Telegram, API-only, UI-only
and API+UI access, virtual dynamic UI in a limited Blindly-style profile, active
exploration including trial actions, parameterized native workflows, reproducible
fresh cases, bounded sequential corrections, independent checks, score 0–10,
separate Verdict, justified semantic Judge support, costs and explainable reports.
Starting with T1 does not reduce the MVP to an API demo.

Excluded: real Telegram/accounts/keys/messages; physical desktop, screenshots or
coordinate control; runtime LLM generation/navigation; arbitrary world generation
or UI redesign; parallel solution search; holdout winner selection; other apps as
product benchmark Tasks; mandatory Static App Model; Sapiens YAML/Haskell workflow
notation; custom DSL/compiler, multiple execution backends, registry/scheduler,
large database/queue/dashboard/budget platform, migration of old evidence.
A small new Task/app fixture tests independence, not a fifth product Task.

## 3. Task independence

Task owns human business intent, input schema/example, cases, public rules,
permitted tools, checks, rubric, feedback disclosure and control. Environment owns
state, elementary observations/actions/errors and protected facts. Composer explores
and creates/corrects a workflow; Experiment runs the agreed policy; Evaluation
checks facts without executing/correcting the candidate.

Core knows no chat/recipient/reply/forward/inventory business semantics. A new Task
within existing contracts and app capabilities changes **only its directory**;
no core/common prompt/Composer/runtime/scoring changes or Task registry. A new app
supplies its simApp and Task; a new Composer supplies a Harbor agent integration
and configuration. New execution semantics require explicit contract expansion.

`instruction.md` is human intent and business constraints, not an algorithm or
UI path. Public contracts separately describe fields, tools/errors and artifact
submission; no natural-language parser is required. `task.json` supplies a public
input contract/example, not a solution or full private Case. Its feedback field
is disclosure policy, not precomputed feedback.

Keep input, state and expected separate. Composer receives a public training world;
simulator receives Case state; replay receives input and technical bindings and
learns state through tools; verifier receives expected and protected facts.

## 4. Business Tasks

| Task / access | Required result |
|---|---|
| T1 Send Message / API-only | Send the exact supplied text to the exact supplied recipient once, with no unrelated changes. The minimal profile uses an unambiguous chat ID; it tests sending, not identity search. |
| T2 UI Message / UI-only | The same sending behavior via fresh-tree observations and UI actions on new inputs and supported tree changes. Business-API bypass is forbidden. |
| T3 Conditional Reply / API+UI | Read the specified chat's latest incoming message, apply public conditions/templates, send the prescribed reply without duplicates or unrelated changes. Own outgoing messages are not incoming. |
| T4 Smart Forwarding / API+UI | Find keyword matches in specified chats and forward the appropriate originals to Saved Messages completely, with provenance and no duplicates. |

T1/T2 must refuse missing or unresolved ambiguous recipients according to public
rules; equal display names do not establish identity. Search Tasks require enough
public input/observations (e.g. unique username/context); never derive an ID from
expected or personal memory. Clarifying dialogue and universal identity resolution
are outside scope.

T3 must publicly define latest-incoming selection, template branches, no incoming
and already-processed behavior before cases are written. It tests rules, not free
text generation. T4 deduplicates by original chat/message, not text; pre-forwarded
objects may exist in Case state. Empty matches cause no fictional send; one version
handles 0/1/N within published limits. Keyword semantics, complete selection bounds
and over-limit behavior must be public before verification; pagination is required
only if included in the profile.

Cases distinguish parameterization from memorization: new IDs/text, T3 branches,
T4 cardinality/provenance, UI order/screen/draft changes. API+UI permits either
interface alone; API receives no automatic bonus. Forced complementary use remains
an optional proposed profile, not an MVP obligation or proof of free choice.

## 5. Simulated environment

All Telegram operations target our simulator. Writes change real simulator state;
reads return current permitted observations; unsupported actions/errors are explicit.
A constant success response without an effect is insufficient.

API and virtual UI share **one business state**. UI additionally exposes current
screen/chat, focus, search and draft: opening changes the tree, typing changes draft,
Send changes messages. Trees show the currently observable UI, not the entire DB,
private expected values or prepared solution selectors. Commands remain elementary; stateful UI actions execute sequentially.

Blindly denotes a limited virtual command profile, not native desktop execution or
full compatibility. Deterministic fresh-tree search/branching is permitted during
replay. Re-exploration and workflow changes occur only between Attempt. HTTP delivery
of UI commands is allowed; forbidden business/admin access violates UI-only.
MCP transport does not create a third app interface or mandatory app-level simMCP.

## 6. Composer and workflow

Codex Exec is first; **the same T1 through Sapiens CLI follows a successful T1/Codex
path, before full T2–T4**. Codex does not wait for Sapiens. A reproducible Sapiens
blocker must be recorded; the owner decides its consequences for progression/release.
Interchangeable contracts do not prove a working integration or equal metrics.

Composer receives public materials, training tools/data, finite limits and, on
correction, the prior artifact and permitted feedback. It may observe and try
training actions. Each independent run has clean memory/config/sessions; accepted
request, terminal result and confirmed stop are distinct. Harness planning stays
inside the harness; adapters add no hidden generation/correction loop.

Submit one fixed `workflow.json` or record explicit missing/invalid/failure/unknown.
A final message is not submission. One version executes on new inputs without logic
changes; binder substitutes only input/technical access data, never state/expected,
branches or answers. Reuse is within a Task/profile; one artifact for API-only and
UI-only is not required. Actual n8n execution is mandatory, not just format checking.

## 7. Experiment policy

Before measurement freeze Task, profile, case sets/order, criteria/rubric,
thresholds/aggregation, success/selection/feedback/continuation rules, harness/model,
Judge when needed, and finite limits. `max_attempts` bounds sequential creation;
many exploration calls or Replay do not add generations. One CLI run may contain
many internal model requests/retries.

Flow: fresh exploration → stopped submission/version → validation/technical binding
→ fresh development Replay and Evaluation → permitted correction within limits
→ selected version recorded **before final data** → final Replay/Evaluation/report.
No corrections or winner selection based on final results. Restore business/UI/draft
and n8n execution/static state for every Case; carry knowledge, not mutated worlds,
between Attempt. Duplicate tests occur within Case, not accumulated cross-Case state.

T1 uses the accepted policy below. Other Tasks' numbers, selection and handling of
incomplete evaluation remain decisions for the owner before implementation/measurement;
“first success, otherwise last result” is a proposal, not an implicit default.

### Accepted T1 measurement

The [Task rubric](../tasks/t1-send-message/tests/rubric.json) is the editable source.
Use 5 development + 5 private final Case, one per type in each set: ordinary new
input, equal display names, exact Unicode/whitespace/expression-like text, populated
state (including an old equal-text message), missing recipient. Four sends and one
refusal per set, different values; published/training/development/E1 values cannot
become holdout by renaming. Freeze both sets/order/hashes before measurement; final
values stay outside Git/public export/build/feedback.

All applicable required criteria must pass: recipient, text, multiplicity,
preservation, journal and refusal; applicability is predetermined. Missing chat
requires tool-confirmed `refused/not_found` without a send. Historical equal text
is not a duplicate: the new request still requires one new effect.

Only the selected version's complete final set receives a score: **2 × passed Case**,
**cap 3** for wrong recipient, duplicate send, altered text, unrelated mutation or
unauthorized send. No within-Case partial credit. Pass requires 5/5 and no critical
violation; any proven failure gives fail. Missing/incomplete/untrusted results give
score=null, with known trusted fail retained, otherwise unknown. Development and
per-Case scores remain null. Earlier development failures do not cap the corrected
version. Efficiency is separate; no Judge or runtime LLM for T1.

Maximum two Attempt, counting invalid/missing submissions. Select the first complete
5/5 development pass, otherwise the **last valid submission in Attempt order**;
an invalid second result does not displace a valid first. With no valid artifact,
report none. Unknown Composer, unconfirmed stop or incomplete/untrusted development
blocks automatic continuation and final Replay. Feedback contains only allowlisted
criterion IDs/status/safe reason or artifact-error codes, no private values/refs.

## 8. Evaluation and cost

Independent Evaluation uses protected before/after state, tool events, errors and
version identity. Check behavior, not equality with a single reference graph.
Code proves effects/recipient/text/templates/selection/duplicates/preservation;
candidate claims and Judge cannot prove a send.

Return score **0–10 or null**, separate Verdict, criteria/reasons/refs, completeness
and critical violations. Task owns the rubric; manifest saves its applied snapshot
and hash, not another editable policy. Critical failure cannot be compensated by
text quality or efficiency. Never average only available cases into a whole-set
result or count missing as zero.

Judge is supported for justified semantic criteria not reliably checked by code.
Do not invent subjective criteria to use it; templates alone need no Judge. Freeze
rubric/model and validate suitability on a small manually labeled set before using
its scores. Judge gets minimum evidence in a separate context with no execution
powers; candidate/chat text is data, not instructions. Validate criterion value,
range, explanation and existing evidence refs. Valid JSON/refs do not prove semantic
quality. Failure of required Judge leaves full score absent; unneeded Judge does
not block Evaluation. Reassessment uses saved facts without redoing business actions.

Report creation (including exploration, correction and failures), development/final
replay and Judge costs separately from infrastructure setup/cleanup. Preserve time,
API/UI/tool counts and available model calls/input/output tokens with sources and
completeness. Missing cost metrics alone do not invalidate a complete business
assessment. Unknown is not zero. Money requires recorded known prices; tokens,
time and differently granular commands are not interchangeable. Remaining Tasks'
weights/partial credit/thresholds/gates/aggregation/efficiency normalization require
approval before measurement, not fitting to observed results.

## 9. Errors and lifecycle

| Situation | Required outcome |
|---|---|
| Invalid artifact/proven workflow error | Record candidate failure/known violations; correct only within agreed Attempt/feedback limits. |
| Setup/verifier infrastructure failure | Preserve available facts; mark absent/incomplete assessment, not zero model quality. |
| Response lost after possible write | Preserve effect separately from workflow knowledge/status. No blind write retry; only permitted read-back or documented operation idempotency can resolve it, otherwise unknown and no full success. UI does not inherit API guarantees. |
| Unknown Composer call | Save facts/status/cost; Experiment must not automatically resubmit or grant a free Attempt. |
| Timeout/cancel | Close admission, drain accepted operations within deadline, stop processes/children and verify cessation. Stopping observation is not stopping work; unconfirmed stop remains unknown. Committed effects are not declared rolled back. |
| Bypass/tampering | No credit from forbidden access; record violation. Lost evidence provenance invalidates measurement rather than proving model failure. |

Harness/CLI/SDK internal retries are part of the measured harness: pin version,
record available retry policy/usage/observability limits, without rewriting its
agent loop. Finite time/tool/model/cost limits and confirmed local stop remain
mandatory. Remote accepted computation/cost can remain unknown after local stop.
Model runs require explicit authorization and finite limits before credential access.
API-billed runs also require an independently verified external credential/project
spending constraint. For explicitly authorized ChatGPT subscription runs, use
the live Codex account allowance instead: check available usage before each Attempt
and block continuation when remaining usage is unavailable or exhausted. This is
the accepted authentication policy, not an API spending-cap assertion.
A config assertion or local timeout is not provider enforcement; disclose documented
lag/possible overrun and agree practical limits/reserve, not a mathematical zero-overrun
promise. Unknown remaining budget blocks another Attempt. Continuation/reassessment
rules and external-check retry limits must be fixed before measurement.

## 10. Security and Evidence

Composer sees only the public task/artifact/tool contracts and authorized training
materials, never private tests, controls, final cases, service docs, personal files,
skills or other-run memory. Replay gets working input/tool observations, never
expected/verifier/admin access, Judge credentials, Docker socket or whole checkout.
Enforce file/network/tool/resource rights outside candidate code, including runner
and child processes; prompt instructions are insufficient.

Untrusted workflow executes separately from the private verifier. Protected
simulator facts reach host/verifier through a trusted channel, bound to run,
Attempt, artifact, Replay, Case and profile. Candidate logs/evidence/reward cannot
replace them. Hash proves identity/integrity after receipt, not producer trust.

Report conditions/tool versions, selected artifact, cases/Attempt, allowed feedback,
criteria/score/Verdict/completeness, execution/stop, costs, errors, cleanup and
unknowns, with native log/evidence refs. Artifact validity, business effect, process
status and assessment completeness remain distinct. Cleanup touches owned resources
only; no separate history platform or duplicate fact/log trees is required.

## 11. Accepted technical path

Native Harbor Task + Docker; one restricted native n8n JSON → validator/binder →
n8n; Python/uv; Harbor's installed-agent seam with stock Codex first and separate
Sapiens integration. No Composer HTTP bridge or parallel alternative implementations.
Compatibility/isolation require real controls for the chosen host/profile/versions;
[ARCHITECTURE](ARCHITECTURE.md) describes current contracts, [ROADMAP](ROADMAP.md)
records capability status and E1–E5 gates. External projects are ideas, not dependencies.

## 12. First-release acceptance

1. Full T1–T4 flow and their access profiles; public T3 templates without runtime LLM.
2. Real simulator effects and API/UI shared-state observations from fresh Case state.
3. Actual Composer exploration/submission and unchanged-version replay on new inputs;
   report model failures honestly, without hidden manual repair.
4. Positive and negative controls through the same runtime/verifier for every Task,
   covering wrong recipient, duplicates, memorized input/UI paths and relevant edges.
5. Agreed finite limits, feedback, pre-final selection and complete-set methodology;
   score/Verdict/completeness/costs keep unknown/infrastructure failures distinct.
6. Actual attempts prove isolation/evidence protection, plus lost-response, timeout,
   stop and incomplete-assessment controls. Diagrams/mocks do not prove isolation.
7. Judge integration is available; suitability/rubric/failure handling are proven
   before any justified semantic scoring, without artificial per-Case model calls.
8. Small supported-contract Task/app controls prove independence without core business
   changes; Composer replacement contract and Sapiens outcome are reported honestly.
9. Reproducible setup/report, real Harbor/n8n controls and bounded authorized model
   checks, with owned cleanup. A full harness × Task matrix is not automatically required.

Bench readiness differs from AI success: low score never justifies weakening checks,
and successful controls do not prove Composer ability. Missing Docker/credentials
or mocks cannot replace required real checks. Savings are not a release gate.

## 13. Decisions still required

| Decision / owner | Deadline |
|---|---|
| Final model/harness/config, finite budgets, retry/usage limits and verified external cap / experiment owner + implementer | Before each paid Codex, Sapiens, Judge or acceptance run; T1 numerical budget proposals remain unapproved. |
| UI identity/tree changes, stale observations, draft/search/effect rules; T3 latest/templates/no-input/processed and T4 keyword/provenance/bounds / Task author + owner | Before the relevant cases/implementation. Native T1 profile is already fixed. |
| Remaining Task sets/order/repetitions, rubric/aggregation/efficiency, selection/feedback/continuation / owner + Task author | Before their evaluated runs and policy implementation. Optional forced hybrid/H4 comparisons require an explicit decision if claimed. |
| Native profile extensions and host/version isolation / architect + implementer | Before unsupported semantics or untrusted execution; no automatic second language/backend. |
| Sapiens tools, state, submission and complete stop / implementer; blocker consequences / project owner | Before progression or release claims; E3 remains blocked. |
| Necessary semantic criteria, labeled set/suitability/model/rubric / Task author + owner | Before E5 and any use of Judge scores. |
