# Code style

## Scope and authority

Read this document before changing Python code or reviewing Python changes. Its rules apply
to new code and code modified by the task, including tests. Refactor surrounding code only
when necessary for the assigned change; existing violations do not authorize a general
cleanup.

This document owns Python writing conventions. [AGENTS.md](../../AGENTS.md) owns engineering
rules, including architecture constraints, validation, error handling, logging and test gates.
Follow its links to the documents that own product requirements and interfaces.

The linked recommendations from the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
are adopted where stated below. Other Google recommendations are reference material, not
additional review requirements. Repository rules take precedence: Ruff owns mechanics and
lint tooling, typing applies to private functions too, and docstrings describe useful
contracts without repeating obvious parameters. The class criteria below are a repository
rule rather than a Google recommendation.

## Mechanical rules

`ruff format` and `ruff check`, configured in [pyproject.toml](../../pyproject.toml), own line
length, quotes, indentation, blank lines and import order. Configuration changes follow
[AGENTS.md](../../AGENTS.md#code-quality-and-portability). Use tool diagnostics for mechanical
violations; a formatting preference absent from the configuration needs a configuration
proposal rather than an invented review rule.

## Naming

Use the existing domain terms from [SPEC](../../SPEC.md) and the surrounding code. Name a
function for its action or computation, a class for its responsibility, and a variable for
what it contains. Replace generic names such as `data`, `result` or `manager` when a more
precise subject is known. Short local names are acceptable when their meaning is apparent
at the use site; use abbreviations only when established in the domain or library.

Adopt Google's [naming conventions](https://google.github.io/styleguide/pyguide.html#s3.16-naming):
`snake_case` for functions, methods, variables and modules, `CapWords` for classes, and
`UPPER_SNAKE_CASE` for constants. Prefix ordinary internal functions and methods with one
underscore. Tool checks govern overlapping rules.

Name booleans as conditions: `is_valid`, `has_errors`, `can_retry`. Prefer positive conditions
so callers can read `if not can_retry:` without a double negative. Include units when a
numeric value would otherwise be ambiguous: `timeout_seconds`, not `timeout`.

## Module and function structure

After imports, place constants and exchange types before operations that use them. Present
public operations before their private helpers. In a class, place initialization before
public operations and private methods after them. Definition-time dependencies must still
be defined before use.

Keep a function focused on one responsibility. Extract a helper when it names a distinct
operation or removes repeated meaning; keep a short, coherent sequence together when
extraction would only make the reader jump between definitions. Function length and
argument count have no arbitrary limits. Several unrelated stages, repeated parameter
groups or branches with different responsibilities are reasons to reconsider the structure.

## Functions or classes

Before adding another private helper, inspect the group it joins. Prefer a class when the
helpers serve one operation and repeatedly pass the same dependencies, configuration or
state. Give that class one responsibility, accept those shared inputs at construction, and
expose only the operations a caller needs. Keep operation-specific inputs on the method.

For example, `load_record(path, schema)`, `validate_record(record, schema)` and
`write_record(path, record, schema)` may belong to a `RecordStore` that holds `path` and
`schema`, with `read()` and `write(record)` as its public operations. An independent
`normalize_name(name)` calculation remains a function.

Moving a chain of helpers into methods is insufficient by itself: the class must reduce
what callers and internal operations need to pass or coordinate. Split unrelated
responsibilities rather than accumulating them in one class. Helper count alone is not a
criterion. The abstraction constraints in [ARCHITECTURE.md](../../ARCHITECTURE.md#not-doing)
still apply.

## Readable Python

Use early returns for empty or terminal cases so the main path remains visible. Keep a
necessary cleanup or finalization path intact when changing control flow.

Adopt these Google recommendations:

- [Comprehensions](https://google.github.io/styleguide/pyguide.html#s2.7-comprehensions): one
  `for`, at most one filter; use loops for complex work.
- [Iteration](https://google.github.io/styleguide/pyguide.html#s2.8-default-iterators-and-operators):
  iterate containers directly; use `items()` for key/value pairs.
- [Lambdas](https://google.github.io/styleguide/pyguide.html#s2.10-lambda-functions) and
  [conditional expressions](https://google.github.io/styleguide/pyguide.html#s2.11-conditional-expressions):
  keep them simple. Expand nested conditionals into statements.
- [Defaults](https://google.github.io/styleguide/pyguide.html#s2.12-default-argument-values):
  use immutable defaults or initialize per call.
- [Global state](https://google.github.io/styleguide/pyguide.html#s2.5-global-state):
  give mutable state an explicit owner.
- [Conditions](https://google.github.io/styleguide/pyguide.html#s2.14-truefalse-evaluations):
  use truthiness for emptiness and `is None` for absence.

Prefer:

```python
if timeout_seconds is None:
    timeout_seconds = default_timeout_seconds
```

Avoid:

```python
timeout_seconds = timeout_seconds or default_timeout_seconds
```

The second version silently replaces zero even when zero has a distinct meaning.

Adopt Google's [exception](https://google.github.io/styleguide/pyguide.html#s2.4-exceptions)
and [resource](https://google.github.io/styleguide/pyguide.html#s3.11-files-and-sockets)
recommendations: narrow `try` blocks, explicit input checks rather than `assert`, and context
managers for resources. Recovery policy belongs to
[AGENTS.md](../../AGENTS.md#code-quality-and-portability); ownership and timeouts belong to
[Operation and completion](../../AGENTS.md#operation-and-completion).

## Typing

Annotate parameters and returns of every new or modified function and method, including
private helpers and tests. Ordinary `self` and `cls` need no annotation. Annotate exchange
values and locals whose type cannot be inferred clearly. Public interfaces carry no `Any`.

Choose types by the operations and meaning they represent:

| Need | Type choice |
|---|---|
| Structured JSON or a dictionary contract | `TypedDict` with declared fields |
| A Python record with named fields | dataclass; use `frozen=True` when immutability is part of its contract |
| A parameter that only reads a mapping or sequence | `Mapping` or `Sequence` |
| A parameter that requires concrete container operations | The concrete container or appropriate mutable interface |
| A value that can be absent | `T \| None`, distinct from an empty value |
| Interchangeable implementations or an agreed test substitution | `Protocol` only when that need exists |

Prefer built-in generics such as `list[str]`. Adopt explicit nullable types (`T | None`) from
Google's [type annotations](https://google.github.io/styleguide/pyguide.html#s3.19-type-annotations).
Validate external values at the trust boundaries defined in `AGENTS.md` before relying on
their declared shape. A type annotation alone does not validate JSON.

The configured type checker verifies compatibility within its configuration. Annotation
coverage, meaningful names, correct exchange models and the public `Any` restriction also
require review; a successful check does not prove those conventions. Use the tools actually
configured in the project, without adding a checker as part of a style-only change.

## Docstrings and comments

Write code prose in English throughout `src/`, `tests/`, `tasks/`, `simapps/` and
`environments/`.

Every package module under `src/` carries a one-line docstring naming its subject. Public
functions, methods and classes used across modules, including CLI and Harbor entry points,
carry a summary saying what the caller gets. Explain decision-valued results: if `False`
means the run must stop, that meaning is part of the contract.

Extend a docstring when using the definition correctly requires information absent from its
name and types: units, side effects, ordering, an invariant, a result's meaning or an error
condition. This applies to private helpers too. Simple private helpers and self-explanatory
accessors need no docstring.

Use Google's [docstring sections](https://google.github.io/styleguide/pyguide.html#s3.8.3-functions-and-methods)
(`Args`, `Returns`, `Yields`, `Raises`, `Attributes`) when useful. Omit sections that repeat
names and types. For exchange types, document non-obvious field meanings or relationships
on the type.

For example:

```python
def can_retry(attempt: int, max_attempts: int) -> bool:
    """Return whether another attempt is allowed.

    Args:
        attempt: One-based number of the attempt that just finished.
    """
    return attempt < max_attempts
```

Comments explain intent the code cannot state: an external constraint, an unexpected
failure mode or a non-obvious reason for ordering. Keep implementation rationale in a
comment only when needed to understand the current code; design history and rejected
alternatives belong in documentation. Docstrings describe usage rather than implementation.

Docstrings and comments carry no decision ids, ticket ids or people's names, and do not
narrate conventions or restate adjacent code.

## Agent checklist

1. Before editing, read this document and inspect nearby code and the relevant contract.
2. While editing, apply the relevant sections to each new or modified definition; use the
   class criteria before extending a group of private helpers.
3. Before completion, inspect the scoped diff for compliance, run the configured checks
   required by `AGENTS.md` and the task, and distinguish tool results from manual review.
4. Resolve violations in the changed code. Report any remaining violation or requirement
   conflict with its location and reason; do not silently treat it as an exception.

For reviews, cite the applicable rule and affected code. Review findings must follow this
document's scope rather than request unrelated cleanup.
