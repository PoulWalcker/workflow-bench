# Workflow Bench — architecture

Current responsibilities, interfaces and trust boundaries. Product rules and terms
belong to [SPEC](SPEC.md); milestone status and verification gates to
[ROADMAP](ROADMAP.md); commands to [README](../README.md). Source signatures and
packaged schemas define exact shapes.

## 1. Responsibilities and dependencies

| Owner / source | Responsibility |
|---|---|
| [Definition](../src/workflow_bench/definition.py) | Load native Task/materials/cases; validate disclosure and paths; publish a public snapshot. No sandbox lifecycle. |
| [Experiment](../src/workflow_bench/experiment.py) | Attempt policy, Case selection, source/version identity, fresh Replay, permitted feedback, pre-final selection and report. No app business decisions. |
| [Execution](../src/workflow_bench/execution.py) | Accept/validate native artifact, bind input/tools, import/execute n8n using borrowed resources. No environment creation, score or cleanup ownership. |
| [Harbor binding](../src/workflow_bench/harbor.py) | Native Trial/environment, stop/collection, tool/control transport, protected delivery to separate verifier and owned cleanup. One concrete Harbor integration. |
| [Evaluation](../src/workflow_bench/evaluation.py) | Validate Evidence/criteria identity/refs, apply Task-owned policy to the complete set and map numeric reward. Never execute/correct candidate. |
| [CLI](../src/workflow_bench/cli.py) | Resolve user paths/config, construct dependencies, logging and cancellation; select submission source. |
| [Composer integration](../src/workflow_bench/composer.py), [MCP transport](../src/workflow_bench/mcp.py) | Shared Harbor submission with stock Codex or Sapiens and native usage/lifecycle facts; stdio JSON-RPC over existing HTTP tools. Live ChatGPT integration is verified; API-billed mode remains closed. |
| [Telegram](../simapps/telegram/app.py) | One app-owned state, tool semantics/authorization and protected event history. Current API profile; future UI shares this state. |
| [SimsApp](../simapps/simsapp/app.py) | One application-owned state, bounded current UI projection and elementary navigation, composer and Send transitions. No Task target or business API. |
| [Simulator transport](../src/workflow_bench/simulator.py) | Shared capability/reset/issue/revoke/drain/freeze/journal and separated HTTP listeners; Telegram and SimsApp supply their own state validation and tool semantics. |
| `tasks/<task>/tests/` | Business checks/expected/rubric; executed by native separate verifier, not imported into host core. |
| [contracts](../src/workflow_bench/contracts.py), [data](../src/workflow_bench/data.py), [resources](../src/workflow_bench/resources/) | Checked exchange values, strict external JSON and installed schemas/public texts. |

Import direction: CLI → concrete integration/config + Experiment;
Experiment → Definition/Execution/Evaluation/contracts + Harbor binding;
Execution → contracts/data and borrowed Harbor context;
Evaluation → contracts/data; Definition → native Harbor Task/parser + data/contracts.
Contracts do not import app/Composer; core does not import Telegram/Sapiens or branch
on their business names. App/verifier may use common exchange helpers. Common prompts
consume public materials without Task switches. No Task registry or alternate Task class.

The [Sapiens integration](../src/workflow_bench_integrations/sapiens.py) lives outside
core at Harbor's `BaseInstalledAgent` seam, reusing native Codex config/MCP/auth
helpers through its Codex subclass. Only the entry point selects it (`--sapiens`);
core knows no CORPORA commands, memory or internal planning. Each native Trial
starts a dedicated unmodified host+CLI/data-dir/home/config/provider session.
The shared Composer submission path accepts `AgentConfig`; Harbor closes tools
and stops the whole container before native artifact collection.
Build prerequisites and controls are in [README](../README.md). Both harnesses use
identical Task/case/profile/rubric/runtime/Evaluation hashes; harness configuration
and costs remain separately attributable.

`simapps/` holds application code; `environments/` builds shared images;
`tasks/` holds native benchmark packages; root `tests/` tests software;
ignored `runs/` holds private results.
Future directories appear with implementation, not as scaffolding.

## 2. Task materials and data boundaries

Native layout: `instruction.md`, `task.toml`, `tests/test.sh`, `solution/solve.sh`;
`environment/` is needed only without a ready image. Additional JSON is experiment
data, not a second Task framework. The current example is
[T1](../tasks/t1-send-message/task.toml).

