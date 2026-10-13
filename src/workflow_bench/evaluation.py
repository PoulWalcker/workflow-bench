"""Read frozen Evidence and map an evaluated case to a native Harbor reward."""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from workflow_bench.contracts import Evaluation, Evidence, JsonValue
from workflow_bench.data import (
    MAX_EVIDENCE_BYTES,
    DataError,
    decode_json,
    read_bytes,
    validate_contract,
)


@dataclass(frozen=True)
class FrozenEvidence:
    """Validated Evidence with the SHA-256 of the exact bytes it was read from."""

    document: Evidence
    sha256: str


def harbor_reward(evaluation: dict[str, JsonValue]) -> dict[str, float] | None:
    """Map an already evaluated score; this function defines no scoring policy."""
    validate_contract("evaluation", evaluation)
    checked = cast(Evaluation, evaluation)
    if (
        checked["completeness"] != "complete"
        or checked["score"] is None
        or checked["errors"]
        or any(c["status"] == "unknown" for c in checked["criteria"])
    ):
        return None
    return {"reward": float(checked["score"])}


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
    """Read Evidence for the expected identity; inconsistencies raise DataError."""
    content = read_bytes(path, "evidence", limit=MAX_EVIDENCE_BYTES)
    document = decode_json(content, "evidence")
    validate_contract("evidence", document)
    evidence = cast(Evidence, document)
    if evidence["identity"] != dict(expected_identity):
        raise DataError("identity_mismatch", "evidence")
    if evidence["after"]["revision"] < evidence["before"]["revision"]:
        raise DataError("invalid_revision", "evidence")
    stages: dict[str, list[str]] = {}
    calls: dict[str, tuple[str, JsonValue]] = {}
    for seq, event in enumerate(evidence["events"], 1):
        if event["seq"] != seq or event["profile"] != expected_identity["profile"]:
            raise DataError("invalid_sequence", "evidence")
        call_stages = stages.setdefault(event["call_id"], [])
        call = (event["operation"], event["arguments"])
        if calls.setdefault(event["call_id"], call) != call:
            raise DataError("call_mismatch", "evidence")
        call_stages.append(event["stage"])
        if call_stages != ["accepted", "effect", "response"][: len(call_stages)]:
            raise DataError("invalid_sequence", "evidence")
        evidence_ref = event["details"].get("evidence_ref")
        if isinstance(evidence_ref, str):
            resolve_ref(document, evidence_ref)
    if evidence["freeze_status"] == "complete" and (
        evidence["pending_call_ids"]
        or any(len(value) != 3 for value in stages.values())
    ):
        raise DataError("incomplete_freeze", "evidence")
    return FrozenEvidence(evidence, hashlib.sha256(content).hexdigest())
