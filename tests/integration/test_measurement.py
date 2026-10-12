"""Opt-in T1 measurement controls on a private, pre-frozen Task copy."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from workflow_bench.evaluation import read_evidence
from workflow_bench.experiment import ControlledSubmission, run_manual, run_measurement


@pytest.fixture
def measurement_task(request):
    value = request.config.getoption("--measurement-task")
    if not value:
        pytest.fail("pass a pre-frozen private Task with --measurement-task")
    return Path(value).resolve()


def test_unchanged_manual_t1_passes_development_and_private_final(
    e1_config, measurement_task
):
    source = measurement_task / "solution/workflow.json"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    result = asyncio.run(
        run_measurement(
            measurement_task, (ControlledSubmission(source),), config=e1_config
        )
    )
    assert result["attempt_count"] == 1
    assert result["selection"]["reason"] == "first_development_pass"
    assert result["selection"]["artifact_hash"] == source_hash
    assert result["score"] == 10 and result["verdict"] == "pass"
    assert result["completeness"] == "complete"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    development = json.loads(
        (e1_config.output_root / "attempt-1/development/report.json").read_bytes()
    )
    final = json.loads((e1_config.output_root / "final/report.json").read_bytes())
    assert (
        development["business_completeness"] == "complete"
        and development["score"] is None
    )
    assert (
        development["reward_status"] == "incomplete"
        and not development["reward_required"]
    )
    assert final["reward_status"] == "complete" and final["reward_required"]
    for phase in (development, final):
        assert len(phase["evaluation"]["cases"]) == 5
        assert {r["identity"]["artifact_hash"] for r in phase["replays"]} == {
            source_hash
        }
        assert not phase["cleanup_errors"] and not phase["residual_resources"]
    for name, phase in (("attempt-1/development", development), ("final", final)):
        root = e1_config.output_root / name
        manifest = json.loads((root / "manifest.json").read_bytes())
        cases = json.loads((root / manifest["case_snapshot"]["ref"]).read_bytes())
        expected_states = {case["id"]: case["state"] for case in cases["cases"]}
        for replay in phase["replays"]:
            evidence = read_evidence(
                root / replay["evidence_ref"], expected_identity=replay["identity"]
            )
            assert evidence.document["before"]["revision"] == 0
            assert (
                evidence.document["before"]["state"]
                == expected_states[replay["identity"]["case_id"]]
            )
    selection_path = e1_config.output_root / "selection.json"
    final_manifest = e1_config.output_root / "final/manifest.json"
    assert selection_path.stat().st_mtime_ns < final_manifest.stat().st_mtime_ns
    native = json.loads(
        (e1_config.output_root / "final" / final["harbor_result_ref"]).read_bytes()
    )
    assert native["verifier_result"]["rewards"] == {"reward": 10.0}
    assert not (e1_config.output_root / "final/feedback.json").exists()


def test_development_cleanup_uncertainty_blocks_final(
    e1_config, measurement_task, monkeypatch
):
    from workflow_bench.harbor import docker

    async def inspection_fault(*arguments):
        if arguments[:2] == ("network", "ls") and any(
            argument.startswith("label=com.docker.compose.project=wb-replay-")
            for argument in arguments
        ):
            raise ConnectionError("synthetic metadata transport failure")
        return await docker(*arguments)

    monkeypatch.setattr("workflow_bench.harbor.docker", inspection_fault)
    result = asyncio.run(
        run_measurement(
            measurement_task,
            (ControlledSubmission(measurement_task / "solution/workflow.json"),),
            config=e1_config,
        )
    )
    development = json.loads(
        (e1_config.output_root / "attempt-1/development/report.json").read_bytes()
    )
    assert development["business_completeness"] == "complete"
    assert development["completeness"] == "partial"
    assert result["selection"]["blocked"]
    assert result["final_report_ref"] is None
    assert result["score"] is None
    assert not (e1_config.output_root / "final").exists()


def test_replay_costs_keep_setup_cleanup_and_judge_separate(e1_config):
    task = Path(__file__).resolve().parents[2] / "tasks/t1-send-message"
    result = asyncio.run(run_manual(task, ("fresh-a",), config=e1_config))
    efficiency = result["efficiency"]
    assert efficiency["infrastructure"]["setup_ms"] > 0
    assert efficiency["infrastructure"]["cleanup_ms"] > 0
    assert efficiency["infrastructure"]["usd"] is None
    assert efficiency["judge"] == {"calls": 0, "source": "not_used", "usd": None}
    metrics = result["replays"][0]["metrics"]
    assert metrics["tool_calls_by_operation"] == {"send_message": 1}
    assert metrics["model_calls"] == 0 and metrics["usd"] is None
    assert (e1_config.output_root / efficiency["native_phase_timings_ref"]).is_file()


def test_proven_workflow_error_blocks_correction_and_private_final(
    e1_config, measurement_task, tmp_path
):
    source = measurement_task / "solution/workflow.json"
    workflow = json.loads(source.read_bytes())
    for node in workflow["nodes"]:
        if node["type"] == "n8n-nodes-base.code":
            node["parameters"]["jsCode"] = "throw new Error('WB12 control failure');"
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps(workflow))
    result = asyncio.run(
        run_measurement(
            measurement_task,
            (ControlledSubmission(broken), ControlledSubmission(source)),
            config=e1_config,
        )
    )
    assert result["attempt_count"] == 1
    assert result["selection"]["blocked"]
    assert result["score"] is None and result["final_report_ref"] is None
    development = json.loads(
        (e1_config.output_root / "attempt-1/development/report.json").read_bytes()
    )
    assert development["business_completeness"] == "partial"
    assert all(
        r["execution"]["process_status"] == "failed" for r in development["replays"]
    )
    assert all(r["execution"]["stop_confirmed"] for r in development["replays"])
    assert not development["cleanup_errors"] and not development["residual_resources"]


@pytest.mark.parametrize("second_valid", [True, False])
def test_bounded_correction_and_invalid_second_use_development_selection(
    e1_config, measurement_task, tmp_path, second_valid
):
    source = measurement_task / "solution/workflow.json"
    workflow = json.loads(source.read_bytes())
    for node in workflow["nodes"]:
        if node["type"] == "n8n-nodes-base.code":
            node["parameters"]["jsCode"] = node["parameters"]["jsCode"].replace(
                "text: bench.input.text", "text: 'WB12 altered-text control'"
            )
    first = tmp_path / "altered-text.json"
    first.write_text(json.dumps(workflow))
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}")
    result = asyncio.run(
        run_measurement(
            measurement_task,
            (
                ControlledSubmission(first),
                ControlledSubmission(source if second_valid else invalid),
            ),
            config=e1_config,
        )
    )
    assert result["attempt_count"] == 2
    assert (
        result["selection"]["selected_attempt_id"]
        == result["attempts"][1 if second_valid else 0]["attempt_id"]
    )
    assert result["selection"]["reason"] == (
        "first_development_pass" if second_valid else "last_valid"
    )
    assert result["score"] == (10 if second_valid else 2)
    assert result["verdict"] == ("pass" if second_valid else "fail")
    assert result["completeness"] == "complete"
    feedback = json.loads(
        (e1_config.output_root / "attempt-1/feedback.json").read_bytes()
    )
    assert any(c["criterion_id"] == "text" and c["status"] == "fail" for c in feedback)
    assert all(set(c) == {"criterion_id", "status", "reason_code"} for c in feedback)
    final = json.loads((e1_config.output_root / "final/report.json").read_bytes())
    assert {r["identity"]["artifact_hash"] for r in final["replays"]} == {
        result["selection"]["artifact_hash"]
    }
    assert all(r["execution"]["stop_confirmed"] for r in final["replays"])
    assert not final["cleanup_errors"] and not final["residual_resources"]
