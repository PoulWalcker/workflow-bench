"""Checked host-side exchange values; nested JSON trees must not be mutated."""

from typing import Literal, TypedDict

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


class Identity(TypedDict):
    """Coordinates that bind Evidence to one replayed case."""

    run_id: str
    attempt_id: str
    replay_id: str
    case_id: str
    profile: str
    artifact_hash: str
    profile_hash: str


class StateSnapshot(TypedDict):
    """Simulator state at one revision."""

    revision: int
    state: dict[str, JsonValue]


class EvidenceEvent(TypedDict):
    """One stage of one tool call.

    Attributes:
        seq: One-based position of the event in the bundle.
        details: Stage-specific fields fixed by the wire schema.
    """

    seq: int
    call_id: str
    actor: Literal["workflow"]
    profile: str
    operation: str
    arguments: dict[str, JsonValue]
    stage: Literal["accepted", "effect", "response"]
    details: dict[str, JsonValue]
    timestamp: float


class Evidence(TypedDict):
    """Frozen Evidence bundle after validation against the wire schema."""

    schema_version: Literal["1.0"]
    identity: Identity
    before: StateSnapshot
    after: StateSnapshot
    events: list[EvidenceEvent]
    violations: list[str]
    freeze_status: Literal["complete", "incomplete"]
    pending_call_ids: list[str]


class Criterion(TypedDict):
    """Result of one task-owned criterion.

    Attributes:
        status: ``fail`` only for a proven violation; ``unknown`` when the
            facts needed to decide are missing or untrusted.
        reason_code: Safe code explaining the status, never candidate content.
    """

    criterion_id: str
    status: Literal["pass", "fail", "unknown", "not_applicable"]
    reason_code: str


class Evaluation(TypedDict):
    """Verdict and assessment completeness derived from criterion results.

    Attributes:
        completeness: ``complete`` when no criterion is unknown and no
            verifier error was recorded; otherwise ``partial``.
        errors: Safe codes of verifier problems that limited the assessment.
    """

    verdict: Literal["pass", "fail", "unknown"]
    completeness: Literal["complete", "partial"]
    criteria: list[Criterion]
    errors: list[str]
