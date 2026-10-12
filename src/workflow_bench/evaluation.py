"""Evaluate frozen criteria and apply the Task-owned complete-set policy."""

import hashlib
import re
from collections.abc import Mapping
from copy import deepcopy
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


def harbor_reward(evaluation: dict[str, JsonValue]) -> dict[str, float] | None:
    """Map an already evaluated score; this function defines no scoring policy."""
    aggregate = "cases" in evaluation
    validate_contract("aggregate" if aggregate else "evaluation", evaluation)
    cases = evaluation["cases"] if aggregate else [evaluation]
    if (
        evaluation["completeness"] != "complete"
        or evaluation["score"] is None
        or evaluation["errors"]
        or any(c["status"] == "unknown" for result in cases for c in result["criteria"])
    ):
        return None
    return {"reward": float(evaluation["score"])}


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
    if document["after"]["revision"] < document["before"]["revision"]:
        raise DataError("invalid_revision", "evidence")
    stages: dict[str, list[str]] = {}
    calls: dict[str, tuple[str, JsonValue]] = {}
    for seq, event in enumerate(document["events"], 1):
        if event["seq"] != seq or event["profile"] != expected_identity["profile"]:
            raise DataError("invalid_sequence", "evidence")
        call_stages = stages.setdefault(event["call_id"], [])
        call = (event["operation"], event["arguments"])
        if calls.setdefault(event["call_id"], call) != call:
            raise DataError("call_mismatch", "evidence")
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
    if document["schema_version"] == "2.0":
        _validate_control_chain(document)
    return FrozenEvidence(document, hashlib.sha256(content).hexdigest())


def _validate_control_chain(document: dict[str, JsonValue]) -> None:
    state = deepcopy(document["before"]["state"])
    revision = document["before"]["revision"]
    known = True
    admissions = {}
    for event in document["events"]:
        details = event["details"]
        if (
            event["stage"] == "response"
            and details["status"] == "unknown"
            and document["freeze_status"] == "complete"
        ):
            raise DataError("incomplete_freeze", "evidence")
        if event["stage"] == "accepted":
            admissions[event["call_id"]] = details
            continue
        if event["stage"] != "effect":
            continue
        transition = details.get("transition")
        observation = details.get("observation")
        rejected = admissions[event["call_id"]]["status"] == "rejected"
        if rejected and (details["status"] != "no_effect" or observation is not None):
            raise DataError("invalid_transition", "evidence")
        if details["status"] == "unknown":
            known = False
            if document["freeze_status"] == "complete":
                raise DataError("incomplete_freeze", "evidence")
        if (details["status"] == "committed") != (transition is not None):
            raise DataError("invalid_transition", "evidence")
        if observation is not None:
            if (
                details["status"] != "no_effect"
                or transition is not None
                or (known and observation["revision"] != revision)
            ):
                raise DataError("invalid_observation", "evidence")
        if transition is None:
            continue
        if transition["to_revision"] != transition["from_revision"] + 1 or (
            known and transition["from_revision"] != revision
        ):
            raise DataError("invalid_transition", "evidence")
        paths = set()
        for change in transition["changes"]:
            path = change["path"]
            if re.search(r"~(?![01])", path) or path in paths:
                raise DataError("invalid_transition", "evidence")
            paths.add(path)
            parent_path, _, encoded_key = path.rpartition("/")
            parent = resolve_ref(state, parent_path) if parent_path else state
            key = encoded_key.replace("~1", "/").replace("~0", "~")
            if isinstance(parent, dict) and key in parent:
                previous = parent[key]
            elif (
                isinstance(parent, list)
                and key.isdecimal()
                and str(int(key)) == key
                and int(key) <= len(parent)
            ):
                key = int(key)
                previous = parent[key] if key < len(parent) else None
            else:
                raise DataError("invalid_transition", "evidence")
            if known and (previous != change["before"] or previous == change["after"]):
                raise DataError("invalid_transition", "evidence")
            if isinstance(parent, list) and key == len(parent):
                parent.append(deepcopy(change["after"]))
            else:
                parent[key] = deepcopy(change["after"])
        revision = transition["to_revision"]
    if known and (
        revision != document["after"]["revision"] or state != document["after"]["state"]
    ):
        raise DataError("invalid_transition", "evidence")


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
    policy = rubric["scoring_policy"]
    critical = sorted(
        {
            c["reason_code"]
            for c in criteria
            if c["status"] == "fail"
            and policy is not None
            and c["reason_code"] in policy["critical_codes"]
        }
    )
    required = {c["id"] for c in rubric["criteria"] if c["required"]}
    relevant = [c for c in criteria if c["criterion_id"] in required]
    known_fail = any(c["status"] == "fail" for c in relevant)
    complete = (
        evidence.document["freeze_status"] == "complete"
        and execution["stop_confirmed"]
        and execution["process_status"] == "completed"
        and execution["claim"] is not None
        and execution["claim"]["status"] != "unknown"
        and all(c["status"] != "unknown" for c in relevant)
    )
    result = {
        "identity": evidence.document["identity"],
        "score": None,
        "verdict": ("fail" if known_fail else "pass" if complete else "unknown")
        if rubric["success_policy"] is not None
        else "unknown",
        "completeness": "complete" if complete else "partial",
        "criteria": list(criteria),
        "violations": evidence.document["violations"],
        "errors": [],
        "critical_violations": critical,
        "evidence_hash": evidence.sha256,
    }
    validate_contract("evaluation", result)
    return result


