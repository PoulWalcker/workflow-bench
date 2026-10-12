import json
from copy import deepcopy

import pytest

from workflow_bench.data import DataError
from workflow_bench.definition import export_public, load_cases, load_task


def test_private_final_set_is_selected_by_purpose_and_never_exported(
    tmp_path, native_task_files
):
    task, tools = native_task_files
    config = (
        (task / "task.toml")
        .read_text()
        .replace("[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"')
    )
    (task / "task.toml").write_text(config)
    final = {
        "schema_version": "1.0",
        "purpose": "final",
        "cases": [
            {
                "id": "hidden",
                "input": {"item": "private-marker"},
                "state": {},
                "expected": {"reserved": "private-marker"},
            }
        ],
    }
    (task / "tests/final.json").write_text(json.dumps(final))
    materials = load_task(task, tool_contract=tools)
    assert load_cases(materials, purpose="final")[0].input["item"] == "private-marker"
    public = export_public(materials, tmp_path / "public")
    assert all("private-marker" not in p.read_text() for p in public.root.iterdir())
    final["purpose"] = "development"
    (task / "tests/final.json").write_text(json.dumps(final))
    with pytest.raises(DataError, match="purpose_mismatch"):
        load_cases(materials, purpose="final")


def evaluated_cases():
    identities = [
        {
            "run_id": "run",
            "attempt_id": "attempt",
            "replay_id": f"replay-{n}",
            "case_id": f"case-{n}",
            "profile": "reserve",
            "profile_hash": "b" * 64,
            "artifact_hash": "a" * 64,
        }
        for n in range(5)
    ]
    criteria = [
        {
            "criterion_id": cid,
            "status": "pass",
            "value": True,
            "reason_code": "pass",
            "evidence_refs": ["/after"],
        }
        for cid in ["reservation"]
    ]
    results = [
        {
            "identity": identity,
            "score": None,
            "verdict": "pass",
            "completeness": "complete",
            "criteria": criteria,
            "critical_violations": [],
            "violations": [],
            "errors": [],
            "evidence_hash": "c" * 64,
        }
        for identity in identities
    ]
    return identities, results


@pytest.fixture
def measurement_files(native_task_files):
    task, tools = native_task_files
    metadata = task / "task.toml"
    metadata.write_text(
        metadata.read_text().replace(
            "[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"'
        )
    )
    final = json.loads((task / "tests/cases.json").read_bytes())
    final["purpose"] = "final"
    for case in final["cases"]:
        case["id"] = "final-" + case["id"]
        case["input"]["item"] = "final-" + case["input"]["item"]
    (task / "tests/final.json").write_text(json.dumps(final))
    return task, tools


def test_creation_total_is_unknown_when_an_attempt_has_no_metrics(
    tmp_path, monkeypatch, config_data, measurement_files
):
    import asyncio

    from workflow_bench.cli import load_config
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    task, tools = measurement_files
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))

    async def exported_tools(config, **kwargs):
        return tools

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    result = asyncio.run(
        run_measurement(
            task,
            (
                ControlledSubmission(None, metrics={"input_tokens": 12}),
                ControlledSubmission(None),
            ),
            config=load_config(config_path, output=tmp_path / "run"),
        )
    )
    assert result["attempt_count"] == 2
    assert result["efficiency"]["creation"]["input_tokens"] is None
    assert len(result["efficiency"]["creation"]["attempts"]) == 2
    assert result["model_calls"] == 0


def test_missing_submissions_retain_reproducible_conditions(
    tmp_path, monkeypatch, config_data, measurement_files
):
    import asyncio

    from workflow_bench.cli import load_config
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    task, tools = measurement_files
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    output = tmp_path / "run"

    async def exported_tools(config, **kwargs):
        return tools

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    asyncio.run(
        run_measurement(
            task,
            (ControlledSubmission(None),),
            config=load_config(config_path, output=output),
        )
    )
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["config"]["app_image"] == config_data["app_image"]
    assert manifest["config"]["total_timeout_sec"] == config_data["total_timeout_sec"]
    assert manifest["harbor_version"]
    assert manifest["materials"]["task.toml"]
    assert manifest["profile_hash"]


