"""Synthetic ingress controls; these do not establish producer trust or Replay."""

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from workflow_bench.evaluation import read_evidence

TASK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("t2_verify", TASK / "tests/verify.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def sample():
    return json.loads((TASK / "tests/cases.json").read_text())["cases"][0]


def evidence(case):
    state = deepcopy(case["state"])
    return {
        "schema_version": "2.0",
        "identity": {
            "protocol": "ui_control",
            "run_id": "synthetic",
            "control_id": "control",
            "case_id": case["id"],
            "profile": "simsapp-ui-v1",
            "profile_hash": "a" * 64,
        },
        "before": {"revision": 0, "state": state},
        "after": {"revision": 0, "state": deepcopy(state)},
        "events": [],
        "violations": [],
        "freeze_status": "complete",
        "pending_call_ids": [],
    }


def event(facts, details, operation="ui_action", arguments=None):
    call = str(len(facts["events"]) + 1)
    for stage, payload in [
        ("accepted", {"status": "accepted", "error": None}),
        ("effect", details),
        ("response", {"status": "sent", "error": None}),
    ]:
        facts["events"].append(
            {
                "seq": len(facts["events"]) + 1,
                "call_id": call,
                "actor": "control",
                "profile": "simsapp-ui-v1",
                "operation": operation,
                "arguments": arguments or {},
                "stage": stage,
                "details": payload,
                "timestamp": 0,
            }
        )


def append_message(facts, conversation="unique-target", text=None):
    messages = facts["after"]["state"]["messages"]
    message = {
        "id": "new-" + str(len(messages)),
        "conversation_id": conversation,
        "direction": "outgoing",
        "text": text if text is not None else sample()["input"]["text"],
    }
    revision = facts["after"]["revision"]
    event(
        facts,
        {
            "status": "committed",
            "message_id": message["id"],
            "transition": {
                "from_revision": revision,
                "to_revision": revision + 1,
                "changes": [
                    {
                        "path": "/messages/" + str(len(messages)),
                        "before": None,
                        "after": message,
                    }
                ],
            },
        },
        arguments={"action": "activate"},
    )
    messages.append(message)
    facts["after"]["revision"] += 1


def assess(tmp_path, case, facts, claim=None):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(facts))
    frozen = read_evidence(path, expected_identity=facts["identity"])
    return {c["criterion_id"]: c for c in verifier.criteria_for(case, frozen, claim)}


def test_existing_equal_text_does_not_replace_new_send(tmp_path):
    case = sample()
    case["state"]["messages"].append(
        {
            "id": "old-equal",
            "conversation_id": "unique-target",
            "direction": "outgoing",
            "text": case["input"]["text"],
        }
    )
    facts = evidence(case)
    assert assess(tmp_path, case, facts)["multiplicity"]["status"] == "fail"
    append_message(facts)
    criteria = assess(tmp_path, case, facts)
    assert criteria["multiplicity"]["status"] == "pass"
    assert criteria["recipient"]["status"] == "pass"
    assert criteria["text"]["status"] == "pass"
    append_message(facts)
    assert (
        assess(tmp_path, case, facts)["multiplicity"]["reason_code"] == "duplicate_send"
    )


def test_outgoing_reference_cannot_authorize_send(tmp_path):
    import pytest

    from workflow_bench.data import DataError

    case = sample()
    case["state"]["messages"][0]["direction"] = "outgoing"
    facts = evidence(case)
    append_message(facts)
    with pytest.raises(DataError, match="invalid_expectation"):
        assess(tmp_path, case, facts)


def change_drafts(facts, drafts):
    state = facts["after"]["state"]
    revision = facts["after"]["revision"]
    event(
        facts,
        {
            "status": "committed",
            "message_id": None,
            "transition": {
                "from_revision": revision,
                "to_revision": revision + 1,
                "changes": [
                    {
                        "path": "/ui/drafts",
                        "before": deepcopy(state["ui"]["drafts"]),
                        "after": deepcopy(drafts),
                    }
                ],
            },
        },
        arguments={"action": "replace_text"},
    )
    state["ui"]["drafts"] = deepcopy(drafts)
    facts["after"]["revision"] += 1


