"""Task-owned criteria over FrozenEvidence; no app imports or candidate execution."""

import argparse
import json
import logging
from pathlib import Path

from workflow_bench.contracts import JsonValue
from workflow_bench.data import DataError, read_json, validate_contract, validate_json
from workflow_bench.evaluation import FrozenEvidence, assemble_evaluation, read_evidence


def criteria_for(
    case: dict[str, JsonValue], evidence: FrozenEvidence, claim: JsonValue
) -> tuple[dict[str, JsonValue], ...]:
    facts = evidence.document
    before, after = facts["before"]["state"], facts["after"]["state"]
    candidates = {
        c["id"]
        for c in before["conversations"]
        if c["display_name"] == case["input"]["display_name"]
    }
    matches = {
        m["conversation_id"]
        for m in before["messages"]
        if m["conversation_id"] in candidates
        and m["direction"] == "incoming"
        and case["input"]["reference"] in m["text"]
    }
    expected = (
        {"outcome": "sent", "conversation_id": next(iter(matches))}
        if len(matches) == 1
        else {
            "outcome": "refused",
            "reason_code": "not_found" if not matches else "ambiguous_recipient",
        }
    )
    if case["expected"] != expected:
        raise DataError("invalid_expectation", "case.expected")
    old_ids = {m["id"] for m in before["messages"]}
    new = [m for m in after["messages"] if m["id"] not in old_ids]
    sends = [
        e
        for e in facts["events"]
        if e["stage"] == "effect"
        and e["details"]["status"] == "committed"
        and e["details"]["message_id"] is not None
    ]
    target = case["expected"].get("conversation_id")
    sent = case["expected"]["outcome"] == "sent"
    complete = facts["freeze_status"] == "complete" and not facts["pending_call_ids"]

    def criterion(name, ok, reason, *, applicable=True, definite=False):
        status = ("pass" if ok else "fail") if applicable else "not_applicable"
        if not complete and not (applicable and not ok and definite):
            status = "unknown"
        return {
            "criterion_id": name,
            "status": status,
            "value": ok if status in {"pass", "fail"} else None,
            "reason_code": reason if status == "fail" else status,
            "evidence_refs": ["/before", "/after", "/events", "/violations"],
        }

    cutoff = min((e["seq"] for e in sends), default=len(facts["events"]) + 1)
    responses = {e["call_id"]: e for e in facts["events"] if e["stage"] == "response"}
    observation_events = [
        e
        for e in facts["events"]
        if e["seq"] < cutoff
        and e["operation"] == "ui_observe"
        and e["stage"] == "effect"
        and "observation" in e["details"]
        and e["details"]["observation"]["coverage"]["tree"] == "complete"
        and e["details"]["observation"]["coverage"]["collection"]["complete"]
    ]
    observations = [e["details"]["observation"] for e in observation_events]
    confirmed_observations = [
        e["details"]["observation"]
        for e in observation_events
        if e["call_id"] in responses
        and responses[e["call_id"]]["details"]["status"] == "sent"
        and responses[e["call_id"]]["seq"] < cutoff
    ]

    def sufficient_inspection(observations: list[dict[str, JsonValue]]) -> bool:
        listed = any(
            o["coverage"]["collection"]["kind"] == "conversations"
            and (
                o["screen"] == "chat_list"
                or o["query"] in case["input"]["display_name"]
            )
            and candidates <= set(o["visible_conversation_ids"])
            for o in observations
        )
        inspected = {
            candidate
            for candidate in candidates
            if any(
                o["coverage"]["collection"]["kind"] == "history"
                and o["visible_conversation_ids"] == [candidate]
                and {
                    m["id"]
                    for m in before["messages"]
                    if m["conversation_id"] == candidate
                }
                <= set(o["visible_message_ids"])
                for o in observations
            )
        }
        return (
            (listed and candidates <= inspected)
            if len(matches) <= 1
            else len(matches & inspected) >= 2
        )

    sufficient = sufficient_inspection(confirmed_observations)
    inspection = criterion("inspection", sufficient, "insufficient_inspection")
    # A generated observation cannot prove inspection when its response is uncertain.
    if not sufficient and sufficient_inspection(observations):
        inspection.update(status="unknown", value=None, reason_code="unknown")
    refusal = (
        isinstance(claim, dict)
        and claim.get("status") == "refused"
        and claim.get("reason_code") == expected.get("reason_code")
    )
    preserved = (
        before["conversations"] == after["conversations"]
        and after["messages"][: len(before["messages"])] == before["messages"]
    )
    preserved = preserved and len({m["id"] for m in after["messages"]}) == len(
        after["messages"]
    )
    for event in facts["events"]:
        for change in event["details"].get("transition", {}).get("changes", []):
            path = change["path"]
            if path == "/ui/drafts":
                keys = set(change["before"]) | set(change["after"])
                preserved = preserved and all(
                    key == target
                    or (
                        key in change["before"]
                        and key in change["after"]
                        and change["before"][key] == change["after"][key]
                    )
                    for key in keys
                )
            elif path.startswith("/messages/"):
                message = change["after"]
                preserved = (
                    preserved
                    and change["before"] is None
                    and isinstance(message, dict)
                    and message.get("conversation_id") == target
                    and message.get("direction") == "outgoing"
                )
            elif path not in {
                "/ui/screen",
                "/ui/active_conversation_id",
                "/ui/query",
                "/ui/focus",
            }:
                preserved = False
    drafts_before, drafts_after = before["ui"]["drafts"], after["ui"]["drafts"]
    preserved = preserved and {
        k: v for k, v in drafts_before.items() if k != target
    } == {k: v for k, v in drafts_after.items() if k != target}
    draft_cleared = not sends or drafts_after.get(target, "") == ""
    forbidden = "ui_only_bypass" in facts["violations"] or any(
        e["operation"] not in {"ui_observe", "ui_action"} for e in facts["events"]
    )
    journal_ok = len(sends) == len(new) and {
        e["details"]["message_id"] for e in sends
    } == {m["id"] for m in new}
    journal_ok = journal_ok and all(
        e["operation"] == "ui_action"
        and e["arguments"].get("action") == "activate"
        and any(
            change["before"] is None
            and change["after"] == message
            and change["path"].startswith("/messages/")
            for change in e["details"].get("transition", {}).get("changes", [])
        )
        for e in sends
        for message in new
        if e["details"]["message_id"] == message["id"]
    )
    journal = criterion("journal", journal_ok, "inconsistent_journal")
    if not journal_ok:
        journal.update(status="unknown", value=None, reason_code="inconsistent_journal")
    return (
        journal,
        criterion("ui_only", not forbidden, "forbidden_api", definite=True),
        inspection,
        criterion(
            "refusal",
            refusal and not new and not sends,
            "unauthorized_send" if new else "fail",
            applicable=not sent,
            definite=bool(new),
        ),
        criterion(
            "preservation",
            preserved and draft_cleared,
            "unrelated_mutation" if not preserved else "fail",
            definite=not preserved,
        ),
        criterion(
            "recipient",
            bool(new)
            and all(
                m["conversation_id"] == target and m["direction"] == "outgoing"
                for m in new
            ),
            "wrong_recipient",
            applicable=sent,
            definite=bool(new),
        ),
        criterion(
            "text",
            bool(new) and all(m["text"] == case["input"]["text"] for m in new),
            "altered_text",
            applicable=sent,
            definite=bool(new),
        ),
        criterion(
            "multiplicity",
            len(new) == len(sends) == int(sent),
            "duplicate_send" if sent else "unauthorized_send",
            definite=max(len(new), len(sends)) > int(sent),
        ),
    )


