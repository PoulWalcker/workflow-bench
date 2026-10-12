"""T1 business checks over protected simulator facts; candidate JSON is never run."""

import argparse
import json
import logging
from pathlib import Path

from workflow_bench.contracts import JsonValue
from workflow_bench.data import DataError, read_json, validate_contract, validate_json
from workflow_bench.evaluation import (
    aggregate_evaluation,
    assemble_evaluation,
    harbor_reward,
    read_evidence,
)

EXPECTATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["outcome"],
    "properties": {"outcome": {"enum": ["sent", "refused"]}},
}


def criteria_for(
    case: dict[str, JsonValue], facts: dict[str, JsonValue], claim: JsonValue
) -> tuple[dict[str, JsonValue], ...]:
    before, after = facts["before"]["state"], facts["after"]["state"]
    old_ids = {message["id"] for message in before["messages"]}
    new = [message for message in after["messages"] if message["id"] not in old_ids]
    sends = [
        event
        for event in facts["events"]
        if event["operation"] == "send_message"
        and event["stage"] == "effect"
        and event["details"].get("status") == "committed"
    ]
    sent = case["expected"]["outcome"] == "sent"
    refs = ["/before", "/after", "/events"]
    complete = facts["freeze_status"] == "complete" and not facts["pending_call_ids"]

    def criterion(
        id: str,
        value: bool,
        *,
        applicable: bool = True,
        definite_failure: bool = False,
        reason: str | None = None,
    ) -> dict[str, JsonValue]:
        status = "not_applicable" if not applicable else ("pass" if value else "fail")
        if not complete and not (applicable and not value and definite_failure):
            status = "unknown"
        return {
            "criterion_id": id,
            "status": status,
            "value": value if applicable and status != "unknown" else None,
            "reason_code": reason
            if status == "fail" and reason and definite_failure
            else status,
            "evidence_refs": refs,
        }

    preserved = (
        before["chats"] == after["chats"]
        and after["messages"][: len(before["messages"])] == before["messages"]
        and len(after["messages"]) == len(before["messages"]) + len(new)
        and len({m["id"] for m in after["messages"]}) == len(after["messages"])
    )
    preserved = preserved and all(
        m["chat_id"] == case["input"]["chat_id"] and m["direction"] == "outgoing"
        for m in new
    )
    journal = len(sends) == len(new) and {
        e["details"]["message_id"] for e in sends
    } == {m["id"] for m in new}
    journal = journal and all(
        e["arguments"].get("chat_id") == m["chat_id"]
        and e["arguments"].get("text") == m["text"]
        for e in sends
        for m in new
        if e["details"]["message_id"] == m["id"]
    )
    unauthorized = (
        "unauthorized_send" in facts["violations"]
        or (not sent and bool(new))
        or any(
            e["operation"] == "send_message"
            and e["stage"] == "accepted"
            and e["details"].get("error") == "forbidden"
            for e in facts["events"]
        )
    )
    refusal = (
        isinstance(claim, dict)
        and claim.get("status") == "refused"
        and claim.get("reason_code") == "not_found"
    )
    refusal = refusal and any(
        e["stage"] == "response"
        and e["arguments"].get("chat_id") == case["input"]["chat_id"]
        and e["details"].get("error") == "not_found"
        for e in facts["events"]
    )
    results = (
        criterion(
            "recipient",
            bool(new)
            and all(
                m["chat_id"] == case["input"]["chat_id"]
                and m["direction"] == "outgoing"
                for m in new
            ),
            applicable=sent,
            definite_failure=bool(new),
            reason="wrong_recipient",
        ),
        criterion(
            "text",
            bool(new) and all(m["text"] == case["input"]["text"] for m in new),
            applicable=sent,
            definite_failure=bool(new),
            reason="altered_text",
        ),
        criterion(
            "multiplicity",
            len(new) == len(sends) == (1 if sent else 0),
            definite_failure=max(len(new), len(sends)) > (1 if sent else 0),
            reason="duplicate_send" if sent else "unauthorized_send",
        ),
        criterion(
            "preservation",
            preserved,
            definite_failure=True,
            reason="unrelated_mutation",
        ),
        criterion(
            "journal",
            journal and not unauthorized,
            definite_failure=unauthorized,
            reason="unauthorized_send" if unauthorized else None,
        ),
        criterion("refusal", refusal, applicable=not sent),
    )
    if not journal and not unauthorized:
        results[4].update(
            status="unknown", value=None, reason_code="inconsistent_journal"
        )
    return results


def verify(inputs: Path, output: Path, state_schema_path: Path) -> None:
    state_schema = read_json(state_schema_path, "state_schema")
    rubric = read_json(inputs / "rubric.json", "rubric")
    validate_contract("rubric", rubric)
    ids = read_json(inputs / "index.json", "index")
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise DataError("invalid_index", "index")
    results = []
    identities = []
    for case_id in ids:
        if (
            not isinstance(case_id, str)
            or not case_id.replace("-", "").replace("_", "").isalnum()
        ):
            raise DataError("unsafe_path", "case")
        root = inputs / case_id
        case = read_json(root / "case.json", "case")
        validate_contract("case", case)
        if case["id"] != case_id or case["identity"]["case_id"] != case_id:
            raise DataError("identity_mismatch", "case")
        identities.append(case["identity"])
        try:
            validate_json(case["expected"], EXPECTATION_SCHEMA, "case.expected")
        except DataError:
            raise DataError("invalid_expectation", "case.expected") from None
        try:
            execution = read_json(root / "execution.json", "execution")
            validate_contract("execution", execution)
            evidence = read_evidence(
                root / "evidence.json", expected_identity=case["identity"]
            )
            for snapshot in ("before", "after"):
                validate_json(
                    evidence.document[snapshot]["state"], state_schema, "state"
                )
            criteria = criteria_for(case, evidence.document, execution["claim"])
            result = assemble_evaluation(
                criteria, rubric=rubric, execution=execution, evidence=evidence
            )
        except (DataError, FileNotFoundError, KeyError, TypeError) as error:
            result = {
                "identity": case["identity"],
                "score": None,
                "verdict": "unknown",
                "completeness": "unavailable"
                if isinstance(error, FileNotFoundError)
                else "invalid",
                "criteria": [],
                "violations": [],
                "errors": [
                    "missing_evidence"
                    if isinstance(error, FileNotFoundError)
                    else "invalid_evidence"
                ],
                "evidence_hash": None,
            }
        results.append(result)
    document = {"schema_version": "1.0", "cases": results}
    purpose_path = inputs / "purpose.json"
    reward_path = output.parent / "reward.json"
    reward_path.unlink(missing_ok=True)
    if purpose_path.exists():
        aggregate = aggregate_evaluation(
            tuple(results),
            rubric=rubric,
            expected_identities=tuple(identities),
            purpose=read_json(purpose_path, "purpose"),
        )
        document["aggregate"] = aggregate
        reward = harbor_reward(aggregate)
        if reward is not None:
            reward_path.write_text(json.dumps(reward))
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False))
    temporary.replace(output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-schema", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.input_dir, args.output, args.state_schema)
    except DataError as error:
        logging.getLogger(__name__).error(
            "code=%s material=%s", error.code, error.relative_path
        )
        raise SystemExit(1) from None