| Material | Reader / ownership |
|---|---|
| `instruction.md` | Human business intent; Composer reads it unchanged. |
| `task.toml` | Host/Harbor native configuration; `wb_public`, `wb_cases`, `wb_rubric`, optional private `wb_final_cases`, app image and tool profile. Not public-exported. |
| [task.json](../tasks/t1-send-message/task.json) | Public input schema, training example including public state, feedback disclosure. |
| `tests/cases.json`, optional private final file | Host selects input/state/expected; only simulator gets state and only verifier gets expected. Case sets have development/final purpose. |
| `tests/test.sh` and supporting checks | Task-owned executable checks on frozen facts in separate verifier. |
| `tests/rubric.json` | Editable Task-owned policy; manifest retains applied snapshot/hash. Public requirements must already be in public intent/contracts. |
| `solution/solve.sh`, `solution/workflow.json` | Trusted manual control submission only; unavailable to candidate Composer. Same validator/runtime/verifier, no self-awarded reward. |
| App [tools profile](../simapps/telegram/tools.json) | App-owned operation semantics/schemas/errors/limits/idempotency/effect observations; supplied explicitly from selected image. |

`load_task(task_path, *, tool_contract) → TaskMaterials` uses the native Harbor
parser, validates metadata/public/tools and checked private paths without starting a
Trial. Paths are absolute, Task files stable during read, returned JSON trees owned
snapshots that callers must not mutate. Core treats state/expected as opaque JSON;
simulator validates state and Task verifier validates expected.
`load_cases(..., purpose="development"|"final") → tuple[CaseData, ...]` validates
IDs/input/purpose and disjoint final versus development IDs/inputs; omitted IDs
select the complete set in file order. Final requires a private metadata reference.

`export_public(materials, destination) → PublicPackage` exports exactly the six
files named by `PUBLIC_PACKAGE_FILES` in contracts: instruction, task, tools,
workflow contract/schema and neutral Composer handoff. Export uses loaded snapshots
and packaged texts, not source-tree traversal or instruction interpolation. Cases,
rubric, tests, solution, native config, service docs/skills and home are excluded.
Destination must be absent with an existing parent and an exclusively caller-owned
name. Task packages/authors are trusted, with containment still enforced.
Publish via temporary sibling/rename; on error remove only the owned temporary
directory. This trusted host Interface is not protection against concurrent
filesystem replacement. Reject metadata traversal/absolute paths/symlinks including
parents, nonregular files and private/public path overlap; safe errors expose only
codes/material refs.

Own JSON uses Draft 2020-12 and installed resources via `importlib.resources`, not
cwd/Git-root lookup or a parallel runtime type schema. Reject duplicate keys,
NaN/Infinity, unresolved/nonfragment HTTP/file refs (including unused ones); check
schema before data, size before decoding. General material limit is owned by
[data.py](../src/workflow_bench/data.py); evidence has its separate bounded limit.
Frozen dataclasses do not freeze nested dicts. Semantic graph/identity/ref checks
belong to their owner; verifier ingress is another trust boundary and validates again.

## 3. Artifact and Replay interfaces

[workflow.md](../src/workflow_bench/resources/workflow.md) and
[workflow.schema.json](../src/workflow_bench/resources/workflow.schema.json) own the
exact current native T1 profile, size/node versions/options and BenchInput/BenchResult
shape. If/Loop Over Items and UI/collection extensions remain future E4 work;
current T1 acceptance does not establish their expressiveness.

`accept_artifact(collected_file, *, submission_stopped, destination)` returns
`WorkflowArtifact` only after confirmed writer stop. Receive a bounded regular file,
reject symlinks (including parent/source during delivery), hardlink substitution,
missing/invalid JSON/profile and unconfirmed submission. Copy/hash the same open
byte snapshot into a new closed host file. Host validation never executes candidate
code, repairs JSON or unpacks arbitrary archives. Timeout remnants are diagnostics,
not automatically accepted versions. Harbor's collection manifest must report the
expected source as an actual successful file; a dereferenced symlink in a host copy
cannot be detected by host lstat alone.

`bind_workflow(artifact, *, case_input, base_url, capability, destination)` returns
`BoundWorkflow`. Replace only BenchInput's literal JSON text with input/tools data;
never interpolate input into code/expressions or inject Case state/expected.
Keep original bytes/hash, bound hash and replacement JSON pointer; all business
nodes/connections/options remain unchanged. Bound JSON may be reserialized.
Capabilities belong only in the private bound file, not reports/ordinary logs.

