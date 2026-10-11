# Architecture, Complexity & Code Quality Review

Audit date: 12 October 2026. Snapshot: `d6b65b0a2c4ce85d3f01673818b31c1d2609aef9`.

**Recommendation: proceed to WB-07 implementation without an architecture rewrite.**
Fix the small filesystem defect S1 before reusing that staging operation, and
correct the misleading documentation entry points. Other simplifications can be
made when touching the affected behavior; they do not justify a separate refactor
milestone. Actual E2 execution still requires the outstanding budget, enforcement
and authorization gates.

The implementation is moderately small. Most of its infrastructure buys required
isolation, immutable submissions, independently checked facts and honest failure
reporting. The main accidental costs are duplicated orchestration bookkeeping,
custom dependency export, positional private paths and documentation that mixes
current contracts with superseded design examples. No duplicate agent framework,
workflow interpreter, business scorer or scheduler was found.

## Scope and method

Read AGENTS, Principles, GLOSSARY, SPEC, ARCHITECTURE, ROADMAP, README and the
WB-02–WB-06 implementation tickets. Applied the installed `code-review`,
`codebase-design` and `domain-modeling` skills. The code-review skill's usual diff
scope was adapted to the requested complete HEAD snapshot; Standards and Spec
were reviewed independently by parallel reviewers. Domain terms were checked
against code without changing the glossary or adding ADRs.

There is no `.codegraph/` index. Inventory and measurements use tracked HEAD
blobs, excluding `.venv`, caches, `runs/`, the pre-existing ZIP index state and an
untracked WB-07 ticket that appeared during the audit. Source line references
below refer to this HEAD. Local installed Harbor source was also inspected to
check specific dependency behavior; it is supplementary evidence, not tracked
benchmark code.

This is a static audit. Earlier WB-04–WB-06 verification results are reported by
their tickets, not independently reproduced here. No private holdout values or
run evidence were inspected. No tests, Docker commands/experiments, model calls,
dependency installation, commits or pushes ran.

## Size and complexity hotspots

Physical lines include blanks, docstrings and data formatting; they are not a
quality threshold. There are 69 tracked files, totaling 17,147 lines.

| Category | Files | Lines |
|---|---:|---:|
| Core Python under `src/workflow_bench` | 9 | 2,623 |
| Simulator Python | 1 | 397 |
| Task verifier Python | 1 | 237 |
| Image builder Python | 1 | 130 |
| **Application/build Python subtotal** | **12** | **3,387** |
| Test Python, including conftests and controls | 18 | 4,178 |
| JSON Schema files | 9 | 1,575 |
| Markdown, including public contracts/instruction | 17 | 4,437 |
| `uv.lock` | 1 | 2,626 |
| Other tracked configuration/data/scripts | 12 | 944 |

The dependency manifest has four direct runtime dependencies and two dev
dependencies ([pyproject.toml](../../pyproject.toml):8–20). The lock contains 97
package records, including the project/dev graph; this is not 97 custom modules.
Harbor's transitive SDKs are an installation cost, not evidence of implemented
model orchestration. The simulator/verifier image uses a 14-package subset
([build.py](../../environments/build.py):35–55).

| Hotspot | Lines / branch proxy | Responsibility and assessment |
|---|---:|---|
| [`experiment._run_manual`](../../src/workflow_bench/experiment.py):109–327 | 219 / 31 | Staging, manifest, case replay callback, report. Multiple independently changing concerns are visible; keep its sequence explicit, consolidate specific repetition rather than split mechanically. |
| [`experiment._run_measurement`](../../src/workflow_bench/experiment.py):429–600 | 172 / 28 | Controlled submissions, development, selection, final evaluation. Reuses the runtime but also repeats phase setup. Main WB-07 integration pressure point. |
| [`harbor.replay_environment`](../../src/workflow_bench/harbor.py):527–688 | 162 / 8 | Mostly concrete Compose data and resource ownership. Length here does not establish complex control flow. |
| [`harbor.run_native_trial`](../../src/workflow_bench/harbor.py):192–340 | 149 / 30 | Native hooks, stop/collection trust checks, evaluation integrity and reward mapping. Substantial but earns its Interface. |
| [`Telegram.tool`](../../simapps/telegram/app.py):223–360 | 138 / 35 | Admission, arguments, effects, faults and response journal under one state owner. Separate only actual new API/UI behavior when it arrives. |
| [`Telegram.control`](../../simapps/telegram/app.py):56–190 | 135 / 31 | Host-only state machine and freeze/drain. Essential lifecycle complexity. |
| [`criteria_for`](../../tasks/t1-send-message/tests/verify.py):25–144 | 120 / 58 | Task business checks and known-failure handling under incomplete facts. Dense, but its branches implement research requirements; no proposed rule deletion. |
| [`aggregate_evaluation`](../../src/workflow_bench/evaluation.py):147–226 | 80 / 42 | Complete-set identity, missing results, critical caps and null semantics. High decision density is substantially essential. |

