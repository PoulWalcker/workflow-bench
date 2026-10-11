# Workflow submission contract — 1.0

Submit one UTF-8 `{artifact}` containing native n8n JSON. The current T1 profile
is `n8n-2.41.5-t1-1.0`, checked by `{workflow_schema}` and the graph validator.
The file is at most 65,536 bytes and contains a safe 16-character workflow ID,
name, nodes, main connections and settings with executionOrder `v1`.

The current allowlist is Manual Trigger 1, Edit Fields/Set 3.4, JavaScript Code 2
(runOnceForAllItems), and HTTP Request 4.2 (POST, JSON body, supplied tool endpoint,
JSON response and a finite request timeout). The schema specifies the exact
permitted options. No credential references, pinned/static data, retries,
additional triggers, community packages or LLM nodes are accepted. If and Loop
Over Items are outside this first T1 profile. Profile acceptance alone does not
prove behavior or expression safety; execution is isolated by the environment.

Use one Manual Trigger connected to a Set node named `BenchInput`. Its single
assignment has name `bench`, type `object`, and a literal JSON text value
`{{"input":{{}},"tools":{{}}}}`. The binder replaces only that value with JSON text
containing the fresh `input` and `tools.base_url`/`tools.capability`. Input strings
remain data, including strings that resemble n8n expressions. All other nodes,
expressions, connections and business decisions remain exactly as submitted.
Learn application state through the permitted tools; private expectations and
previous sends are never inputs.

All nodes must be reachable and lead to the sole terminal Set node `BenchResult`.
Its assignments are exactly `status`, `reason_code`, `result`; emit a claim with
status `completed`, `refused` or `unknown`. Claims and CLI exit status are recorded
separately from the independent checks of simulator state and action history.
HTTP calls use only the supplied endpoint and bearer capability. Never retry a
write automatically: after a lost response, observe the effect through permitted
reading or report `unknown`. A server response marked sent does not prove receipt.
