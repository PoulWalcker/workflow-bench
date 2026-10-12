# Sanitized WhatsApp macOS AX fixtures

Sanitized AX trees and fragments used by the SimsApp UI projection. Runtime state
and actions are supplied by SimsApp; captured structure does not establish native
WhatsApp behavior. Loading these fixtures requires no desktop or model access.
`manifest.json` maps states, transitions, fragments and exact source JSON pointers.
All examples use fictional English content. Private captures are not distributed.

## Provenance and publication

The project owner made the underlying AX captures for this project and authorized
publication of this sanitized package on 2026-10-12. These are project-owned
captures, not an imported third-party dataset. This permission covers the reviewed
package only; it does not license Blindly or WhatsApp software, trademarks or other
third-party material. No separate dataset redistribution conditions were identified.

The publication allowlist is exactly the 40 assets in `manifest.json` plus
`manifest.json`, `check.py` and this README. The root `.gitignore` excludes any
other fixture files, including original captures, caches and experiment outputs.
It also excludes the private source directory. No screenshots, binaries, accounts,
credentials or original message text are part of this package.

Review covered every distinct asset string, JSON key and scalar field, the
manifest, checker and README. Names, messages and dates are declared fictional;
identifiers use one sentinel, PIDs are zero, and paths are AX indices or relative
source references. Geometry retains native sizes and relative positions, including
offscreen content; it may reveal layout characteristics. The ignored Python
bytecode cache is not a publishable asset.

The publication checkout did not contain the 28 selected private source files.
The offline checker verifies the stored structural and sanitized-content digests,
fragment relationships and allowlist; source fidelity cannot be re-established
independently until the original selected captures are available privately.

## Selected evidence

Seven complete Blindly trees retain every node, child order and dictionary key,
including menus, offscreen history and underlying chat content beneath results:

| Fixture | Private source under `docs/research/blindly-whatsapp/` | Nodes |
|---|---|---:|
| `chat-list` | `01-activated/tree.json` | 279 |
| `search-focused` | `07-search-focus-after/tree.json` | 334 |
| `results-zero` | `10-query-settled-after/tree.json` | 335 |
| `results-many` | `16-search-brand-fresh-after/tree.json` | 355 |
| `result-sheet` | `17-open-search-result-after/tree.json` | 286 |
| `list-cleared` | `20-clear-search-final-after/tree.json` | 328 |
| `conversation` | `25-composer-focus-after/tree.json` | 339 |

Only 28 source JSON files were selected. The other reads cover search/composer
focus, two chat inspections, two history inspections/actions, root attributes,
read-only AX relation probes and accepted/rejected command results. There are 40
assets: seven trees, 21 observations and twelve exact subtree fragments. The
manifest is the authoritative list; no screenshots, environment/account dump,
raw stderr, research provenance dump or entire capture directory was copied.

Blindly's tree records omit actions and attribute inventories. Those remain in
separate `observations/` records; they were not injected into tree nodes. The direct
AX relation probes preserve relation order, role counts, errors and settable flags.
An attribute name such as `AXParent` or `AXLinkedUIElements` establishes availability
in that inspection; its target value was not captured and remains UNKNOWN.
Reads were separate live operations. A find path can differ from the earlier tree;
paths are capture-local indices, never stable selectors or proven identity links.

## Fidelity and transformations

**OBSERVED:** hierarchy, roles/subroles, actions (including custom action strings),
attribute names, enabled/selected/focused flags, types, missing fields, empty values,
truncation flags, relation results and geometry relationships are preserved.
All seven selected tree envelopes report `truncated=false`; this establishes only
the serializer's bounded capture status, not complete application coverage.
Public English labels retain their observed leading U+200E direction mark.

**RECONSTRUCTED:** the research copies had already replaced names, messages,
dates, identifiers and many control/menu labels with one `[redacted]` value.
English identities therefore represent an explicit fictional scenario, not a
recoverable mapping to real people. Alice Morgan, Bob Carter and Emma Wilson recur
in the examples; messages include “Hello Alice!” and “Can we meet tomorrow?”.
Repeated list positions and related search snapshots use consistent fictional
content. Unknown redacted controls/menu items receive “Unspecified …” labels;
these do not establish their original purpose. Message bodies and timestamps live
in `description` where observed; empty `value` fields remain empty. Missing draft
values remain missing. Fictional text need not fit the original measured geometry.