Branch proxy = one plus AST if/loop/except/conditional-expression decisions,
boolean alternatives and comprehensions. It includes nested function bodies and
is not formal cyclomatic complexity. Function span is inclusive source lines.
`experiment.py` (653 lines) and `harbor.py` (688) hold 51% of core Python; this
concentration identifies review surfaces, not a mandate to create more files.

Only four Python comment tokens occur in application/build code. There is no
excessive-comment problem; the historical explanation burden is in Markdown.

## Standards

### S1 — Conditional filesystem defect: staged replacement follows source links

**P2; high static confidence, not reproduced.**
[experiment.py](../../src/workflow_bench/experiment.py):124–134 copies a Task with
`symlinks=True`, then `copyfile` replaces `stage/solution/workflow.json`. A permitted
absolute symlink from that file to another file inside the original Task survives
the copy, and the replacement follows it into the source Task. The later native
validation occurs at [harbor.py](../../src/workflow_bench/harbor.py):207, after the
write. This violates the own-run resource discipline in
[Principles.md](../../Principles.md):174–176.

Supporting installed Harbor behavior: input containment allows links resolving
inside a Task (`.venv/lib/python3.12/site-packages/harbor/utils/path_safety.py`:5–24),
and native Task applies it to `solution/` (`harbor/models/task/task.py`:132–139).
The tracked T1 contains no such link. The affected Interface is direct
`run_manual(submission=...)`; `run_measurement` first reloads/validates its initial
snapshot at [experiment.py](../../src/workflow_bench/experiment.py):442–445, which
rejects this absolute-link scenario earlier. This is not evidence of a candidate
escape in the existing T1.

Reject redirected replacement paths, including a linked parent, before writing.
Do not add a filesystem framework or change artifact acceptance semantics.

### S2 — Documented progress logging is absent during long awaits

**P3; proven standards omission.**
[Principles.md](../../Principles.md):191–194 requires a phase INFO approximately
every 30 seconds. [harbor.py](../../src/workflow_bench/harbor.py):273–277 awaits
the whole Trial, including the replay preparation callback, without a periodic
Workflow Bench progress message. [execution.py](../../src/workflow_bench/execution.py):
238–265 similarly logs replay start and then awaits import/execute. Configured
finite limits can exceed 30 seconds. External logs exist, but do not implement
the specified phase-progress behavior. Add a small bounded log update at these
waits if needed; no monitoring subsystem.

### S3 — Possible Duplicated Code: cancellation/deadline ownership

**Design judgment, not a defect.**
[experiment.py](../../src/workflow_bench/experiment.py):43–106 and 611–653 repeat
the current-task watcher, pre-cancel check, total timeout and watcher cleanup.
Error reporting and cancellation return semantics differ. Consolidate only the
shared watcher/deadline mechanics if WB-07 would otherwise add a third copy;
retain those differences. This is real repeated meaning under
[Principles.md](../../Principles.md):36–38, not a file-length complaint.

### S4 — Possible duplicated facts: execution serialization

**Design judgment, not a trust defect.**
[execution.py](../../src/workflow_bench/execution.py):310 persists execution facts;
[experiment.py](../../src/workflow_bench/experiment.py):242 writes the same result
to staged verifier inputs and :258 embeds it in the report. The verifier reads
the staged copy ([verify.py](../../tasks/t1-send-message/tests/verify.py):173).
[Principles.md](../../Principles.md):178–180 prefers source facts once and reports
with refs. Keep the emergency persistence on interrupted execution and the
required cross-process verifier transfer; consider replacing the full report
embedding with a reference. Blindly deleting the first write would lose failure
diagnostics.

