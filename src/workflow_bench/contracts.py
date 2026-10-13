"""Checked host-side exchange values; nested JSON trees must not be mutated."""

from typing import Literal, NotRequired, TypedDict

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


class Identity(TypedDict):
    """Coordinates that bind Evidence and Evaluation to one replayed case."""

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
    """Tri-state result of one evaluation criterion with its Evidence references."""

    criterion_id: str
    status: Literal["pass", "fail", "unknown", "not_applicable"]
    value: bool | None
    reason_code: str
    evidence_refs: list[str]


class Evaluation(TypedDict):
    """Evaluated case after validation against the wire schema.

    Attributes:
        score: Value from 0 to 10, or None when no score could be established.
    """

    identity: Identity
    score: float | None
    verdict: Literal["pass", "fail", "unknown"]
    completeness: Literal["complete", "partial", "unavailable", "invalid"]
    criteria: list[Criterion]
    violations: list[str]
    errors: list[str]
    evidence_hash: str | None
    critical_violations: NotRequired[list[str]]