def test_restoring_an_unrelated_draft_does_not_erase_violation(tmp_path):
    case = sample()
    case["state"]["conversations"].append(
        {"id": "other", "display_name": "Other", "identity_hint": None}
    )
    case["state"]["ui"]["drafts"]["other"] = "Keep me"
    facts = evidence(case)
    change_drafts(facts, {"other": "damaged"})
    change_drafts(facts, {"other": "Keep me"})
    append_message(facts)
    assert (
        assess(tmp_path, case, facts)["preservation"]["reason_code"]
        == "unrelated_mutation"
    )


def inspect(facts, case):
    state = case["state"]
    groups = [
        ("chat_list", "conversations", [c["id"] for c in state["conversations"]], [])
    ]
    groups.extend(
        (
            "conversation",
            "history",
            [c["id"]],
            [m["id"] for m in state["messages"] if m["conversation_id"] == c["id"]],
        )
        for c in state["conversations"]
        if c["display_name"] == case["input"]["display_name"]
    )
    for screen, kind, conversations, messages in groups:
        event(
            facts,
            {
                "status": "no_effect",
                "message_id": None,
                "observation": {
                    "revision": facts["after"]["revision"],
                    "screen": screen,
                    "query": "",
                    "coverage": {
                        "tree": "complete",
                        "collection": {"kind": kind, "complete": True},
                    },
                    "visible_conversation_ids": conversations,
                    "visible_message_ids": messages,
                },
            },
            "ui_observe",
        )


def test_missing_match_requires_inspection_and_explicit_refusal(tmp_path):
    case = sample()
    case["input"]["reference"] = "#absent"
    case["expected"] = {"outcome": "refused", "reason_code": "not_found"}
    facts = evidence(case)
    claim = {"status": "refused", "reason_code": "not_found", "result": None}
    assert assess(tmp_path, case, facts, claim)["inspection"]["status"] == "fail"
    inspect(facts, case)
    assert assess(tmp_path, case, facts, claim)["refusal"]["status"] == "pass"
    assert assess(tmp_path, case, facts, claim)["inspection"]["status"] == "pass"
    assert assess(tmp_path, case, facts)["refusal"]["status"] == "fail"


def test_forbidden_api_attempt_fails_even_without_an_effect(tmp_path):
    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    append_message(facts)
    event(facts, {"status": "no_effect", "message_id": None}, "send_message")
    facts["violations"].append("ui_only_bypass")
    assert assess(tmp_path, case, facts)["ui_only"]["reason_code"] == "forbidden_api"


def test_message_without_matching_send_fact_is_unknown(tmp_path):
    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    append_message(facts)
    facts["events"][-2]["details"]["message_id"] = None
    assert assess(tmp_path, case, facts)["journal"]["status"] == "unknown"


def test_separate_verifier_entry_writes_criteria_without_claiming_replay(tmp_path):
    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    append_message(facts)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "case.json").write_text(
        json.dumps({**case, "identity": facts["identity"]})
    )
    (bundle / "evidence.json").write_text(json.dumps(facts))
    (bundle / "claim.json").write_text(
        json.dumps({"status": "completed", "reason_code": None, "result": None})
    )
    output = tmp_path / "criteria.json"
    verifier.verify_control(
        bundle, output, TASK.parents[1] / "simapps/simsapp/state.schema.json"
    )
    result = json.loads(output.read_text())
    assert all(c["status"] in {"pass", "not_applicable"} for c in result["criteria"])
    assert "verdict" not in result and "score" not in result


@pytest.mark.parametrize(
    "case",
    json.loads((TASK / "tests/cases.json").read_text())["cases"],
    ids=lambda c: c["id"],
)
def test_development_expectations_accept_independent_protected_effects(tmp_path, case):
    facts = evidence(case)
    inspect(facts, case)
    if case["expected"]["outcome"] == "sent":
        target = case["expected"]["conversation_id"]
        if facts["after"]["state"]["ui"]["drafts"].get(target):
            change_drafts(
                facts, {**facts["after"]["state"]["ui"]["drafts"], target: ""}
            )
        append_message(facts, target, case["input"]["text"])
        claim = {"status": "completed", "reason_code": None, "result": None}
    else:
        claim = {
            "status": "refused",
            "reason_code": case["expected"]["reason_code"],
            "result": None,
        }
    assert all(
        c["status"] in {"pass", "not_applicable"}
        for c in assess(tmp_path, case, facts, claim).values()
    )