`replay(artifact, *, case_input, context, config)` uses a borrowed `ReplayContext`
and returns execution JSON + BoundWorkflow. One execution path: import into a fresh
local n8n database, then Server CLI execute by submitted workflow ID with raw output.
No editor service or second execution backend. JS Code runs in the compatible external
n8n runner, without candidate npm installation. Code/expressions are untrusted;
structural validation or forbidden-substring scanning cannot prove their safety.

Current execution reads the sole BenchResult item from the fresh native SQLite
execution record, using a separate trusted collector and bounded flatted/JSON
serialization. Candidate stdout/stderr remain separate diagnostics and cannot supply
a result. Require one matching CLI execution; record its native execution ID. Record
claim `completed|refused|unknown` or absence independently of process
`not_started|completed|failed|timed_out|cancelled|unknown`, exit code, stop request/
confirmation, error/log refs and timings.
`exit 0`, raw output and claims are not trusted proof of business effect.

## 4. Harbor lifecycle and trust topology

| Surface | Permitted data/connections |
|---|---|
| Trusted host | Private Task/results, Harbor/Docker management and simulator control; owns resource handles and immutable snapshots. |
| Composer sandbox | Public package, prior artifact/permitted feedback, clean workspace/home/config/sessions; only exploration tools and required provider. Model-free mode uses synthetic auth/internal local stub. ChatGPT mode uses Harbor's native single-file auth injection and network allowlist; API-billed mode still requires a verified external cap. |
| Replay n8n | Artifact, input and Case tool capability; fresh DB, only current simulator tools and own runner broker. No Internet/host egress. |
| External JS runner | Own broker only, no private volumes/control; subject to the same candidate isolation/resource constraints. |
| Simulator | App state/history and tools; management listener separated from tools and accessible only to host. |
| Separate verifier | Private tests/expected and protected read-only facts, candidate JSON as data; no candidate execution, no network unless a necessary Judge endpoint is explicitly provided. |

Composer credentials never reach replay/verifier; Judge auth belongs only to assessment.
Native `auth.json` is readable by Composer's shell in its temporary home under the
accepted subscription-auth policy; the personal home is never mounted. Harbor deletes
the Composer environment before accepting its artifact.
No checkout, personal home, private tests/final/solution, Docker socket, control or
Judge credential in candidate/replay/runner. Oracle solution access exists only for
trusted manual submission. Images are prepared from allowlists before measurement,
with pinned base/runtime/runner and locked dependency hashes; private Task/home are
excluded from build context. [build.py](../environments/build.py) owns image pins;
[pyproject.toml](../pyproject.toml)/[uv.lock](../uv.lock) own dependency versions.
The builder requires explicit `--simapp`; the selected app owns its image tag and
contracts. Shared images expose regular protocol files at `/bench/tools.json` and
`/bench/state.schema.json`, with application code at `/app/simapp`.

Replay/runner use internal tools/broker networks, no exposed host ports/bind mounts,
read-only roots, tmpfs, resource limits, dropped capabilities/no-new-privileges.
Host control is an authenticated management-IP listener with a dynamic loopback host
port; never bind admin into tools. n8n SSRF protection is disabled for local tools;
Docker network topology supplies the egress boundary. Inspect actual mounts/networks,
private access, control reachability and fresh DB **before uploading workflow**.
Settings/container names alone do not prove isolation on a new host/profile.
Composer probes the inspected management IP and configured control port from both
main and provider; any HTTP response, including authorization failure, means reachable.

`replay_environment(config, identity, *, lifecycle=...)` owns environment/session
creation through exit/partial-start cleanup. `ReplayContext` is borrowed; host-only
control/auth never enters tool bindings. `run_native_trial(stage, attempt_id,
prepare_verification, *, config, lifecycle=...)` owns native Trial/config and separate
verifier. The current agent/setup/close-tools/verification options support stock
Codex and manual sources at the same seam, without copying Trial.

Submission: native `AGENT_END` closes tools/stops writer before collection;
`VERIFICATION_START` confirms submission deletion and collection, clears untrusted
agent-phase verifier logs without following symlinks, and calls host preparation
with only the collected path. The callback accepts the artifact, performs separate
Replay, then stages protected inputs before native separate-verifier tests upload.
No custom BaseVerifier, nested Harbor, Docker socket in test.sh or candidate-driven
lifecycle. Read Evaluation only after successful protected-input preparation;
validate delivered case/identity/evidence hash, aggregate and parsed native reward.

