import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parents[2] / "tasks/t1-send-message/tests/verify.py"
IDENTITY = {
    "run_id": "run",
    "attempt_id": "attempt",
    "replay_id": "replay",
    "artifact_hash": "a" * 64,
    "case_id": "fresh",
    "profile_hash": "b" * 64,
    "profile": "t1-api-v1",
}


@pytest.fixture
def protected_inputs(tmp_path: Path) -> Path:
    inputs = tmp_path / "input"
    case_dir = inputs / "fresh"
    case_dir.mkdir(parents=True)
    before = {"chats": [{"id": "42", "display_name": "Anna"}], "messages": []}
    after = {
        **before,
        "messages": [
            {"id": "m-new", "chat_id": "42", "direction": "outgoing", "text": "exact"}
        ],
    }
    events = [
        {
            "seq": 1,
            "call_id": "call",
            "actor": "workflow",
            "profile": "t1-api-v1",
            "operation": "send_message",
            "arguments": {"chat_id": "42", "text": "exact"},
            "stage": "accepted",
            "details": {"status": "accepted", "error": None},
            "timestamp": 1,
        },
        {
            "seq": 2,
            "call_id": "call",
            "actor": "workflow",
            "profile": "t1-api-v1",
            "operation": "send_message",
            "arguments": {"chat_id": "42", "text": "exact"},
            "stage": "effect",
            "details": {
                "status": "committed",
                "message_id": "m-new",
                "evidence_ref": "/after/state/messages/0",
            },
            "timestamp": 2,
        },
        {
            "seq": 3,
            "call_id": "call",
            "actor": "workflow",
            "profile": "t1-api-v1",
            "operation": "send_message",
            "arguments": {"chat_id": "42", "text": "exact"},
            "stage": "response",
            "details": {"status": "sent", "error": None},
            "timestamp": 3,
        },
    ]
    data = {
        "case": {
            "id": "fresh",
            "input": {"chat_id": "42", "text": "exact"},
            "expected": {"outcome": "sent"},
            "identity": IDENTITY,
        },
        "execution": {
            "process_status": "completed",
            "exit_code": 0,
            "claim": {"status": "completed", "reason_code": "", "result": {}},
            "stop_confirmed": True,
        },
        "evidence": {
            "schema_version": "1.0",
            "identity": IDENTITY,
            "before": {"revision": 0, "state": before},
            "after": {"revision": 1, "state": after},
            "events": events,
            "violations": [],
            "freeze_status": "complete",
            "pending_call_ids": [],
        },
    }
    for name, value in data.items():
        (case_dir / (name + ".json")).write_text(json.dumps(value))
    (inputs / "index.json").write_text('["fresh"]')
    rubric = {
        "scoring_policy": None,
        "success_policy": None,
        "criteria": [
            {"id": id, "required": True}
            for id in [
                "recipient",
                "text",
                "multiplicity",
                "preservation",
                "journal",
                "refusal",
            ]
        ],
    }
    (inputs / "rubric.json").write_text(json.dumps(rubric))
    return inputs