def aggregate_evaluation(
    results: tuple[dict[str, JsonValue], ...],
    *,
    rubric: dict[str, JsonValue],
    expected_identities: tuple[dict[str, str], ...],
    purpose: str = "final",
) -> dict[str, JsonValue]:
    """Evaluate the entire fixed set; never average the available subset."""
    validate_contract("rubric", rubric)
    policy = rubric["scoring_policy"]
    if policy is None or rubric["success_policy"] != "all-required-v1":
        raise DataError("missing_methodology", "rubric")
    ids = [identity["case_id"] for identity in expected_identities]
    scopes = [
        {k: v for k, v in identity.items() if k not in {"case_id", "replay_id"}}
        for identity in expected_identities
    ]
    if (
        len(ids) != policy["case_count"]
        or len(set(ids)) != len(ids)
        or any(scope != scopes[0] for scope in scopes)
    ):
        raise DataError("invalid_set_identity", "evaluation")
    expected = {identity["case_id"]: identity for identity in expected_identities}
    seen = set()
    for result in results:
        validate_contract("evaluation", result)
        case_id = result["identity"]["case_id"]
        if case_id in seen or result["identity"] != expected.get(case_id):
            raise DataError("identity_mismatch", "evaluation")
        seen.add(case_id)
        if not set(result.get("critical_violations", [])) <= set(
            policy["critical_codes"]
        ):
            raise DataError("unknown_critical_code", "evaluation")
    missing = seen != set(ids)
    criterion_ids = {c["id"] for c in rubric["criteria"]}
    complete = not missing and all(
        r["completeness"] == "complete"
        and r["evidence_hash"] is not None
        and not r["errors"]
        and r["verdict"] != "unknown"
        and len(r["criteria"]) == len(criterion_ids)
        and {c["criterion_id"] for c in r["criteria"]} == criterion_ids
        and all(c["status"] != "unknown" for c in r["criteria"])
        for r in results
    )
    trusted = [
        r
        for r in results
        if r["completeness"] not in {"invalid", "unavailable"}
        and r["evidence_hash"] is not None
    ]
    critical = sorted(
        {code for r in trusted for code in r.get("critical_violations", [])}
    )
    failed = bool(critical) or any(r["verdict"] == "fail" for r in trusted)
    score = None
    if complete and purpose == "final":
        score = policy["points_per_pass"] * sum(r["verdict"] == "pass" for r in results)
        if critical:
            score = min(score, policy["critical_cap"])
    completeness = (
        "complete"
        if complete
        else (
            "invalid"
            if any(r["completeness"] == "invalid" for r in results)
            else "unavailable"
            if not results
            else "partial"
        )
    )
    evaluation = {
        "schema_version": "1.0",
        "purpose": purpose,
        "case_ids": ids,
        "cases": list(results),
        "score": score,
        "verdict": "fail" if failed else "pass" if complete else "unknown",
        "completeness": completeness,
        "critical_violations": critical,
        "errors": ["missing_cases"] if missing else [],
    }
    validate_contract("aggregate", evaluation)
    return evaluation
