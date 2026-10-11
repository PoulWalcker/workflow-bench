"""Validate frozen facts and criterion references; WB-04 has no scoring policy."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from workflow_bench.contracts import JsonValue
from workflow_bench.data import (
    MAX_EVIDENCE_BYTES,
    DataError,
    decode_json,
    read_bytes,
    validate_contract,
)


@dataclass(frozen=True)
class FrozenEvidence:
    document: dict[str, JsonValue]
    sha256: str


def resolve_ref(document: JsonValue, reference: str) -> JsonValue:
    """Resolve a JSON pointer within one bundle, including escaped keys."""
    if not reference.startswith("/"):
        raise DataError("invalid_reference", "evidence")
    current = document
    try:
        for part in reference[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if isinstance(current, list):
                if not key.isdecimal() or str(int(key)) != key:
                    raise ValueError()
                current = current[int(key)]
            elif isinstance(current, dict):
                current = current[key]
            else:
                raise ValueError()
        return current
    except (KeyError, IndexError, ValueError):
        raise DataError("invalid_reference", "evidence") from None


def read_evidence(
    path: Path, *, expected_identity: Mapping[str, str]
) -> FrozenEvidence:
    content = read_bytes(path, "evidence", limit=MAX_EVIDENCE_BYTES)
    document = decode_json(content, "evidence")
    validate_contract("evidence", document)
    if document["identity"] != dict(expected_identity):
        raise DataError("identity_mismatch", "evidence")
    stages: dict[str, list[str]] = {}
    for seq, event in enumerate(document["events"], 1):
        if event["seq"] != seq or event["profile"] != expected_identity["profile"]:
            raise DataError("invalid_sequence", "evidence")
        call_stages = stages.setdefault(event["call_id"], [])
        call_stages.append(event["stage"])
        if call_stages != ["accepted", "effect", "response"][: len(call_stages)]:
            raise DataError("invalid_sequence", "evidence")
        if event["details"].get("evidence_ref"):
            resolve_ref(document, event["details"]["evidence_ref"])
    if document["freeze_status"] == "complete" and (
        document["pending_call_ids"]
        or any(len(value) != 3 for value in stages.values())
    ):
        raise DataError("incomplete_freeze", "evidence")
    return FrozenEvidence(document, hashlib.sha256(content).hexdigest())


def assemble_evaluation(
    criteria: tuple[dict[str, JsonValue], ...],
    *,
    rubric: dict[str, JsonValue],
    execution: dict[str, JsonValue],
    evidence: FrozenEvidence,
) -> dict[str, JsonValue]:
    validate_contract("rubric", rubric)
    validate_contract("execution", execution)
    ids = [criterion["criterion_id"] for criterion in criteria]
    expected_ids = [criterion["id"] for criterion in rubric["criteria"]]
    if len(set(ids)) != len(ids) or set(ids) != set(expected_ids):
        raise DataError("criterion_mismatch", "evaluation")
    for criterion in criteria:
        validate_contract("criterion", criterion)
        for reference in criterion["evidence_refs"]:
            resolve_ref(evidence.document, reference)
    complete = (
        evidence.document["freeze_status"] == "complete"
        and execution["stop_confirmed"]
        and all(c["status"] != "unknown" for c in criteria)
    )
    result = {
        "identity": evidence.document["identity"],
        "score": None,
        "verdict": "unknown",
        "completeness": "complete" if complete else "partial",
        "criteria": list(criteria),
        "violations": evidence.document["violations"],
        "errors": [],
        "evidence_hash": evidence.sha256,
    }
    validate_contract("evaluation", result)
    return result