**Standards summary:** two conditional/proven defects and two heuristic findings.
Worst defect: S1, source-Task mutation through staged replacement.

## Spec

**No proven runtime violation was found in the completed WB-02–WB-05 scope or
implemented WB-06 methodology.** This is a source-review conclusion, not a new
integration certification. Missing Codex, MCP exploration, UI, Sapiens and Judge
are scheduled work, not scope defects. WB-06 is still IN PROGRESS
([ROADMAP.md](../../ROADMAP.md):43), and an accepted preflight explicitly leaves
execution/enforcement disabled ([cli.py](../../src/workflow_bench/cli.py):66–73).

### D1 — Current architecture documentation retains superseded status/contracts

**Proven documentation defect; low runtime risk.**
[ARCHITECTURE.md](../../ARCHITECTURE.md):10–11 says §10 is not implemented;
:919–938 retains the design-session statement that E1–E5 were not run and the
signatures do not exist. Its implemented sections at :1205–1245 and :1374–1417,
[harbor.py](../../src/workflow_bench/harbor.py):192–340,
[experiment.py](../../src/workflow_bench/experiment.py):429–600 and the WB-04/05
DONE tickets show that those statements need explicit historical scoping.
Do not turn them into claims that all hosts/profiles are now verified.

The same document has two §10.6 headings (:1298, :1374), and a substantial draft
T1 example (:629–872) duplicates the real Task while advertising `:spike` images
and null policy. [README.md](../../README.md):103 links to
`docs/reviews/REMEDIATION_PLAN.md`, absent from HEAD. These are concrete navigation
and current-truth problems, not objections to long documents alone.

Replace stale live status/signature descriptions with current Interface summaries
and links to implementation tickets. Replace redundant draft fixture listings
with links to the real Task/public contracts. Preserve versioned verification
limitations and the reasoning needed to understand the trust seam.

**Spec summary:** zero proven runtime findings; one documentation finding, D1.
Worst issue on this axis: ambiguity between implemented contracts and historical
design. Historical WB-05 null-score statements remain valid for that stage and
should not be rewritten as WB-06 measurement results.

## Actual responsibilities and Task-first separation

| Responsibility | Actual source evidence | Conclusion |
|---|---|---|
| Definition | [definition.py](../../src/workflow_bench/definition.py):202–273 loads native Task; :276–332 exports an explicit snapshot. | Hides containment/disclosure complexity; no alternate Task registry or lifecycle. |
| Experiment | [experiment.py](../../src/workflow_bench/experiment.py):198–273 creates identities and routes cases; :551–576 selects before final replay. | Owns sequence/policy rather than Telegram correctness. |
| Execution | [execution.py](../../src/workflow_bench/execution.py):152–183 binds one literal; :205–317 borrows Harbor handles for n8n. | No hidden expected/state injection, business repair or second workflow language. |
| Evaluation | [evaluation.py](../../src/workflow_bench/evaluation.py):92–226 checks criteria/complete-set identity and reads rubric parameters. | No runtime calls; generic scoring rather than Telegram branches. |
| Application/Task | [app.py](../../simapps/telegram/app.py):34–54 owns state; [verify.py](../../tasks/t1-send-message/tests/verify.py):25–144 owns business checks. | Correct ownership direction. API/UI sharing is a future extension, not yet demonstrated. |
| Harbor binding | [harbor.py](../../src/workflow_bench/harbor.py):192–340, 451–688 owns native lifecycle, stop, topology and transport. | A deep concrete integration Module, not a pass-through wrapper. |

The import graph has no runtime core import of Telegram or a Composer integration.
Definition imports native Harbor Task/parser; this is reuse of the chosen Task
format. Evaluation imports only common contracts/data. Execution's Harbor import
is TYPE_CHECKING-only (:33–34), so the Harbor-to-Evaluation direction introduces
no runtime import cycle. Three responsibilities do not require three source files.