@pytest.mark.parametrize(
    "conversation,text,criterion",
    [
        ("wrong", None, "recipient"),
        ("unique-target", "altered", "text"),
    ],
)
def test_wrong_effect_is_a_known_failure_even_with_incomplete_freeze(
    tmp_path, conversation, text, criterion
):
    case = sample()
    facts = evidence(case)
    append_message(facts, conversation, text)
    facts["freeze_status"] = "incomplete"
    assert assess(tmp_path, case, facts)[criterion]["status"] == "fail"
    assert assess(tmp_path, case, facts)["inspection"]["status"] == "unknown"


def test_inspection_after_send_cannot_justify_recipient_choice(tmp_path):
    case = sample()
    facts = evidence(case)
    append_message(facts)
    inspect(facts, case)
    assert assess(tmp_path, case, facts)["inspection"]["status"] == "fail"


def test_lost_send_response_preserves_the_committed_effect(tmp_path):
    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    append_message(facts)
    facts["events"][-1]["details"]["status"] = "failed"
    result = assess(
        tmp_path,
        case,
        facts,
        {"status": "unknown", "reason_code": "effect_unknown", "result": None},
    )
    assert result["multiplicity"]["status"] == "pass"
    assert result["journal"]["status"] == "pass"


def test_forged_transition_and_foreign_identity_are_rejected(tmp_path):
    from workflow_bench.data import DataError

    case = sample()
    facts = evidence(case)
    append_message(facts)
    facts["after"]["state"]["messages"][-1]["text"] = "forged"
    # The synthetic helper shares its appended value; break that alias deliberately.
    facts["events"][-2]["details"]["transition"]["changes"][0]["after"] = {
        **facts["after"]["state"]["messages"][-1],
        "text": "original",
    }
    with pytest.raises(DataError, match="invalid_transition"):
        assess(tmp_path, case, facts)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence(case)))
    with pytest.raises(DataError, match="identity_mismatch"):
        read_evidence(
            path, expected_identity={**facts["identity"], "case_id": "foreign"}
        )


def test_common_evaluation_rejects_ui_control_identity(tmp_path):
    from workflow_bench.data import DataError
    from workflow_bench.evaluation import assemble_evaluation

    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    append_message(facts)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(facts))
    frozen = read_evidence(path, expected_identity=facts["identity"])
    execution = {
        "process_status": "completed",
        "exit_code": 0,
        "claim": {"status": "completed", "reason_code": None, "result": None},
        "stop_requested": True,
        "stop_confirmed": True,
        "errors": [],
    }
    with pytest.raises(DataError, match="invalid_schema: evaluation"):
        assemble_evaluation(
            verifier.criteria_for(case, frozen, execution["claim"]),
            rubric=json.loads((TASK / "tests/rubric.json").read_text()),
            execution=execution,
            evidence=frozen,
        )


def test_two_observed_matches_are_sufficient_to_refuse_ambiguity(tmp_path):
    case = next(
        c
        for c in json.loads((TASK / "tests/cases.json").read_text())["cases"]
        if c["id"] == "ambiguous"
    )
    facts = evidence(case)
    inspect(facts, case)
    # A third equally named conversation exists but need not be inspected once
    # two different conversations have already established ambiguity.
    third = {"id": "third", "display_name": "Alex Morgan", "identity_hint": None}
    facts["before"]["state"]["conversations"].append(third)
    facts["after"]["state"]["conversations"].append(third)
    claim = {"status": "refused", "reason_code": "ambiguous_recipient", "result": None}
    assert assess(tmp_path, case, facts, claim)["inspection"]["status"] == "pass"


@pytest.mark.parametrize("effect_status", ["pending", "unknown"])
def test_untouched_target_draft_with_incomplete_freeze_is_unknown(
    tmp_path, effect_status
):
    case = sample()
    case["state"]["ui"]["drafts"]["unique-target"] = "Existing unsent draft"
    facts = evidence(case)
    event(facts, {"status": "unknown", "message_id": None})
    if effect_status == "pending":
        del facts["events"][-2:]
    facts["freeze_status"] = "incomplete"
    facts["pending_call_ids"] = [facts["events"][0]["call_id"]]
    result = assess(tmp_path, case, facts)
    assert result["preservation"]["status"] == "unknown"
    assert result["preservation"]["reason_code"] == "unknown"
    assert result["multiplicity"]["status"] == "unknown"