For each Replay: reset new simulator → issue scoped capability → execute → revoke/
close admission → bounded drain/freeze → stop n8n/runner and verify metadata →
export frozen facts → separate verifier. Exploration is already stopped and its
mutated world is never used for Case verification. Pending operations produce
incomplete facts; late commit after freeze is forbidden. Export preserves the same
frozen facts. Failures still attempt both runtime stops and owned cleanup.

`DeadlineDockerEnvironment` narrowly extends pinned Harbor 0.24.0 stop and buffered/
streamed collectors to bound cleanup and kill/reap its own subprocess on cancellation.
For Composer cancellation, close tools/stop writer before installed-agent finally
collection; stopping host docker exec alone does not stop container children.
Native lifecycle stays Harbor-owned. Private-method coupling requires regression
and real controls when Harbor changes. Cancellation/signal handling supports bounded
cleanup on POSIX; SIGKILL/daemon failure cannot promise finally/graceful cleanup.
Report stop request separately from observation, original cause when stop is unknown,
cleanup errors and scoped residual IDs. Never remove neighboring resources.

### Tools and control wire

HTTP: `POST /tools/{name}`, bearer Case/exploration capability,
`{schema_version, arguments}` → `{call_id, result}` or
`{call_id, error: {code, retryable: false}}`. Missing transport response is local
`transport_unknown`; client may not know call_id. HTTP status is not effect proof.
Server fixes identity/actor/profile/expiry/count from capability, not client fields.
Prepared images expose packaged Python modules through the interpreter’s site path,
so Codex’s filtered MCP subprocess environment does not require `PYTHONPATH`.
MCP is a thin stdio facade over these operations; MCP/HTTP share authorization/count,
no write retry and no admin publication. UI-only must reject API at server level,
even for direct HTTP; SimsApp navigation has its own real model-free control.

Host-only control: POST reset(identity/state/profile/tool limits), issue(identity/
actor/TTL/max_calls), revoke(identity), freeze(identity/drain deadline), GET export.
One reset/issued scope per fresh instance, no reset of an active Replay. Revoke is
idempotent and prevents new admission, not rollback. Export follows freeze; safe
control retries stay within cleanup deadlines and never repeat business actions.
Fault injection for lost-response/pending-commit controls remains host-only.
Body reads and response transport run outside the app state lock; admission is
rechecked after body read. Pending calls retain their last stage so freeze records
unknown completion once, without duplicate effects or late journal changes.
The wire evidence limit (1200 events) owns the journal bound; after 400 journaled
requests, reject excess traffic without growing events. Protected violation summaries
retain overflow and unauthorized-send facts. Overflow adds no scoring penalty; the
existing unauthorized-send criterion also reads its protected summary.

SimsApp model-free controls reuse the existing Harbor sandbox topology, stop and
protected export responsibilities. `ui_control` identities use `run_id`,
`control_id`, `case_id`, `profile`, `profile_hash`; resources use `wb-control-`
scopes. They do not invent artifact/Attempt/Replay IDs or execute a native workflow.
A scripted UI caller runs in the existing isolated sandbox; cancellation uses the
existing writer-stop callback before host exec teardown. No online agent harness
or second lifecycle is introduced.

## 5. Evidence and Evaluation interfaces

[wire.schema.json](../src/workflow_bench/resources/wire.schema.json) owns identity,
claim, execution, evidence, criterion, rubric, evaluation and aggregate envelopes.
Evidence binds run/Attempt/artifact/Replay/Case/profile hash/name to revisioned
before/after snapshots, monotonic events, violations, freeze status and pending IDs.
Each call records accepted/effect/response stages: committed/no_effect/unknown and
sent/failed/unknown remain distinct. Sent means transport write, not client receipt.
State/effect payload semantics belong to simApp. Gaps/violations survive export.
Only protected host-control provenance grants trust; hashing untrusted data does not.