Human intent is the seven-line [instruction.md](../../tasks/t1-send-message/instruction.md):
3–7. Technical artifact requirements live in
[workflow.md](../../src/workflow_bench/resources/workflow.md):1–31 and
[composer.md](../../src/workflow_bench/resources/composer.md):1–11. Public export
uses the six-role allowlist in [contracts.py](../../src/workflow_bench/contracts.py):
19–28; it excludes rubric, cases, solution, task config and developer instructions.
Private state goes to reset (:223–230), input to replay (:236–238), and expected
to staged verifier input (:210–217) in `experiment.py`. Feedback projects allowed
IDs/status/reason codes (:384–409); selection is persisted before final (:565–568).

Task-owned size/points/cap come from rubric, not a duplicated T1 constant in core
([evaluation.py](../../src/workflow_bench/evaluation.py):165, 199–202). The fixed
two-attempt policy in [experiment.py](../../src/workflow_bench/experiment.py):346,
417, 462, 611 and [cli.py](../../src/workflow_bench/cli.py):70,107 is the explicitly
approved WB-06 slice. It becomes maintenance debt if copied into future generic
flow; it is not currently an unrequested default or reason to introduce a policy
framework.

## Dependency overlap and essential versus accidental complexity

| Mechanism | Keep / simplify | Evidence and reason |
|---|---|---|
| Harbor Task, Trial, collection and separate verifier | Keep native implementation. | [harbor.py](../../src/workflow_bench/harbor.py):207–277 calls these directly. Installed Harbor `trial/single_step.py`:38–59,88–117 owns the native order; there is no copied Trial here. |
| Stop deadlines and residual inspection | Keep while pinned deficiency remains. | [harbor.py](../../src/workflow_bench/harbor.py):40–115 wraps native cleanup and verifies labels. Installed `environments/docker/docker.py`:767–789 handles TimeoutError but not external CancelledError; :1183–1212 includes best-effort stop behavior. Stock return alone does not prove quiescence. |
| Native n8n execution/JS runner | Keep; no substitute interpreter. | [execution.py](../../src/workflow_bench/execution.py):249–265 calls native CLI; [harbor.py](../../src/workflow_bench/harbor.py):566–606 uses the external runner. Validator restricts the benchmark profile rather than reimplementing node execution. |
| Validation/binding/claim extraction | Keep benchmark-specific parts. | [execution.py](../../src/workflow_bench/execution.py):45–183 enforces immutable file/profile/one input slot; :186–202,277–291 parses the chosen CLI output. An importer cannot replace disclosure/profile policy. No alternative stock extraction route was verified in this audit. |
| Independent criteria and score | Keep. | [verify.py](../../tasks/t1-send-message/tests/verify.py):182–218 uses generic Evaluation. [harbor.py](../../src/workflow_bench/harbor.py):314–321 recomputes the same aggregate for integrity, not a second formula. Harbor reward parsing cannot replace Task semantics or null handling. |
| Locked dependency traversal | Replace with existing uv export after builder validation. | [build.py](../../environments/build.py):35–55 manually walks `uv.lock` and emits requirements/hashes. Offline frozen uv export produced identical 14-package names/versions and the identical 663-hash set. This is the clearest dependency feature duplicated by custom code. |
| Repeated profile export/oracle delivery | Reduce phase preparation opportunistically. | [experiment.py](../../src/workflow_bench/experiment.py):440 exports a profile; development/final call `run_manual` (:530,568), which exports again (:121), stages a full Task (:124) and runs oracle (:276). One successful controlled measurement performs three exports and two oracle trials for an already supplied file. Replays/verifiers themselves remain necessary. |

No supported Harbor feature was shown to replace the outer research policy:
multiple fresh cases per immutable version, approved feedback and selection
before holdout differ from simply running/repeating a native Trial. Do not replace
that policy with stock reward averaging or invoke the Composer again on final.

Portability is adequate for the documented POSIX/Linux-container environment.
Configuration owns images/timeouts/ports ([cli.py](../../src/workflow_bench/cli.py):
17–22); published host control ports are dynamic and loopback-bound
([harbor.py](../../src/workflow_bench/harbor.py):560,652–667). Builder constants
are pinned reproducibility inputs and emitted editable technical limits
([build.py](../../environments/build.py):13–17,97–116). They are not compulsory
fixed host ports. Signal handling (:117–118 in CLI) and POSIX file flags
(:57–59 in Execution) do not establish Windows-host support. No user-specific
absolute path was found in application/build Python.

## Ranked simplification opportunities

Risk means risk to existing WB-04–WB-06 behavior; effort is relative, not an
estimate of elapsed time. These are recommendations only; nothing is changed.

