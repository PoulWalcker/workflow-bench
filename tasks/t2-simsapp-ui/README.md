# T2 — Context-aware message delivery

Task-owned definition, development Cases, reference UI decisions and independent
criteria. **Native benchmark execution is blocked by existing contracts.** This
package does not claim successful native n8n Replay, a numeric score or NAV readiness.
No models, real accounts or physical desktops are used.

## Business vocabulary and rules

A **matching conversation** has the exact input display name and at least one
incoming message containing the literal, case-sensitive reference substring.
A **requested send** is a new outgoing message caused by this execution. A previous
identical outgoing message is neither that send nor a reason to suppress it.
An **unrelated draft** belongs to any conversation other than the unique match;
when there is no unique match, every draft is unrelated.

Names, references and text retain Unicode code points, whitespace and newlines.
One match requires one exact send; zero/multiple matches require an explicit refusal
and no send. UI search/navigation/focus may change. Only the unique target's draft
may be replaced and cleared; even temporary unrelated draft mutation is a failure.
Visible identity hints are not matching predicates. The short public instruction
gives the objective; `task.json` schema descriptions publish these matching, refusal
and preservation rules without a route or hidden recipient ID.

## Package and interfaces

| Files | Responsibility |
|---|---|
| `instruction.md`, `task.json`, `task.toml` | Definition: public intent, bounded input/training example, native Harbor metadata |
| `tests/cases.json` | Development input/state/independently authored expected outcomes |
| `tests/rubric.json`, `tests/verify.py`, `tests/test.sh` | Required criteria and separate-verifier entry point |
| `tests/input.schema.json` | Verifier delivery copy of the public input schema; equality checked by package tests |
| `solution/reference.js`, `solution/build_workflow.py`, `solution/workflow.json`, `solution/solve.sh` | Reference decision logic and native n8n submission |
| `prepare_private.py` | Freeze an operator-supplied private-final file into a separate owner-only Task copy |
| `tests/test_definition.py`, `tests/test_verifier.py` | Local behavioral/disclosure/ingress controls |
| `tests/controls.py`, `tests/native_probe.py` | Explicit model-free Harbor controls and native compatibility reproduction |

The verifier's small Interface is `criteria_for(case, FrozenEvidence, claim)`.
Callers first use the existing `read_evidence` ingress, which validates identity,
freeze, stage ordering and revision-linked transitions. Verifier CLI additionally
validates input, state schemas and claim. It imports no SimsApp code and independently
checks expected against the initial world. An inconsistent expected value is an
invalid Case, not an agent failure.

Eight required criteria: recipient, exact text, multiplicity, preservation, journal,
refusal, UI-only access and inspection. Sends are identified by committed message IDs
and appended messages, never by counting committed navigation actions. New outgoing
IDs distinguish existing equal-text messages. Journal inconsistency is unknown;
trusted wrong effects remain failures even when freeze is incomplete. Preservation
separates proven unrelated mutations from the draft-clearing postcondition of an
actual Send; an incomplete Send postcondition remains unknown. Inspection requires
an observation response matched by `call_id` with status `sent` before the first
send: unique/missing outcomes require complete candidate coverage and all candidate
histories; two observed matches suffice for ambiguity. Generated observations with
failed, unknown, missing or late responses cannot confirm inspection. If those
observations could supply the missing coverage, inspection remains unknown. A
`sent` response proves a transport write, not a client receipt acknowledgement.

The current rubric uses `all-required-v1` with **no numeric scoring policy**. No T1
weights/caps, aggregate, numeric reward or second scorer are introduced. Protected
UI-control verification emits checked criteria and an Evidence hash only. It cannot
supply common Evaluation until that contract accepts its real identity/stop facts.

## Development Cases

| Case | Expected behavior |
|---|---|
| unique | One new send to Alex Morgan identified by incoming reference |
| duplicate-names | Ignore the first equal-name conversation with a different reference |
| wrong-contact-reference | Ignore the reference in another contact's history |
| outgoing-only | Refuse: outgoing reference is insufficient |
| missing-reference | Refuse: no incoming match |
| ambiguous | Refuse: two different matching conversations |
| old-equal-text | Send one new message despite an equal old outgoing |
| unicode | Preserve emoji, combining marks, whitespace, newline and literal expressions |
| unrelated-drafts | Start in another conversation; preserve its draft and replace the target draft |
| case-sensitive-reference | Refuse a differently cased reference |
| exact-name | Refuse a name with an extra trailing space |
| multiple-incoming-one-conversation | Two matching incoming messages still identify one conversation; start in search |
| empty-world | Refuse with a complete empty list |
| unicode-no-normalization | Refuse composed/decomposed reference mismatch |