@pytest.mark.parametrize(
    "passed,critical,score",
    [(5, False, 10), (4, False, 8), (4, True, 3), (1, True, 2), (0, False, 0)],
)
def test_full_set_scoring_examples(passed, critical, score, rubric_data):
    from workflow_bench.evaluation import aggregate_evaluation, harbor_reward

    identities, results = evaluated_cases()
    for result in results[passed:]:
        result["verdict"] = "fail"
        if critical:
            result["critical_violations"] = ["unexpected_reservation"]
    rubric = rubric_data
    evaluation = aggregate_evaluation(
        tuple(results), rubric=rubric, expected_identities=tuple(identities)
    )
    assert evaluation["score"] == score
    assert evaluation["verdict"] == ("pass" if passed == 5 else "fail")
    assert harbor_reward(evaluation) == {"reward": float(score)}


@pytest.mark.parametrize(
    "change", ["missing", "partial", "unknown", "no-criteria", "no-hash", "known-fail"]
)
def test_incomplete_set_never_receives_numeric_reward(change, rubric_data):
    from workflow_bench.evaluation import aggregate_evaluation, harbor_reward

    identities, results = evaluated_cases()
    if change == "missing":
        results.pop()
    elif change == "no-criteria":
        results[0]["criteria"] = []
    elif change == "no-hash":
        results[0]["evidence_hash"] = None
    else:
        results[0].update(completeness="partial", verdict="unknown")
        if change == "unknown":
            results[0]["criteria"] = [
                {**c, "status": "unknown"} for c in results[0]["criteria"]
            ]
        if change == "known-fail":
            results[1].update(
                verdict="fail", critical_violations=["repeated_reservation"]
            )
    rubric = rubric_data
    result = aggregate_evaluation(
        tuple(results), rubric=rubric, expected_identities=tuple(identities)
    )
    assert result["score"] is None and harbor_reward(result) is None
    assert result["verdict"] == ("fail" if change == "known-fail" else "unknown")


@pytest.mark.parametrize("change", ["duplicate", "hash", "case", "run", "profile"])
def test_aggregate_rejects_results_of_another_measurement(change, rubric_data):
    from workflow_bench.evaluation import aggregate_evaluation

    identities, results = evaluated_cases()
    if change == "duplicate":
        results[-1] = results[0]
    else:
        key = {
            "hash": "artifact_hash",
            "case": "case_id",
            "run": "run_id",
            "profile": "profile_hash",
        }[change]
        results[0]["identity"] = {**results[0]["identity"], key: "d" * 64}
    rubric = rubric_data
    with pytest.raises(DataError):
        aggregate_evaluation(
            tuple(results), rubric=rubric, expected_identities=tuple(identities)
        )


@pytest.mark.parametrize(
    "completeness,evidence_hash",
    [
        ("invalid", None),
        ("invalid", "c" * 64),
        ("unavailable", None),
        ("partial", None),
    ],
)
def test_invalid_evidence_cannot_establish_a_business_failure(
    rubric_data, completeness, evidence_hash
):
    from workflow_bench.evaluation import aggregate_evaluation

    identities, results = evaluated_cases()
    results[0].update(
        completeness=completeness,
        verdict="fail",
        evidence_hash=evidence_hash,
        critical_violations=["unexpected_reservation"],
    )
    result = aggregate_evaluation(
        tuple(results), rubric=rubric_data, expected_identities=tuple(identities)
    )
    assert result["score"] is None
    assert result["completeness"] == (
        "invalid" if completeness == "invalid" else "partial"
    )
    assert result["verdict"] == "unknown"
    assert result["critical_violations"] == []


def test_trusted_failure_survives_invalid_neighbour(rubric_data):
    from workflow_bench.evaluation import aggregate_evaluation

    identities, results = evaluated_cases()
    results[0].update(completeness="invalid", verdict="unknown", evidence_hash=None)
    results[1].update(
        completeness="partial",
        verdict="fail",
        critical_violations=["repeated_reservation"],
    )
    result = aggregate_evaluation(
        tuple(results), rubric=rubric_data, expected_identities=tuple(identities)
    )
    assert result["score"] is None
    assert result["completeness"] == "invalid"
    assert result["verdict"] == "fail"
    assert result["critical_violations"] == ["repeated_reservation"]