Task verifier reads `/bench/input/{case,execution,evidence,rubric}.json`, delivered
via staged native tests. Inputs and parent are root-owned/read-only to UID 65534;
only current verifier output is writable. Candidate modules/strings are never executed
here. `read_evidence(path, *, expected_identity)` validates envelope, revisions,
sequence, call consistency/refs/freeze and returns `FrozenEvidence` with hash.
Task script supplies criterion ID/status/value/reason/evidence refs;
`assemble_evaluation` validates against rubric/execution/facts;
`aggregate_evaluation` checks the complete expected identity set (reject duplicate,
missing/foreign identity) and applies task-owned policy without app semantics.
Numeric rules/selection are [SPEC's T1 policy](SPEC.md#accepted-t1-measurement),
with editable values in Task rubric rather than wire schema/core duplicates.

Criterion status is `pass|fail|unknown|not_applicable`; completeness is
`complete|partial|unavailable|invalid`. Known trusted failures survive incomplete
scores; lost provenance cannot generate business conclusions from fabricated facts.
No missing claim is silently interpreted as claim=unknown. Null success/scoring
policy permits a technical control, not an invented full score or Verdict.

Atomic `/logs/verifier/evaluation.json` is authoritative only in the current clean
verifier phase. `harbor_reward` maps a complete numeric score to `{"reward": score}`;
otherwise no numeric file is written. Harbor missing-reward error is retained, never
zero. Development requires no numeric reward: missing native reward is expected and
separate from business completeness. Final missing reward marks incomplete coupling
while preserving business Evaluation. Standard Harbor averages do not define the
experiment's score; host recomputes aggregate and compares parsed reward.

Future Judge receives minimum facts/rubric without execution authority; response
validation and repeated assessment use saved facts, never another business Replay.
Suitability and failure rules belong to [SPEC §8](SPEC.md#8-evaluation-and-cost).

Wire Evidence v1 remains the unchanged native T1 branch. Version 2.0 currently
supports only tagged `ui_control` identity and actor=`control`; it reuses the
before/after/event/freeze envelope and adds protected observation facts and
revision-linked transition deltas. `read_evidence` independently validates stage
ordering, references and the delta chain from before to after; unknown/pending
facts cannot fabricate a complete freeze. App payload semantics stay in app/control
checks, and no second state/journal or score calculation is stored. The current
SimsApp V1 profile (`simsapp-ui-v1`) exposes the active conversation's composer and
Send, with no pagination or scroll. Its UI projection copies sanitized AX trees and
fragments from the app fixture package. Native roles and fields retain their captured
shape; `simulation` annotations explicitly mark reconstructed labels, supported actions,
identity hints and draft values. Scoped `ref` locators belong to the simulator. Send
uses an annotated AXMenuItem; its activation/effect is reconstructed, not observed
native WhatsApp behavior. `replace_text` replaces the focused editable
value exactly; the wrapper admits message-sized text, while the resolved Search
control enforces its smaller query bound from the state schema. Drafts are keyed
by conversation in the same state. Send uses the active conversation and draft,
appends one outgoing and clears that draft in one revision under the existing
Simulator lock. Protected deltas capture owned values (including draft replacements),
and the send effect's message ID links its call to the appended message and later
observations. FrozenEvidence already validates list append and draft-map deltas;
no wire version, shared ingress, transport or Harbor lifecycle change is needed.
The app profile/image hash identifies the supported UI capabilities; tool wrapper v1
and Evidence v2 retain their existing versions. Lost response remains
separate from commit; no write retry or deduplication is added.

The AX projection selects chat-list, search-focused, results-zero, results-many or
conversation captures according to current state. It retains AXApplication →
AXWindow → nested AXGroup relationships, window chrome, menu bar/submenus, native
role/subrole variants, geometry, numeric flags, empty strings and omitted fields.
Search remains AXStaticText/AXSearchField; composer remains AXTextArea without a
fabricated native AX value. Message bodies bind AX descriptions; direction and
exact draft value belong to `simulation`. Contacts/results repeat observed row
fragments; history repeats observed composites, including its wrapped first message
and nested date headings. State supplies names/hints and messages; fixture examples
never create an extra conversation or history. Search background rows remain present
but cannot activate with a nonempty query; background history is empty without an
active conversation and does not expose another conversation's messages/drafts.

Observation `template` identifies the selected capture; `truncated` retains its
serializer flag. Coverage is complete for the bounded SimsApp collection, not all
native AX content. Refs are assigned by traversing the assembled tree and include
scope, revision, template and current child path. Capture-local paths/identifiers
are neither business identity nor stable action locators. Nonannotated nodes have
no supported actions even when their captured enabled flag is true. The derived
profile allows 640 nodes and depth 16; state bounds stay 32 conversations/100 messages.

Reconstruction preserves the accepted simulator navigation/effects: result
activation opens a conversation directly; Back and Send activate serialized menu
nodes without a menu-opening sequence. Blindly result activation instead exposed
a sheet. Full one-result screens, draft writes and Send effects were not captured.
Sheets, message-result search, the unlabelled result category, Voice message,
scrolling, other menu actions, delivery semantics and alternate AX relations are
unsupported. Unused result categories retain headings but have no candidates;
unknown relation targets are not invented. Copied coordinates and fictional date
headings are reference layout, not measured geometry or message timestamps for new
state. Sanitized assets are committed application resources, covered by the
[fixture package's publication scope](../simapps/simsapp/fixtures/README.md#provenance-and-publication).
Private captures are unnecessary for runtime/builds and remain outside the package.
Runtime integration neither regenerates fixtures nor authorizes additional captures.

## 6. Experiment/configuration interfaces

`run_manual` orchestrates one control Attempt with chosen Case IDs/purpose; optional
accepted submission is staged without following solution/parent symlinks. `run_measurement`
uses controlled files or one submission callable per Attempt through the same
runtime/verifier. `select_attempts` returns selection/block/continuation and the
Task-allowed development projection. Selection ID/hash/ref is written before final
Replay; source/phase manifests save applied config/material/profile/case/rubric
snapshots and hashes. Report references native logs and closed run facts once.

| Parameter | Source |
|---|---|
| Task/output/case/submission paths | Explicit CLI; resolve once relative to invocation cwd. Internal paths are absolute. |
| Public/case/rubric references and app/profile | Native Task metadata, relative only to Task root. |
| Runtime images/ports/phase and total deadlines/CPU/RAM/max_calls | One explicit runtime JSON validated by [e1.schema.json](../src/workflow_bench/resources/e1.schema.json); E1Config derives native overrides, no competing env defaults. |
| Tools | Selected prepared image exports app profile; passed to loader explicitly and hashed. |
| Schema/artifact/protocol constants | Packaged resources/contracts, not independent CLI options. |
| Control/candidate/broker capabilities | Host-generated per run/scope; only respective recipient gets secret. Topology allocates host ports. |
| Model plan | Explicit budget/runtime config, [model-budget.schema.json](../src/workflow_bench/resources/model-budget.schema.json); Composer config records mode/image/CLI/model/reasoning/exploration limits. |
| Internal Codex subscription auth and authorization | Explicit `--codex-auth` path resolved once at entry and `--authorize-model`; native host account facts supply remaining allowance. No API dollar budget is asserted for ChatGPT auth. |

Preflight validates method/profile/versions and finite approved per-Attempt/total
budgets/remaining amounts before credential/resources. `model_preflight` validates
a plan only (`execution_enabled=false`, `enforcement_verified=false`);
`codex_preflight` permits isolated model-free mode. ChatGPT mode requires explicit
CLI authorization and an auth-file path; native host `account/rateLimits/read`
checks subscription usage before and after each Attempt, using a temporary clean
Codex home. The entry point supplies `--authorize-model` and `--codex-auth`; it
never supplies credentials to Replay. API-billed mode remains closed without
verified external enforcement. Config flags are not proof of provider limits.

Composer facts include native result/timing/usage refs, artifact/process/stop and
cleanup outcomes. Human `instruction.md` is copied unchanged; a packaged Harbor
prompt template supplies the neutral artifact/tools handoff separately. The narrow
stock Codex adapter guard snapshots only regular, no-follow session files, with
entry/depth/aggregate byte bounds, before native parsing. Candidate trajectory files
never supply fallback metrics. Missing/ambiguous/malformed usage remains null; use the last
cumulative total of one session, not the sum of repeated totals or Harbor's missing
counts normalized to zero. Unknown remaining budget blocks another Attempt.
Model-free zero calls are grounded in the isolated stub mode; no claim about real
reasoning, provider enforcement or successful E2 follows from it.

Errors before resources are safe typed data/artifact errors; observed external
failures are result values. Unexpected defects propagate at CLI after bounded
cleanup. Cleanup/export/persistence failures preserve the primary exception or
cancellation; stop errors are exchanged through the borrowed context and recorded
when persistence is available. Original phase facts remain discoverable after interrupted runs. Technical
E1 timeouts are not model budgets; readiness is recorded in [ROADMAP](ROADMAP.md).