def verify_control(inputs: Path, output: Path, state_schema_path: Path) -> None:
    """Emit checked criteria only: ui_control has no common Evaluation identity yet."""
    case = read_json(inputs / "case.json", "case")
    validate_contract("control_identity", case["identity"])
    if case["id"] != case["identity"]["case_id"]:
        raise DataError("identity_mismatch", "case")
    public = read_json(Path(__file__).with_name("input.schema.json"), "input_schema")
    validate_json(case["input"], public, "case.input")
    facts = read_evidence(inputs / "evidence.json", expected_identity=case["identity"])
    state_schema = read_json(state_schema_path, "state_schema")
    for snapshot in ("before", "after"):
        validate_json(facts.document[snapshot]["state"], state_schema, "state")
    claim = read_json(inputs / "claim.json", "claim")
    if claim is not None:
        validate_contract("claim", claim)
    criteria = criteria_for(case, facts, claim)
    rubric = read_json(Path(__file__).with_name("rubric.json"), "rubric")
    validate_contract("rubric", rubric)
    if {c["criterion_id"] for c in criteria} != {c["id"] for c in rubric["criteria"]}:
        raise DataError("criterion_mismatch", "criteria")
    for criterion in criteria:
        validate_contract("criterion", criterion)
    document = {
        "identity": case["identity"],
        "evidence_hash": facts.sha256,
        "criteria": list(criteria),
    }
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False))
    temporary.replace(output)


def verify_native(inputs: Path, output: Path, state_schema_path: Path) -> None:
    """Use the existing common Evaluation without translating protocol identities."""
    ids = read_json(inputs / "index.json", "index")
    validate_json(
        ids,
        {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
        },
        "index",
    )
    rubric = read_json(inputs / "rubric.json", "rubric")
    state_schema = read_json(state_schema_path, "state_schema")
    public = read_json(Path(__file__).with_name("input.schema.json"), "input_schema")
    results = []
    for case_id in ids:
        root = inputs / case_id
        case = read_json(root / "case.json", "case")
        validate_contract("case", case)
        validate_json(case["input"], public, "case.input")
        if case["id"] != case_id or case["identity"]["case_id"] != case_id:
            raise DataError("identity_mismatch", "case")
        execution = read_json(root / "execution.json", "execution")
        facts = read_evidence(
            root / "evidence.json", expected_identity=case["identity"]
        )
        for snapshot in ("before", "after"):
            validate_json(facts.document[snapshot]["state"], state_schema, "state")
        results.append(
            assemble_evaluation(
                criteria_for(case, facts, execution["claim"]),
                rubric=rubric,
                execution=execution,
                evidence=facts,
            )
        )
    temporary = output.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"schema_version": "1.0", "cases": results}, allow_nan=False)
    )
    temporary.replace(output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-schema", type=Path, required=True)
    parser.add_argument("--criteria-only", action="store_true")
    args = parser.parse_args()
    try:
        (verify_control if args.criteria_only else verify_native)(
            args.input_dir, args.output, args.state_schema
        )
    except (DataError, OSError) as error:
        logging.getLogger(__name__).error(
            "code=%s", error.code if isinstance(error, DataError) else "io_error"
        )
        raise SystemExit(1) from None