def run_checks(inputs: Path, output: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(CHECK),
            "--input-dir",
            str(inputs),
            "--output",
            str(output),
            "--state-schema",
            str(CHECK.parents[3] / "simapps/telegram/state.schema.json"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(output.read_bytes())["cases"][0]


def test_t1_checks_protected_state_and_journal_without_scoring(
    protected_inputs: Path, tmp_path: Path
) -> None:
    evaluation = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert evaluation["score"] is None and evaluation["verdict"] == "unknown"
    assert evaluation["completeness"] == "complete"
    assert all(
        c["status"] in {"pass", "not_applicable"} for c in evaluation["criteria"]
    )


def test_missing_facts_are_unavailable_not_a_candidate_zero(
    protected_inputs: Path, tmp_path: Path
) -> None:
    (protected_inputs / "fresh/evidence.json").unlink()
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["completeness"] == "unavailable"
    assert result["score"] is None and result["verdict"] == "unknown"
    assert result["errors"] == ["missing_evidence"]


@pytest.mark.parametrize("change", ["recipient", "text", "duplicate", "preservation"])
def test_wrong_effect_is_not_rescued_by_completed_claim(
    protected_inputs: Path, tmp_path: Path, change: str
) -> None:
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    message = facts["after"]["state"]["messages"][0]
    if change == "recipient":
        message["chat_id"] = "other"
    elif change == "text":
        message["text"] = "wrong"
    elif change == "duplicate":
        facts["after"]["state"]["messages"].append({**message, "id": "duplicate"})
    else:
        facts["after"]["state"]["chats"][0]["display_name"] = "changed"
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    expected = "multiplicity" if change == "duplicate" else change
    assert (
        next(c for c in result["criteria"] if c["criterion_id"] == expected)["status"]
        == "fail"
    )
    assert result["score"] is None


def test_incomplete_freeze_produces_unknown_criteria(
    protected_inputs: Path, tmp_path: Path
) -> None:
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    facts["freeze_status"] = "incomplete"
    facts["pending_call_ids"] = ["pending"]
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["completeness"] == "partial"
    assert all(c["status"] == "unknown" for c in result["criteria"])


def test_committed_effect_with_lost_response_keeps_execution_incomplete(
    protected_inputs: Path, tmp_path: Path
) -> None:
    root = protected_inputs / "fresh"
    execution = json.loads((root / "execution.json").read_bytes())
    execution.update(process_status="failed", exit_code=1, claim=None)
    (root / "execution.json").write_text(json.dumps(execution))
    facts = json.loads((root / "evidence.json").read_bytes())
    facts["events"][-1]["details"]["status"] = "failed"
    (root / "evidence.json").write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["completeness"] == "partial"
    assert (
        next(c for c in result["criteria"] if c["criterion_id"] == "multiplicity")[
            "status"
        ]
        == "pass"
    )
    assert result["score"] is None


def test_proven_duplicate_survives_incomplete_drain(
    protected_inputs: Path, tmp_path: Path
) -> None:
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    facts["freeze_status"] = "incomplete"
    facts["pending_call_ids"] = ["pending"]
    message = facts["after"]["state"]["messages"][0]
    facts["after"]["state"]["messages"].append({**message, "id": "duplicate"})
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["completeness"] == "partial"
    assert (
        next(c for c in result["criteria"] if c["criterion_id"] == "multiplicity")[
            "status"
        ]
        == "fail"
    )


def test_reward_maps_only_a_complete_numeric_fixture(
    protected_inputs: Path, tmp_path: Path
) -> None:
    from workflow_bench.evaluation import harbor_reward

    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert harbor_reward(result) is None
    result.update(score=7.25, verdict="pass")
    assert harbor_reward(result) == {"reward": 7.25}
    result["completeness"] = "partial"
    assert harbor_reward(result) is None


@pytest.mark.parametrize("change", ["details", "call_arguments", "revision"])
def test_corrupted_event_facts_are_invalid_before_business_checks(
    protected_inputs: Path, tmp_path: Path, change: str
) -> None:
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    if change == "details":
        facts["events"][1]["details"]["status"] = "made-up-commit"
    elif change == "call_arguments":
        facts["events"][2]["arguments"]["text"] = "different-call"
    else:
        facts["before"]["revision"] = 2
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["completeness"] == "invalid" and not result["criteria"]


@pytest.mark.parametrize("change", ["identity", "sequence", "reference"])
def test_invalid_protected_envelope_has_no_business_verdict(
    protected_inputs: Path, tmp_path: Path, change: str
) -> None:
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    if change == "identity":
        facts["identity"]["case_id"] = "another"
    elif change == "sequence":
        facts["events"][1]["seq"] = 99
    else:
        facts["events"][1]["details"]["evidence_ref"] = "/after/no-such-field"
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["completeness"] == "invalid"
    assert not result["criteria"] and result["verdict"] == "unknown"


def refusal_inputs(inputs: Path) -> None:
    root = inputs / "fresh"
    case = json.loads((root / "case.json").read_bytes())
    case["input"] = {"chat_id": "absent", "text": "exact"}
    case["expected"] = {"outcome": "refused"}
    (root / "case.json").write_text(json.dumps(case))
    facts = json.loads((root / "evidence.json").read_bytes())
    facts["after"] = facts["before"]
    facts["events"] = [
        {
            "seq": 3,
            "call_id": "refusal",
            "actor": "workflow",
            "profile": "t1-api-v1",
            "operation": "send_message",
            "arguments": case["input"],
            "stage": "response",
            "details": {"status": "sent", "error": "not_found"},
            "timestamp": 1,
        }
    ]
    facts["events"] = [
        {
            **facts["events"][0],
            "seq": 1,
            "stage": "accepted",
            "details": {"status": "accepted", "error": None},
        },
        {
            **facts["events"][0],
            "seq": 2,
            "stage": "effect",
            "details": {"status": "no_effect", "message_id": None},
        },
        *facts["events"],
    ]
    (root / "evidence.json").write_text(json.dumps(facts))
    execution = json.loads((root / "execution.json").read_bytes())
    execution["claim"] = {"status": "refused", "reason_code": "not_found", "result": {}}
    (root / "execution.json").write_text(json.dumps(execution))


@pytest.mark.parametrize(
    "expected", [{"outcome": "misspelled-outcome"}, {}, {"outcome": 42}]
)
def test_invalid_expectation_is_rejected_instead_of_assessed_as_refusal(
    protected_inputs: Path, tmp_path: Path, expected: dict
) -> None:
    refusal_inputs(protected_inputs)
    output = tmp_path / "evaluation.json"
    valid = run_checks(protected_inputs, output)
    assert valid["completeness"] == "complete"
    assert valid["score"] is None and valid["verdict"] == "unknown"
    assert all(c["status"] in {"pass", "not_applicable"} for c in valid["criteria"])
    output.unlink()
    path = protected_inputs / "fresh/case.json"
    case = json.loads(path.read_bytes())
    case["expected"] = expected
    path.write_text(json.dumps(case))
    result = subprocess.run(
        [
            sys.executable,
            str(CHECK),
            "--input-dir",
            str(protected_inputs),
            "--output",
            str(output),
            "--state-schema",
            str(CHECK.parents[3] / "simapps/telegram/state.schema.json"),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "invalid_expectation" in result.stderr and "case.expected" in result.stderr
    assert not output.exists() and not result.stdout
    assert "misspelled-outcome" not in result.stderr
    assert "Traceback" not in result.stderr


def test_t1_methodology_preserves_critical_fail_with_null_score(
    protected_inputs, tmp_path
):
    rubric = json.loads((CHECK.parent / "rubric.json").read_text())
    (protected_inputs / "rubric.json").write_text(json.dumps(rubric))
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    facts["after"]["state"]["messages"][0]["text"] = "changed"
    facts["freeze_status"] = "incomplete"
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["score"] is None and result["verdict"] == "fail"
    assert result["critical_violations"] == ["altered_text"]


def prepare_final_inputs(inputs: Path) -> None:
    import shutil

    ids = ["fresh", "second", "third", "fourth", "fifth"]
    for case_id in ids[1:]:
        shutil.copytree(inputs / "fresh", inputs / case_id)
        for filename in ["case.json", "evidence.json"]:
            path = inputs / case_id / filename
            value = json.loads(path.read_bytes())
            value["identity"].update(case_id=case_id, replay_id=case_id)
            if filename == "case.json":
                value["id"] = case_id
            path.write_text(json.dumps(value))
    (inputs / "index.json").write_text(json.dumps(ids))
    (inputs / "purpose.json").write_text('"final"')
    (inputs / "rubric.json").write_bytes((CHECK.parent / "rubric.json").read_bytes())


def test_final_verifier_writes_one_aggregate_reward_for_five_cases(
    protected_inputs, tmp_path
):
    prepare_final_inputs(protected_inputs)
    output = tmp_path / "evaluation.json"
    run_checks(protected_inputs, output)
    result = json.loads(output.read_bytes())
    assert result["aggregate"]["score"] == 10
    assert json.loads((tmp_path / "reward.json").read_bytes()) == {"reward": 10.0}


@pytest.mark.parametrize(
    "change,reason",
    [
        ("recipient", "wrong_recipient"),
        ("text", "altered_text"),
        ("duplicate", "duplicate_send"),
        ("mutation", "unrelated_mutation"),
        ("unauthorized", "unauthorized_send"),
    ],
)
def test_task_classifies_all_five_critical_categories(
    protected_inputs, tmp_path, change, reason
):
    (protected_inputs / "rubric.json").write_bytes(
        (CHECK.parent / "rubric.json").read_bytes()
    )
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    message = facts["after"]["state"]["messages"][0]
    if change == "recipient":
        message["chat_id"] = "other"
    elif change == "text":
        message["text"] = "wrong"
    elif change == "duplicate":
        facts["after"]["state"]["messages"].append({**message, "id": "second"})
    elif change == "mutation":
        facts["after"]["state"]["chats"][0]["display_name"] = "changed"
    else:
        facts["events"][0]["details"] = {"status": "rejected", "error": "forbidden"}
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert reason in result["critical_violations"] and result["verdict"] == "fail"


def test_no_send_is_ordinary_failure_and_historical_same_text_is_not_duplicate(
    protected_inputs, tmp_path
):
    (protected_inputs / "rubric.json").write_bytes(
        (CHECK.parent / "rubric.json").read_bytes()
    )
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    message = facts["after"]["state"]["messages"][0]
    old = {**message, "id": "historical"}
    facts["before"]["state"]["messages"] = [old]
    facts["after"]["state"]["messages"].insert(0, old)
    facts["events"][1]["details"]["evidence_ref"] = "/after/state/messages/1"
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["verdict"] == "pass" and not result["critical_violations"]
    facts["after"] = facts["before"]
    facts["events"] = []
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["verdict"] == "fail" and not result["critical_violations"]


def test_final_missing_facts_remove_stale_numeric_reward(protected_inputs, tmp_path):
    prepare_final_inputs(protected_inputs)
    output = tmp_path / "evaluation.json"
    run_checks(protected_inputs, output)
    (protected_inputs / "fifth/evidence.json").unlink()
    run_checks(protected_inputs, output)
    aggregate = json.loads(output.read_bytes())["aggregate"]
    assert aggregate["score"] is None and aggregate["completeness"] != "complete"
    assert not (tmp_path / "reward.json").exists()


def test_protected_repeat_commit_is_critical_even_if_snapshot_has_one_new_message(
    protected_inputs, tmp_path
):
    (protected_inputs / "rubric.json").write_bytes(
        (CHECK.parent / "rubric.json").read_bytes()
    )
    path = protected_inputs / "fresh/evidence.json"
    facts = json.loads(path.read_bytes())
    events = [{**e, "seq": e["seq"] + 3, "call_id": "repeat"} for e in facts["events"]]
    facts["events"].extend(events)
    path.write_text(json.dumps(facts))
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["score"] is None and result["verdict"] == "fail"
    assert "duplicate_send" in result["critical_violations"]


def test_missing_execution_keeps_frozen_criteria_unavailable(
    protected_inputs, tmp_path
):
    (protected_inputs / "rubric.json").write_bytes(
        (CHECK.parent / "rubric.json").read_bytes()
    )
    (protected_inputs / "fresh/execution.json").unlink()
    result = run_checks(protected_inputs, tmp_path / "evaluation.json")
    assert result["score"] is None and result["completeness"] == "unavailable"
