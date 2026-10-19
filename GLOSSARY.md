# Workflow Bench glossary

Canonical domain language for measuring Sapiens on autonomous business tasks
and optionally comparing agent configurations.
Product requirements belong in [SPEC](SPEC.md).

## Language

<a id="task"></a>

**Task**:
A business benchmark problem with public intent and constraints, an environment,
private expectations and criteria, and a control demonstrating solvability.
_Avoid_: Implementation ticket

<a id="level"></a>

**Level**:
A task category determined by the environment provided to the agent, independent
of the strategy the agent chooses.

<a id="horizon"></a>

**Horizon**:
The single or repeated execution dimension of a task; repeated tasks assess results
across successive occasions rather than one isolated occasion.

<a id="observation-window"></a>

**Observation window**:
A task-owned period after the agent's setup turn during which scheduled inputs and
observations reveal whether behavior continues without the agent present.

<a id="harness"></a>

**Harness**:
The agent system that directs model use and tool interactions to pursue a task,
including its orchestration and execution behavior.

<a id="configuration"></a>

**Configuration**:
The complete measured combination of harness revision, model, effective settings,
initial agent state, environment and limits.
_Avoid_: Model alone

<a id="trial"></a>

**Trial**:
One bounded execution and assessment of one task with one configuration; a repeated
task may contain multiple steps within its trial.
_Avoid_: Run

<a id="outcome"></a>

**Outcome**:
The trial classification: `pass` for proved satisfaction of required criteria,
`fail` for a proved violation, `unknown` for insufficient trustworthy facts, or
`infra_error` for setup or assessment infrastructure failure.

<a id="evidence"></a>

**Evidence**:
Observable task facts with protected provenance, tied to the execution and result
being assessed; candidate assertions alone are not evidence of an effect.

<a id="evaluation"></a>

**Evaluation**:
The independent assessment of evidence against task criteria, yielding criterion
results, a verdict and assessment completeness.

<a id="verdict"></a>

**Verdict**:
The `pass`, `fail` or `unknown` judgement of task results, distinct from process
status, infrastructure classification, a numeric score or one individual effect.

<a id="criterion"></a>

**Criterion**:
One task-owned requirement against which observable results are assessed,
with its applicability and success conditions specified in advance.

<a id="readiness"></a>

**Readiness**:
The ready/not-ready determination that a task is well formed, solvable and checked
reliably enough to admit measured agent trials.

<a id="comparison"></a>

**Comparison**:
The offline reporting stage for one configuration's saved trial outcomes and costs,
optionally assessing differences between configurations under equal conditions;
unequal conditions make that comparison incomparable.

<a id="simulated-service"></a>

**Simulated service**:
A controlled substitute for an external application, exposing permitted observations
and actions over real mutable state within the benchmark environment.

<a id="step"></a>

**Step**:
One successive occasion within a repeated task. A task may invoke the agent at
each step or assess scheduled effects after one setup turn.
