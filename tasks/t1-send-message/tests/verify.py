"""T1 business checks over protected simulator facts; candidate JSON is never run."""

import argparse
import json
import logging
from pathlib import Path

from workflow_bench.contracts import JsonValue
from workflow_bench.data import DataError, read_json, validate_contract, validate_json
from workflow_bench.evaluation import assemble_evaluation, read_evidence


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
        id: str, value: bool, *, applicable: bool = True
    ) -> dict[str, JsonValue]:
        status = "not_applicable" if not applicable else ("pass" if value else "fail")
        if not complete:
            status = "unknown"
        return {
            "criterion_id": id,
            "status": status,
            "value": value if complete and applicable else None,
            "reason_code": status,
            "evidence_refs": refs,
        }

    preserved = (
        before["chats"] == after["chats"]
        and after["messages"][: len(before["messages"])] == before["messages"]
        and len(after["messages"]) == len(before["messages"]) + len(new)
        and len({m["id"] for m in after["messages"]}) == len(after["messages"])
    )
    journal = len(sends) == len(new) and {
        e["details"]["message_id"] for e in sends
    } == {m["id"] for m in new}
    journal = journal and all(e["arguments"] == case["input"] for e in sends)
    refusal = (
        isinstance(claim, dict)
        and claim.get("status") == "refused"
        and claim.get("reason_code") == "not_found"
    )
    refusal = refusal and any(
        e["stage"] == "response" and e["details"].get("error") == "not_found"
        for e in facts["events"]
    )
    return (
        criterion(
            "recipient",
            bool(new)
            and all(
                m["chat_id"] == case["input"]["chat_id"]
                and m["direction"] == "outgoing"
                for m in new
            ),
            applicable=sent,
        ),
        criterion(
            "text",
            bool(new) and all(m["text"] == case["input"]["text"] for m in new),
            applicable=sent,
        ),
        criterion("multiplicity", len(new) == (1 if sent else 0)),
        criterion("preservation", preserved),
        criterion("journal", journal),
        criterion("refusal", refusal, applicable=not sent),
    )


def verify(inputs: Path, output: Path, state_schema_path: Path) -> None:
    state_schema = read_json(state_schema_path, "state_schema")
    rubric = read_json(inputs / "rubric.json", "rubric")
    validate_contract("rubric", rubric)
    ids = read_json(inputs / "index.json", "index")
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise DataError("invalid_index", "index")
    results = []
    for case_id in ids:
        if (
            not isinstance(case_id, str)
            or not case_id.replace("-", "").replace("_", "").isalnum()
        ):
            raise DataError("unsafe_path", "case")
        root = inputs / case_id
        case = read_json(root / "case.json", "case")
        validate_contract("case", case)
        execution = read_json(root / "execution.json", "execution")
        validate_contract("execution", execution)
        try:
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
    verify(args.input_dir, args.output, args.state_schema)
