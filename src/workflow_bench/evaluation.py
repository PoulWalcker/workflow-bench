"""Evaluate task criteria into Harbor verifier output and read frozen Evidence."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from workflow_bench.contracts import Criterion, Evaluation, Evidence, JsonValue
from workflow_bench.data import (
    MAX_EVIDENCE_BYTES,
    DataError,
    decode_json,
    read_bytes,
    validate_contract,
)

EVALUATION_FILENAME = "evaluation.json"
REWARD_FILENAME = "reward.json"


@dataclass(frozen=True)
class FrozenEvidence:
    """Validated Evidence with the SHA-256 of the exact bytes it was read from."""

    document: Evidence
    sha256: str


def evaluate(
    criteria: Sequence[Criterion], *, errors: Sequence[str] = ()
) -> Evaluation:
    """Derive the verdict and completeness from task-owned criterion results.

    A proven violation is ``fail`` even when other criteria are unknown;
    otherwise any unknown criterion or verifier error makes the verdict
    ``unknown``. Completeness depends only on missing facts, never on the
    candidate failing. Invalid or duplicate criteria raise ``DataError``.
    """
    # Read without indexing so malformed criteria reach schema validation below.
    statuses = {criterion.get("status") for criterion in criteria}
    if "fail" in statuses:
        verdict = "fail"
    elif "unknown" in statuses or errors:
        verdict = "unknown"
    else:
        verdict = "pass"
    is_complete = "unknown" not in statuses and not errors
    evaluation: Evaluation = {
        "verdict": verdict,
        "completeness": "complete" if is_complete else "partial",
        "criteria": list(criteria),
        "errors": list(errors),
    }
    validate_contract("evaluation", cast(JsonValue, evaluation))
    identifiers = [criterion["criterion_id"] for criterion in criteria]
    if len(set(identifiers)) != len(identifiers):
        raise DataError("duplicate_criterion", "evaluation")
    return evaluation


def harbor_reward(evaluation: Evaluation) -> dict[str, float] | None:
    """Return Harbor's native reward, or None when assessment is incomplete.

    Only a complete evaluation has a reward: 1.0 for ``pass``, 0.0 for
    ``fail``. Missing reward must never be read as a measured zero.
    """
    if (
        evaluation["completeness"] != "complete"
        or evaluation["errors"]
        or any(c["status"] == "unknown" for c in evaluation["criteria"])
    ):
        return None
    return {"reward": 1.0 if evaluation["verdict"] == "pass" else 0.0}


def write_evaluation(
    verifier_dir: Path, criteria: Sequence[Criterion], *, errors: Sequence[str] = ()
) -> Evaluation:
    """Write ``evaluation.json`` and, only when complete, ``reward.json``.

    Without ``reward.json`` Harbor records a verifier error, so an incomplete
    assessment is never reported as a measured agent score.
    """
    evaluation = evaluate(criteria, errors=errors)
    (verifier_dir / EVALUATION_FILENAME).write_text(json.dumps(evaluation) + "\n")
    reward = harbor_reward(evaluation)
    if reward is not None:
        (verifier_dir / REWARD_FILENAME).write_text(json.dumps(reward) + "\n")
    return evaluation


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