def test_selection_uses_first_full_pass_or_last_valid_and_redacts_feedback(
    tmp_path, native_task_files, rubric_data
):
    from workflow_bench.evaluation import aggregate_evaluation
    from workflow_bench.execution import accept_artifact
    from workflow_bench.experiment import Attempt, select_attempts

    task, tools = native_task_files
    materials = load_task(task, tool_contract=tools)
    workflow_file = task / "solution/workflow.json"
    rubric = rubric_data
    second_source = tmp_path / "second.json"
    workflow = json.loads(workflow_file.read_text())
    workflow["name"] = "Second controlled submission"
    second_source.write_text(json.dumps(workflow))
    artifacts = [
        accept_artifact(
            source,
            submission_stopped=True,
            destination=tmp_path / f"version-{i}.json",
        )
        for i, source in enumerate([workflow_file, second_source])
    ]
    identities, results = evaluated_cases()
    for identity in identities:
        identity.update(attempt_id="first", artifact_hash=artifacts[0].sha256)
    good = aggregate_evaluation(
        tuple(deepcopy(results)),
        rubric=rubric,
        expected_identities=tuple(identities),
        purpose="development",
    )
    results[0]["verdict"] = "fail"
    results[0]["criteria"] = [
        {**c, "status": "fail", "reason_code": "private-marker"}
        for c in results[0]["criteria"]
    ]
    bad = aggregate_evaluation(
        tuple(results),
        rubric=rubric,
        expected_identities=tuple(identities),
        purpose="development",
    )
    first = Attempt("first", artifacts[0], bad, "completed", True)
    worse = deepcopy(bad)
    for case in worse["cases"]:
        case["identity"].update(attempt_id="second", artifact_hash=artifacts[1].sha256)
        case["verdict"] = "fail"
        case["criteria"] = [
            {**c, "status": "fail", "reason_code": "private-marker"}
            for c in case["criteria"]
        ]
    second = Attempt("second", artifacts[1], worse, "completed", True)
    choice = select_attempts(
        (first, second), feedback_rules=materials.public_data["feedback"]
    )
    assert (
        choice["selected_attempt_id"] == "second" and choice["reason"] == "last_valid"
    )
    assert choice["artifact_hash"] == artifacts[1].sha256 != artifacts[0].sha256
    assert "private-marker" not in json.dumps(choice)
    passed = Attempt("first", artifacts[0], good, "completed", True)
    assert (
        select_attempts((passed,), feedback_rules=materials.public_data["feedback"])[
            "continue"
        ]
        is False
    )
    assert (
        select_attempts(
            (passed, second), feedback_rules=materials.public_data["feedback"]
        )["selected_attempt_id"]
        == "first"
    )
    invalid = Attempt("second", None, None, "completed", True)
    assert (
        select_attempts(
            (first, invalid), feedback_rules=materials.public_data["feedback"]
        )["selected_attempt_id"]
        == "first"
    )
    assert (
        select_attempts((invalid,), feedback_rules=materials.public_data["feedback"])[
            "selected_attempt_id"
        ]
        is None
    )
    with pytest.raises(DataError, match="attempt_limit"):
        select_attempts(
            (first, second, invalid), feedback_rules=materials.public_data["feedback"]
        )


@pytest.mark.parametrize("fault", ["partial", "unknown", "stop"])
def test_selection_blocks_continuation_on_uncertainty(
    tmp_path, fault, workflow_file, rubric_data
):
    from workflow_bench.evaluation import aggregate_evaluation
    from workflow_bench.execution import accept_artifact
    from workflow_bench.experiment import Attempt, select_attempts

    artifact = accept_artifact(
        workflow_file,
        submission_stopped=True,
        destination=tmp_path / "accepted.json",
    )
    identities, cases = evaluated_cases()
    for identity in identities:
        identity["artifact_hash"] = artifact.sha256
    cases[0].update(completeness="partial", verdict="unknown")
    rubric = rubric_data
    development = aggregate_evaluation(
        tuple(cases),
        rubric=rubric,
        expected_identities=tuple(identities),
        purpose="development",
    )
    result = select_attempts(
        (
            Attempt(
                "attempt",
                artifact,
                development,
                "unknown" if fault == "unknown" else "completed",
                fault != "stop",
            ),
        ),
        feedback_rules={"criterion_ids": [], "private_values": False},
    )
    assert result["blocked"] and not result["continue"] and result["feedback"] == []


