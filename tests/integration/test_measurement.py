"""Opt-in T1 measurement controls on a private, pre-frozen Task copy."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from workflow_bench.experiment import ControlledSubmission, run_measurement


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
    selection_path = e1_config.output_root / "selection.json"
    final_manifest = e1_config.output_root / "final/manifest.json"
    assert selection_path.stat().st_mtime_ns < final_manifest.stat().st_mtime_ns
    native = json.loads(
        (e1_config.output_root / "final" / final["harbor_result_ref"]).read_bytes()
    )
    assert native["verifier_result"]["rewards"] == {"reward": 10.0}
    assert not (e1_config.output_root / "final/feedback.json").exists()