| Rank | Concrete action | Impact | Risk | Effort | Timing |
|---|---|---|---|---|---|
| 1 | Fix redirected staged workflow replacement (S1), with an original-Task-unchanged regression through the existing staging Interface. | High correctness benefit for a small change | Low | Small | Before reusing this operation in WB-07 |
| 2 | Correct live architecture status, duplicate section numbering and broken README link; replace redundant draft T1 examples with real contract links (D1). | High navigation/maintenance benefit | Low if requirements/evidence retained | Small–medium | At WB-07 start; no document redesign |
| 3 | Delete the custom lock traversal/requirements serializer in favor of uv's existing exporter, preserving the lean image dependency set and hashes. | Medium; removes lock-format maintenance | Low–medium; image build still needs verification | Small | Optional independent maintenance change |
| 4 | Reuse one snapshotted app profile/public material set across controlled phases; avoid treating replay of an accepted version as another composition. | Medium runtime and future integration benefit | Medium; lifecycle/hash semantics matter | Medium | While connecting WB-07, not a prerequisite rewrite |
| 5 | Consolidate cancellation watcher/deadline mechanics only if another caller would repeat them (S3); add the required progress messages (S2). | Medium maintenance/observability benefit | Medium for cancellation, low for logging | Small–medium | When implementing Composer waits |
| 6 | Replace positional `private_paths[0/1/2]` knowledge with explicit named fields in the existing DTO. | Medium locality benefit | Low–medium; affects callers/snapshots | Small | When those paths next change |
| 7 | Use authoritative execution refs in summaries while preserving interrupted persistence and verifier transport copies (S4). | Low storage/consistency benefit | Medium if interrupted facts are lost | Small–medium | Defer until report work |

Rank 3 feasibility command actually run, capturing stdout in memory:

```sh
uv export --frozen --offline --no-cache --no-dev --no-emit-project --prune harbor --format requirements.txt
```

Exit 0; package names/versions and the hash set match the current builder's
closure. No image build or pip-install equivalence was tested. A future builder
should assert lock consistency rather than silently refreshing dependencies.

Rank 6 evidence: Definition constructs an ordered tuple at
[definition.py](../../src/workflow_bench/definition.py):228–233, interprets it at
:54–56, and Experiment repeats its meanings at :137,172–177,448,471–477. Named
fields in `TaskMaterials` would remove this scattered ordering contract without
adding a repository/service/registry.

Two smaller clarity opportunities should accompany future report work:

- `tool_calls` counts every admission-stage event
  ([experiment.py](../../src/workflow_bench/experiment.py):249–251), including
  rejected events ([app.py](../../simapps/telegram/app.py):264–269), while
  [ARCHITECTURE.md](../../ARCHITECTURE.md):1415 describes accepted counts. Define
  it as observed requests or count admitted events explicitly. Current score is
  unaffected; this is a metric-definition mismatch, not evidence of reward bias.
- Measurement root completeness uses only the final report
  ([experiment.py](../../src/workflow_bench/experiment.py):584), although earlier
  phase reports can retain cleanup errors/residuals (:285–290). Surface those at
  the root without changing business score/selection. References already retain
  them (:539,595). A residual stopped volume/frozen simulator alone does not prove
  invalid facts or unconfirmed runtime stop; do not invent such a scoring gate.

## Documentation maintenance cost

| Document | Lines | Content-specific assessment |
|---|---:|---|
| ARCHITECTURE | 1,417 | Highest duplication: implemented descriptions coexist with draft signatures/examples and old verification status. See D1; retain trust/lifecycle explanations. |
| SPEC | 481 | Contains substantive product/research constraints; do not shorten by removing null semantics, public/private separation or acceptance criteria. T1 methodology already links to WB-06. |
| WB-06 ticket | 469 | Combines agreed methodology, old proposals, implementation evidence and corrections. Keep the methodology/evidence identifiable; label superseded proposal wording explicitly rather than repeat it as current contract. |
| README | 399 | Current commands coexist with several historical test counts (101–108,385). Link older counts/results to tickets; retain the current reproducible commands and prerequisites. |
| WB-05 / WB-04 tickets | 265 / 239 | Negative results, subsequent fixes and verification limits are useful research provenance, not disposable narrative. Avoid copying their evidence tables into architecture/README. |
| ROADMAP / Principles | 218 / 216 | Legitimate distinct owners: transition criteria versus engineering rules. Duplication is reduced with links, not by merging them. |