def budget_document():
    return {
        "methodology": "case-pass-v1",
        "profile": "t1-api-v1",
        "harness": "codex",
        "harness_version": "test",
        "backend": "test",
        "model": "test",
        "model_version": "test",
        "finalized": False,
        "max_attempts": 2,
        "judge_calls": 0,
        "runtime_llm_calls": 0,
        "attempt": {
            "seconds": 300,
            "tools": 40,
            "model_calls": 20,
            "input_tokens": 50000,
            "output_tokens": 10000,
            "usd": 2.5,
        },
        "total": {
            "seconds": 2400,
            "tools": 80,
            "model_calls": 40,
            "input_tokens": 100000,
            "output_tokens": 20000,
            "usd": 5,
        },
        "credential_cap_usd": 5,
        "retry_policy": "no-unknown-retry",
        "enforcement": {
            "seconds": "process_deadline",
            "tools": "capability",
            "model_calls": "provider_quota",
            "input_tokens": "provider_quota",
            "output_tokens": "provider_quota",
            "usd": "credential_cap",
        },
    }


def test_model_preflight_requires_finalized_budget_and_separate_authorization(
    tmp_path, config_data
):
    from workflow_bench.cli import model_preflight

    budget = budget_document()
    with pytest.raises(DataError, match="unapproved_budget"):
        model_preflight(budget, runtime=config_data, authorized=False)
    budget["finalized"] = True
    with pytest.raises(DataError, match="model_not_authorized"):
        model_preflight(budget, runtime=config_data, authorized=False)
    plan = model_preflight(
        budget,
        runtime=config_data,
        authorized=True,
        usage={
            "model_calls": 3,
            "input_tokens": 1000,
            "output_tokens": 100,
            "usd": 0.5,
            "tools": 2,
            "seconds": 30,
        },
    )
    assert plan["remaining"]["model_calls"] == 37 and plan["remaining"]["usd"] == 4.5
    assert plan["execution_enabled"] is False


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), 0, -1, None])
def test_preflight_rejects_unbounded_or_unknown_limits(config_data, bad):
    from workflow_bench.cli import model_preflight

    budget = budget_document()
    budget["total"]["usd"] = bad
    with pytest.raises(DataError):
        model_preflight(budget, runtime=config_data, authorized=False)


def test_preflight_rejects_exhausted_or_unknown_shared_budget(config_data):
    from workflow_bench.cli import model_preflight

    budget = budget_document()
    budget["finalized"] = True
    usage = dict.fromkeys(budget["total"], 0)
    usage["usd"] = 5
    with pytest.raises(DataError, match="budget_exhausted"):
        model_preflight(budget, runtime=config_data, authorized=True, usage=usage)
    usage["usd"] = None
    with pytest.raises(DataError, match="unknown_usage"):
        model_preflight(budget, runtime=config_data, authorized=True, usage=usage)


def test_private_set_cannot_reuse_development_identity_or_input(
    tmp_path, native_task_files
):
    task, tools = native_task_files
    path = task / "task.toml"
    path.write_text(
        path.read_text().replace(
            "[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"'
        )
    )
    development = json.loads((task / "tests/cases.json").read_bytes())
    development.update(purpose="final")
    (task / "tests/final.json").write_text(json.dumps(development))
    materials = load_task(task, tool_contract=tools)
    with pytest.raises(DataError, match="overlapping_cases"):
        load_cases(materials, purpose="final")


@pytest.mark.parametrize("critical, expected_score", [(False, 8), (True, 1)])
def test_aggregate_uses_task_owned_set_size_points_and_cap(
    critical, expected_score, rubric_data
):
    from workflow_bench.evaluation import aggregate_evaluation

    identities, cases = evaluated_cases()
    rubric = rubric_data
    rubric["scoring_policy"].update(case_count=2, points_per_pass=4, critical_cap=1)
    if critical:
        cases[0]["verdict"] = "fail"
        cases[0]["criteria"][0].update(
            status="fail", value=False, reason_code="unexpected_reservation"
        )
        cases[0]["critical_violations"] = ["unexpected_reservation"]
    result = aggregate_evaluation(
        tuple(cases[:2]), rubric=rubric, expected_identities=tuple(identities[:2])
    )
    assert result["score"] == expected_score
    assert result["completeness"] == "complete"
    assert result["verdict"] == ("fail" if critical else "pass")


def test_measurement_preserves_existing_output_before_any_resources(
    tmp_path, config_data, native_task_files
):
    import asyncio

    from workflow_bench.cli import load_config
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    output = tmp_path / "existing"
    output.mkdir()
    (output / "report.json").write_text("original")
    config = load_config(path, output=output)
    with pytest.raises(FileExistsError):
        asyncio.run(
            run_measurement(
                native_task_files[0],
                (ControlledSubmission(None),),
                config=config,
            )
        )
    assert (output / "report.json").read_text() == "original"


