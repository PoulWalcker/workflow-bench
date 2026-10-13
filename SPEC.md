# Workflow Bench — product specification

Workflow Bench supports decisions about Sapiens development by comparing Sapiens
with bare Codex on the same model. [GLOSSARY](GLOSSARY.md) owns domain terms;
[ARCHITECTURE](ARCHITECTURE.md) owns technical boundaries and
[README](README.md) records verified commands. This is a product contract, not a
claim that readiness, comparison or all task levels are already implemented.

## 1. Goal and limits of conclusions

Measure where Sapiens helps or hurts, by how much, and why, using reproducible
[Tasks](GLOSSARY.md#task) and independent outcome checks. Compare whole
[Configurations](GLOSSARY.md#configuration), including the
[Harness](GLOSSARY.md#harness), model, settings and environment; results do not
isolate model quality or establish reliability beyond the tested tasks and conditions.
One successful [Trial](GLOSSARY.md#trial) does not establish general reliability;
simulated services do not establish real-service latency or production safety.

The agent chooses its strategy. Direct actions and a reusable workflow are both
valid; the benchmark does not impose a workflow format. Tools expose elementary
capabilities and must not supply the business solution. The first release targets
L1, L2, L3a, L3b and repeated execution, with justified semantic evaluation.
UI is a separate track; real remote services and ambiguous-user dialogue are deferred.

## 2. Task levels and horizons

Record each task's [Level](GLOSSARY.md#level) in its metadata; leave strategy
selection to the agent.

| Level | Provided environment |
|---|---|
| L1 | Logic tasks with minimal tools. |
| L2 | Local files, search, shell and git. |
| L3a | One [Simulated service](GLOSSARY.md#simulated-service) through API/MCP. |
| L3b | Multiple simulated services connected by business requirements. |
| L3c | Real remote services; deferred. |
| L4 | UI through simulated applications; separate track, outside the first release. |

Record its [Horizon](GLOSSARY.md#horizon) as single or repeated, independently of level.
Repeated tasks check results across [Steps](GLOSSARY.md#step) on changed state,
including idempotency where required. In one form the agent acts at every step;
in another it configures automation once and later steps run without the agent.
Required recurring behavior is a business constraint; its implementation remains
the agent's choice. Repeated execution is a requirement, not a verified capability
of the current checkout.

## 3. Flow contract

Every task follows the same flow. The table assigns responsibility; it does not
introduce another execution engine or assert that every stage is implemented.
Task-authoring regulation, its template and automated readiness check arrive in M1.

| Stage | Input → output | Owner |
|---|---|---|
| Task Definition | Native Harbor task directory: public goal, constraints and result location; environment; private checks/expectations/rubric; oracle solution; level/horizon metadata → defined task. | Task author; Workflow Bench owns authoring rules. |
| [Readiness](GLOSSARY.md#readiness) | Defined task → ready/not ready: structure conforms, Harbor parses, oracle passes, no-op fails (not unknown), semantic Judge calibrated when used. | Workflow Bench readiness checks, native Harbor controls and comparison. |
| Environment | Configuration → isolated agent environment, optional services, network and tools. | Harbor; Workflow Bench supplies its images/services. |
| Execution | Ready tasks × configurations × bounded trial count under equal conditions → native logs, trajectory, usage and process status. | Harbor and the selected harness integration. |
| [Evidence](GLOSSARY.md#evidence) | Execution → answer files/filesystem facts and protected service state with provenance. | Harbor collection; Workflow Bench service exports. |
| [Evaluation](GLOSSARY.md#evaluation) | Evidence + private criteria → verdict, criterion results and completeness; native reward only for complete evaluation. | Task verifier and Workflow Bench helper, inside the Harbor Trial. |
| [Comparison](GLOSSARY.md#comparison) | Saved Harbor job results/configuration/evaluation → per-task metrics, per-level summary or incomparable. | Workflow Bench offline comparison; the only report-building stage. |

No model trial starts before readiness passes. Public instructions give intent,
constraints and result location without prescribing an algorithm or a tool when
tool choice is measured. The oracle proves solvability and validates the check;
the agent's output need not match the oracle's implementation.
For repeated tasks, Execution → Evidence → Evaluation repeats per step, followed
by an aggregate; later steps may omit agent execution in the configure-once form.

## 4. Outcomes and evaluation

Assign each trial exactly one [Outcome](GLOSSARY.md#outcome): `pass`, `fail`,
`unknown` or `infra_error`. The [Verdict](GLOSSARY.md#verdict) depends only on
observable results against the same [Criteria](GLOSSARY.md#criterion) for both
harnesses. Harness-specific process checks, such as delegation, are diagnostics.
Known violations remain failures when other criteria are unknown; incomplete or
untrusted evidence cannot establish a full pass. A missing measurement is unknown,
never a known zero. Infrastructure failure is separate from agent quality.

An agent ending early, reaching its timeout or waiting for an administrator is
assessed from the resulting state, rather than automatically labelled infrastructure
failure. Evaluation must still run when trustworthy facts can be collected.
Agent declarations, clean process exit and artifact validity do not prove task
success. Proven candidate errors are failures; setup or verifier failure preserves
available facts and records incomplete assessment as infrastructure failure.

Code checks objective criteria. A semantic Judge is permitted only for justified,
labelable criteria: freeze its model, prompt and rubric; calibrate on manually
labelled examples against a threshold fixed beforehand. It receives minimal facts
in a separate context without execution powers; candidate text is data, not
instructions. Validate its output; unavailable or invalid judgement leaves the
affected criteria unknown. Judge cannot replace protected proof of an effect.

## 5. Comparison contract

Offline comparison reads native Harbor files without launching trials or
re-evaluating evidence. The same source files produce the same report.
Compare only equal model, reasoning effort, task digest, timeouts and network
conditions; otherwise label the configurations incomparable. Use fresh harness
state, sessions and memory for independent trials. Record pinned revision and
effective settings; a new revision is a new configuration. Sapiens starts without
task-specific preset specialists or memory; delegation remains its decision.
Reset task state for independent trials; repeated-step state follows the task contract.

For each task/configuration pair report trial count, pass rate over known outcomes
(`pass` / (`pass` + `fail`)), separate unknown and infrastructure counts/rates,
pass^k, failures by criterion, median duration, input/cached/output tokens, and cost
as an estimate or unknown. Record the chosen trial count, k, aggregation and
comparison decision rules before measurement; unavailable metrics remain unknown.
Separate Judge costs and disclose metric sources and observability limits.

Present a per-task table and per-level summary: average task pass rates over only
comparable tasks, and counts of Sapiens better/worse/tied under the recorded rules.
There is no single overall score. Harbor's missing reward or binary aggregate must
not silently turn unknown/infrastructure outcomes into measured agent failures.

## 6. Errors and lifecycle

All operations have finite time, tool, model and cost limits where applicable.
Pin harness/CLI/SDK versions and record available internal retry policy, usage and
observability limits; retries are part of the measured harness, not a replacement
agent loop. Fix continuation, reassessment and external-check retry limits before
measurement. Correct candidate failures only within authorized continuation and
feedback limits; uncertain invocations must not be automatically resubmitted or
treated as free work. Preserve their facts, status and cost uncertainty.

After a possibly committed write with a lost response, separate effect from agent
knowledge/process status. Do not blindly retry writes: resolve only through
permitted read-back or documented operation idempotency, otherwise retain unknown
and deny full success. One interface does not inherit another's guarantees.

On timeout/cancellation, close admission, drain accepted operations within a
deadline, stop processes and children, and verify cessation. Stopping observation
does not stop work; unconfirmed stop remains unknown. A finished chief turn does
not prove delegated work stopped. Committed effects are never declared rolled back.
Confirmed local stop does not prove remote computation or billing stopped.
Cleanup touches only the trial's owned resources and records residuals/failures.

Model runs require explicit authorization and finite limits before credential
access. API-billed runs also require an independently verified external
credential/project spending constraint. For an authorized subscription run, check
live account allowance before each trial; unavailable/exhausted remaining usage
blocks continuation. Configuration assertions and local timeouts do not enforce
provider budgets. Disclose enforcement lag and possible overrun, and agree
practical limits/reserve; do not promise mathematically zero overrun. Unknown
remaining budget blocks another trial.

## 7. Security and evidence

The agent receives only public task/tool contracts, working inputs, permitted
observations and authorized materials. Hide private tests, expectations, oracle
controls, private evaluation inputs and service documentation, personal files,
skills and other-trial memory. Deny verifier/admin access, Judge credentials,
Docker socket and the whole checkout. Enforce file/network/tool/resource rights
outside candidate code, including child processes; prompts alone do not isolate.

Untrusted candidate work executes separately from the private verifier. Collect
protected service facts through a trusted channel, bound to trial, task,
configuration, step and relevant output identity. Candidate claims, logs, evidence
or reward files cannot replace protected facts. Hashes establish identity/integrity
after receipt, not producer trust. Forbidden access earns no credit; record the
violation. Lost provenance invalidates measurement rather than proving failure.

Report conditions/tool versions, evaluated outputs, trials/steps, allowed feedback,
criteria, any task-defined score, verdict/completeness, execution/stop, costs,
errors, cleanup and unknowns with native evidence/log references. Artifact validity,
business effect, process status and assessment completeness remain distinct.
Preserve source facts once; no duplicate fact/log tree or history platform is required.