The two retained research queries became `Missing Fictional Alice Contact` and
`Alice Mo`. Their lengths remain 31 and 8, preserving observed character counts.
Dates/times are fictional January 2026 / 09:30 examples. PIDs stay at the existing
anonymous `0`; every redacted identifier becomes `fixture-redacted-id`. Keeping
one sentinel preserves the research's collapsed equality class and introduces no
fictional unique IDs. Original ID distinctness is UNKNOWN. AX index paths stay
unchanged. Coordinates are translated by x+100/y+61, placing the captured window
origin at (100,100); sizes, offscreen positions and all relative distances remain
observed layout data. No real filesystem path, account, token or process ID is
retained in fixture data. Source references are repository-relative filenames.

**UNKNOWN:** complete exactly-one-results screen, original private identity links,
redacted control meanings, visibility/selectability of every underlying node,
composer draft write, composer Send appearance/enabling, Send effect, persistence,
message direction/delivery semantics, scrolling completion and full WhatsApp parity.
The populated result tree has three chat candidates, one candidate in an unlabelled
group and four message candidates. `single-result` extracts one actual candidate
for reuse; `results-1-fragment` is RECONSTRUCTED isolation, not a captured one-result
screen. No siblings were pruned to manufacture such a full tree.

The empty composer exposes Voice message. `send-menu-item` is an observed enabled
**AXMenuItem** titled Send, with no inspected actions; it is not a composer Send
button. The manifest leaves draft/Send transitions UNKNOWN. Pressing a search
result exposed a sheet, which was cancelled; ordinary chat opening and composer
focus were observed later. Accepted command results alone do not establish all
state effects. The manifest notes omitted intermediate steps and unavailable
immediate destination captures; its edges are research summaries, not replay rules.

## Reuse

Load plain JSON, copy the required subtree, and use the manifest's `templates`
entries to locate its parent-tree counterpart. Each fragment has explicit `slots`
with JSON pointers, default English examples and RECONSTRUCTED provenance. Change
only those text fields in a derived scenario, keeping identities/content consistent
across the row, conversation and message examples. For instance, `chat-row` and
`selected-chat-row` use Bob Carter in both `/description` and `/value`.

```python
import json
from pathlib import Path

fixtures = Path("simapps/simsapp/fixtures")  # Explicit caller-supplied package path.
row = json.loads((fixtures / "fragments/chat-row.json").read_text())
row["description"] = row["value"] = "Bob Carter: Can we meet tomorrow? 09:30"
```

Use `history-message`/`history-message-long` for repeated static-text messages,
`date-heading` for its actual nested heading layout, and `message-result` for the
observed group with message text and a separate button. Substitute whole composite
descriptions; the captures did not expose invented contact/body/timestamp fields.
Keep actions, attributes, structure, flags, role variants and empty fields intact.
`search-query` permits `/value`; keep matching character-count observations aligned.
`composer` permits its reconstructed description only: adding draft/Send behavior
requires a separately specified design. This package supplies no templating engine.
Derived scenarios must not overwrite these baseline fixtures.

## Verification

From the repository root, using the locked local environment:

```sh
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
uv run --locked --offline python simapps/simsapp/fixtures/check.py
uv run --locked --offline pytest -q tests/fast/test_simsapp_fixtures.py
```

Optional source comparison requires a separately supplied private source directory;
it is not a build/test prerequisite and must not be committed or included in images:

```sh
uv run --locked --offline python simapps/simsapp/fixtures/check.py --source-root "${AX_SOURCE_ROOT:?Set AX_SOURCE_ROOT to the private capture directory}"
```

The default checker requires no private files. It rejects undeclared strings,
non-anonymous identifiers/PIDs, structural or exact fixture drift, and fragments
that disagree with their parent subtree or declared examples. Optional local source
comparison reads only manifest-selected files/pointers, compares structural
commitments and the exact coordinate translation, and emits counts/safe codes only.
No original content or original-content hashes are written to committed outputs.
Structural commitments mask nonempty text/identity/coordinate values, while retaining
their types, empty strings and all other structure. Exact sanitized digests protect
the English baseline. The manifest and string allowlist are reviewed trusted inputs;
changing them together with fixtures requires renewed review, not an automatic
privacy proof. No finite detector can establish absence of every possible identifier.

Pytest uses synthetic fault inputs and the real sanitized package, never private
research or the desktop.