Historical WB-01 and PRODUCT_REVIEW are explicitly non-authoritative
([AGENTS.md](../../AGENTS.md):13–14;
[ARCHITECTURE.md](../../ARCHITECTURE.md):906–912). They are not runtime
dependencies. Their detailed obsolete implementation instructions can eventually
be replaced by a short historical pointer after preserving relevant rationale
and fixing inbound links; deletion is not a WB-07 prerequisite. Do not discard
failed experiments, regenerate holdout, or rewrite earlier evidence as success.

## What must remain unchanged

- Immutable accepted bytes/hash and the single data-only binding replacement;
  no repair of candidate business logic (Execution:45–85,152–183).
- Fresh simulator state/capability and n8n database per case, isolated external
  runner, separate clean non-root verifier and no private mounts/admin secrets
  (Harbor:355–427,527–688; Task `tests/test.sh`:3–14).
- Revoke/freeze/drain, observed stop, finite deadlines, owned-resource cleanup,
  residual reporting and no automatic retry of unknown effects
  (Harbor:80–115,451–483; Execution:292–310).
- Independent Task-owned business checks/rubric, identity/evidence/reward
  integrity, known fail retained with null score, and no missing-as-zero
  (Evaluation:60–89,119–144,159–226; Harbor:295–332).
- Explicit public export, safe feedback, selection before holdout, no final
  feedback or re-selection (Definition:276–332; Experiment:384–419,551–576).
- Existing WB-04–WB-06 positive/negative controls and honest historical results;
  no expected-output changes to suit a candidate. Audit does not certify them
  afresh or mark WB-06 DONE.

## WB-07 and future tasks

The present seams are sufficient for a narrow WB-07: extend the native Harbor
agent configuration where oracle is currently fixed
([harbor.py](../../src/workflow_bench/harbor.py):221–224), prepare clean Composer
materials/exploration, and preserve accepted-artifact replay/selection. Use the
stock Codex adapter; do not create a Composer hierarchy, HTTP model bridge or
another verifier/runtime lifecycle. E2 must establish real exploration, isolated
home/config/session state, provider egress and finite credential limits, raw
usage and child-process stop ([ROADMAP.md](../../ROADMAP.md):96–107).

Future UI should extend the one application state owner rather than clone
Telegram state; T2–T4 criteria remain in their Task directories. Generalize the
bounded attempt configuration when WB-12 requires it, rather than spreading the
current T1 literals. Task/app independence is structurally plausible but not yet
proven by the planned WB-14 real controls (:172–176 in ROADMAP).

Proceed with WB-07 implementation, carrying S1 and documentation corrections as
small concrete work items. The case for a broad simplify-first architecture
project is not supported by this audit. Model execution remains blocked until
its actual required approvals/enforcement are satisfied.

## Commands and verification performed in this audit

- `git rev-parse HEAD`, `git status --short --untracked-files=all`,
  `git ls-tree -r --name-only HEAD`, `git show HEAD:<path>` and `git log -8 --oneline`:
  pinned HEAD, distinguished user/untracked state and measured the committed snapshot.
- `test -d .codegraph`: absent; ordinary source reads/searches were used.
- `rg`, `cat`, `sed` and `nl`: inspected source, project rules, relevant tickets
  and specific installed Harbor lifecycle/path/reward implementation.
- Inline `.venv/bin/python` AST/lock/Markdown-link audits: produced the size,
  hotspot/import results, missing README target and duplicate §10.6 locations.
  These scripts parsed text; they did not import/execute benchmark code.
- `uv export --help` and the frozen offline export above: exit 0; dependency
  subset names/versions/hashes compared in memory, with no output file.
- `git diff --check`: exit 0. The report's no-index whitespace check against
  `/dev/null` returned 1 for the new-file difference, with no whitespace diagnostics.
  Report links resolve and all other tracked file bytes match HEAD.
  Final report/reference and Git diff checks are static. No pytest/Ruff suite,
  Docker, models, image build, provider access or fresh integration verification
  is claimed. The only intended repository write is this report.