def test_measurement_uses_task_owned_case_count(
    tmp_path, monkeypatch, config_data, native_task_files
):
    import asyncio

    from workflow_bench.cli import load_config
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    task, tools = native_task_files
    path = task / "task.toml"
    path.write_text(
        path.read_text().replace(
            "[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"'
        )
    )
    development = json.loads((task / "tests/cases.json").read_bytes())
    development["cases"] = development["cases"][:2]
    (task / "tests/cases.json").write_text(json.dumps(development))
    final = deepcopy(development)
    final["purpose"] = "final"
    for case in final["cases"]:
        case["id"] = "final-" + case["id"]
        case["input"]["item"] = "synthetic-new-input-" + case["input"]["item"]
    (task / "tests/final.json").write_text(json.dumps(final))
    path = task / "tests/rubric.json"
    rubric = json.loads(path.read_bytes())
    rubric["scoring_policy"].update(case_count=2, points_per_pass=5)
    path.write_text(json.dumps(rubric))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))

    async def exported_tools(config, **kwargs):
        return tools

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    result = asyncio.run(
        run_measurement(
            task,
            (ControlledSubmission(None),),
            config=load_config(config_path, output=tmp_path / "run"),
        )
    )
    assert result["selection"]["reason"] == "no_valid_submission"
    assert result["attempt_count"] == 1
    assert result["score"] is None


def test_cli_model_gate_rejects_before_any_run_or_credential_access(
    tmp_path, config_data
):
    import subprocess
    import sys

    marker = "synthetic-private-config-marker"
    config = tmp_path / (marker + ".json")
    config.write_text(json.dumps({"budget": budget_document(), "runtime": config_data}))
    output = tmp_path / "uncreated"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "workflow_bench.cli",
            "--model-preflight",
            "--config",
            str(config),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1 and not output.exists()
    assert "unapproved_budget" in result.stderr and not result.stdout
    assert marker not in result.stderr and "Traceback" not in result.stderr


def test_selection_rejects_development_of_another_artifact(
    tmp_path, workflow_file, rubric_data
):
    from workflow_bench.evaluation import aggregate_evaluation
    from workflow_bench.execution import accept_artifact
    from workflow_bench.experiment import Attempt, select_attempts

    artifact = accept_artifact(
        workflow_file,
        submission_stopped=True,
        destination=tmp_path / "accepted.json",
    )
    identities, cases = evaluated_cases()
    rubric = rubric_data
    development = aggregate_evaluation(
        tuple(cases),
        rubric=rubric,
        expected_identities=tuple(identities),
        purpose="development",
    )
    with pytest.raises(DataError, match="identity_mismatch"):
        select_attempts(
            (Attempt("attempt", artifact, development, "completed", True),),
            feedback_rules={"criterion_ids": [], "private_values": False},
        )


def test_independent_measurements_use_distinct_native_submission_projects(
    tmp_path, monkeypatch, config_data, native_task_files
):
    import asyncio

    from harbor.trial.trial import Trial

    from workflow_bench.cli import load_config
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    task, tools = native_task_files
    path = task / "task.toml"
    path.write_text(
        path.read_text().replace(
            "[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"'
        )
    )
    final = json.loads((task / "tests/cases.json").read_bytes())
    final["purpose"] = "final"
    for case in final["cases"]:
        case["id"] = "final-" + case["id"]
        case["input"]["item"] = "synthetic-new-input-" + case["input"]["item"]
    (task / "tests/final.json").write_text(json.dumps(final))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    projects = []

    class ProcessBoundaryObserved(Exception):
        pass

    async def exported_tools(config, **kwargs):
        return tools

    async def observe_creation(config):
        projects.append(config.trial_name)
        raise ProcessBoundaryObserved()

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    monkeypatch.setattr(Trial, "create", observe_creation)
    for index in range(2):
        config = load_config(config_path, output=tmp_path / f"run-{index}")
        with pytest.raises(ProcessBoundaryObserved):
            asyncio.run(
                run_measurement(
                    task,
                    (ControlledSubmission(task / "solution/workflow.json"),),
                    config=config,
                )
            )
    assert projects[0] != projects[1]
