from workflow_bench.evaluation import harbor_reward


def test_reward_maps_only_a_complete_numeric_fixture() -> None:
    result = {
        "identity": {
            "run_id": "run",
            "attempt_id": "attempt",
            "replay_id": "replay",
            "artifact_hash": "a" * 64,
            "case_id": "fresh",
            "profile_hash": "b" * 64,
            "profile": "reserve",
        },
        "score": None,
        "verdict": "unknown",
        "completeness": "complete",
        "criteria": [
            {
                "criterion_id": "reservation",
                "status": "pass",
                "value": True,
                "reason_code": "pass",
                "evidence_refs": ["/after"],
            }
        ],
        "violations": [],
        "errors": [],
        "evidence_hash": "c" * 64,
    }
    assert harbor_reward(result) is None
    result.update(score=7.25, verdict="pass")
    assert harbor_reward(result) == {"reward": 7.25}
    result["completeness"] = "partial"
    assert harbor_reward(result) is None