No AX fixtures are copied here. Real UI controls use an already prepared immutable
SimsApp image; fixture publication/packaging remains external to this Task.

## Reproducible commands

Run from the repository root after the root README's locked setup. All output
paths must be new. Runtime config supplies images, ports and finite limits.

```sh
uv run --locked --offline pytest -q tasks/t2-simsapp-ui/tests
uv run --locked --offline ruff check tasks/t2-simsapp-ui
uv run --locked --offline ruff format --check tasks/t2-simsapp-ui
uv run --locked --offline python tasks/t2-simsapp-ui/solution/build_workflow.py

# Use the prepared SimsApp config. For the full serial suite, explicitly set
# total_timeout_sec=1200, verifier_timeout_sec=90, max_calls=100 in that config.
uv run --locked --offline python tasks/t2-simsapp-ui/tests/controls.py \
  --config runs/simsapp-images/config.json --output runs/t2-controls

# Genuine native submission through the existing path; currently blocked.
uv run --locked --offline python -m workflow_bench.cli \
  --task tasks/t2-simsapp-ui --config runs/simsapp-images/config.json \
  --output runs/t2-native --case unique
uv run --locked --offline python tasks/t2-simsapp-ui/tests/native_probe.py \
  --config runs/simsapp-images/config.json --output runs/t2-native-observe
```

The UI control command uses existing Harbor resource ownership, isolated UI transport,
revoke/freeze, confirmed stop and separate verifier. Fourteen reference scenarios
and three negative controls (altered text, duplicate send, forbidden API attempt)
pass through the same checks. No native workflow is executed by this command.
The decision function is shared with the reference workflow, but this does not prove
n8n expressions, branching or loop execution. A missing native reward is expected
for criteria-only controls and remains recorded, never replaced with a fake reward.

## Private final

Keep real holdout data outside the checkout. Supply a prepared native Case document
with `schema_version: "1.0"`, `purpose: "final"` and independently authored Cases.
Its IDs and inputs must be disjoint from development. Use different synthetic worlds,
not renamed training data. Freeze the file before evaluating candidates.

```sh
uv run --locked --offline python tasks/t2-simsapp-ui/prepare_private.py \
  --final /path/to/operator-final.json --destination runs/private-t2/task \
  --tools simapps/simsapp/tools.json
```

The destination must be absent. Its root/private directory use mode 0700 and final
file mode 0600. `wb_final_cases` points to `private/final.json`; the real Definition
loader enforces path/disclosure rules and development/final disjointness. Only the
existing six-file public export is Composer material. Never give Composer the Task
copy or use it as an image build context. No final file, final expected, solution or
verifier is in public export. Missing final is an error, never a development fallback.
There are no real holdout values in this repository. Synthetic sentinel tests prove
export separation, not filesystem isolation against the trusted host owner.

## Native compatibility and WB-22

1. **Artifact profile**: the reference native graph uses an `If` node and a cycle
   around one UI HTTP request. Current acceptance permits only the T1 node profile.
   Genuine Harbor oracle collection succeeds, then `accept_artifact` rejects
   `invalid_profile`. No Replay starts. The reference n8n graph is an unverified
   native proposal, not an accepted/runnable artifact under today's profile.
2. **Simulator identity/actor**: `native_probe.py` submits a minimal allowlisted
   observation-only artifact (not a solution). Its artifact is accepted, but the
   existing native path fails at simulator reset with `control_failed`. SimsApp
   declares `identity_contract="control_identity"`, `actor="control"`, Evidence v2;
   native Experiment sends the artifact-bound Replay identity. No fake conversion
   to `ui_control` is performed; n8n execution is not reached.
3. **Evaluation identity**: existing `assemble_evaluation` rejects real `ui_control`
   identity with `invalid_schema: evaluation`. A retained local reproduction supplies
   valid FrozenEvidence, criteria and an execution envelope. The Task emits raw
   checked criteria for controls; it does not invent Replay IDs or a second Verdict.

WB-22 needs approved artifact/UI iteration, simulator identity/actor and common
Evaluation coupling contracts, then genuine end-to-end positive and negative native
controls. No extension is implemented here. Numeric methodology and real private-final
results also remain unverified. See `VERIFICATION.md` for actual command outcomes.
