# Workflow submission contract — 1.0

Submit one UTF-8 `{artifact}` containing a native n8n workflow, parameterized
for the Task's input schema. Reuse the same business logic for fresh inputs.
`{workflow_schema}` checks only the common JSON envelope. Accepted native node
types, typeVersion/options, bindings and runtime compatibility must be established
by the runtime profile before execution; this envelope does not authorize execution.

Use ordinary nodes with roles `BenchInput` (input parameters and technical tool
bindings) and terminal `BenchResult` (completed, refused or unknown claim).
Learn application state through the permitted tools. Private expectations are
never an input. The workflow must not call an LLM, use external integrations,
credential references, pinned data or persistent state. HTTP calls target only
the supplied tool endpoint. Do not retry writes blindly when the effect is unknown.

The proposed node families are Manual Trigger, Edit Fields/Set, HTTP Request,
JavaScript Code, If and Loop Over Items. Their precise versions and permitted
options remain subject to the runtime profile; no compatibility is claimed here.