def test_no_send_preserves_existing_target_draft(tmp_path):
    case = sample()
    case["state"]["ui"]["drafts"]["unique-target"] = "Existing unsent draft"
    result = assess(tmp_path, case, evidence(case))
    assert result["preservation"]["status"] == "pass"
    assert result["multiplicity"]["status"] == "fail"


@pytest.mark.parametrize(
    "freeze_status,status", [("complete", "fail"), ("incomplete", "unknown")]
)
def test_uncleared_target_draft_is_a_send_postcondition(
    tmp_path, freeze_status, status
):
    case = sample()
    case["state"]["ui"]["drafts"]["unique-target"] = "Existing unsent draft"
    facts = evidence(case)
    append_message(facts)
    facts["freeze_status"] = freeze_status
    result = assess(tmp_path, case, facts)["preservation"]
    assert result["status"] == status
    assert result["reason_code"] == status


def test_proven_unrelated_draft_mutation_fails_with_incomplete_freeze(tmp_path):
    case = sample()
    case["state"]["conversations"].append(
        {"id": "other", "display_name": "Other", "identity_hint": None}
    )
    case["state"]["ui"]["drafts"]["other"] = "Keep me"
    facts = evidence(case)
    change_drafts(facts, {"other": "damaged"})
    change_drafts(facts, {"other": "Keep me"})
    facts["freeze_status"] = "incomplete"
    result = assess(tmp_path, case, facts)["preservation"]
    assert result["status"] == "fail"
    assert result["reason_code"] == "unrelated_mutation"


def test_failed_observation_responses_do_not_confirm_inspection(tmp_path):
    case = next(
        c
        for c in json.loads((TASK / "tests/cases.json").read_text())["cases"]
        if c["id"] == "duplicate-names"
    )
    facts = evidence(case)
    inspect(facts, case)
    for entry in facts["events"]:
        if entry["stage"] == "response":
            entry["details"]["status"] = "failed"
    append_message(facts, case["expected"]["conversation_id"], case["input"]["text"])
    result = assess(tmp_path, case, facts)
    assert result["inspection"]["status"] == "unknown"
    assert result["recipient"]["status"] == "pass"
    assert result["multiplicity"]["status"] == "pass"


@pytest.mark.parametrize("delivery", ["failed", "unknown", "missing", "late"])
def test_other_successful_responses_cannot_confirm_a_history_call(tmp_path, delivery):
    case = next(
        c
        for c in json.loads((TASK / "tests/cases.json").read_text())["cases"]
        if c["id"] == "duplicate-names"
    )
    facts = evidence(case)
    inspect(facts, case)
    history = next(
        e
        for e in facts["events"]
        if e["stage"] == "effect"
        and e["details"]["observation"]["coverage"]["collection"]["kind"] == "history"
    )
    response = next(
        e
        for e in facts["events"]
        if e["stage"] == "response" and e["call_id"] == history["call_id"]
    )
    if delivery in {"failed", "unknown"}:
        response["details"]["status"] = delivery
    else:
        facts["events"].remove(response)
    if delivery in {"unknown", "missing"}:
        facts["freeze_status"] = "incomplete"
        facts["pending_call_ids"] = [history["call_id"]]
    append_message(facts, case["expected"]["conversation_id"], case["input"]["text"])
    if delivery == "late":
        facts["events"].append(response)
    for seq, entry in enumerate(facts["events"], 1):
        entry["seq"] = seq
    result = assess(tmp_path, case, facts)["inspection"]
    assert result["status"] == "unknown"
    assert result["value"] is None


def test_interleaved_observation_responses_are_matched_by_call_id(tmp_path):
    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    responses = [e for e in facts["events"] if e["stage"] == "response"]
    facts["events"] = [e for e in facts["events"] if e["stage"] != "response"]
    facts["events"].extend(reversed(responses))
    for seq, entry in enumerate(facts["events"], 1):
        entry["seq"] = seq
    append_message(facts)
    assert assess(tmp_path, case, facts)["inspection"]["status"] == "pass"


def test_a_confirmed_repeat_observation_resolves_delivery_uncertainty(tmp_path):
    case = sample()
    facts = evidence(case)
    inspect(facts, case)
    for entry in facts["events"]:
        if entry["stage"] == "response":
            entry["details"]["status"] = "failed"
    inspect(facts, case)
    append_message(facts)
    assert assess(tmp_path, case, facts)["inspection"]["status"] == "pass"
