"""`wb compare` over synthetic Harbor job directories, against hand-computed reports."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from harbor.models.agent.context import AgentContext
from harbor.models.job.config import JobConfig
from harbor.models.task.config import VerifierEnvironmentMode
from harbor.models.task.id import LocalTaskId
from harbor.models.trial.config import AgentConfig, TaskConfig, TrialConfig
from harbor.models.trial.result import (
    AgentInfo,
    ExceptionInfo,
    ModelInfo,
    TimingInfo,
    TrialResult,
)
from harbor.models.verifier.result import VerifierResult

from workflow_bench.cli import main
from workflow_bench.contracts import Criterion
from workflow_bench.evaluation import write_evaluation

START = datetime(2026, 1, 1, tzinfo=UTC)
CODEX = {
    "harness": "codex",
    "harness_version": "0.162.1",
    "model": "openai/gpt-5",
    "reasoning": "high",
}


def _job(jobs_dir: Path, name: str) -> Path:
    """Create a Harbor job directory as `harbor run` lays it out."""
    job_dir = jobs_dir / name
    job_dir.mkdir(parents=True)
    config = JobConfig(job_name=name, jobs_dir=jobs_dir)
    (job_dir / "config.json").write_text(config.model_dump_json())
    return job_dir


def _criteria(*statuses: Literal["pass", "fail", "unknown"]) -> list[Criterion]:
    return [
        {"criterion_id": f"c{index}", "status": status, "reason_code": "checked"}
        for index, status in enumerate(statuses)
    ]


def _trial(
    job_dir: Path,
    name: str,
    *,
    criteria: Sequence[Criterion] | None,
    task: str = "t1",
    checksum: str = "c1",
    harness: str = "codex",
    version: str = "0.162.1",
    model: str | None = "gpt-5",
    provider: str | None = "openai",
    kwargs: dict[str, object] | None = None,
    agent_sec: float | None = 10.0,
    tokens: tuple[int | None, int | None, int | None] = (None, None, None),
    exception: str | None = None,
    artifacts_status: str = "ok",
    verifier: Literal["finished", "failed", "skipped"] = "finished",
    verifier_mode: Literal["separate", "shared"] = "separate",
) -> None:
    """Write one Trial directory with Harbor's result and an evaluation file.

    ``criteria=None`` leaves no evaluation; ``agent_sec=None`` means the agent
    never started. ``verifier`` is what Harbor recorded of its verifier phase:
    ``failed`` began it without a verifier result, ``skipped`` never began it,
    so an evaluation file then is not the verifier's.
    """
    trial_dir = job_dir / name
    (trial_dir / "verifier").mkdir(parents=True)
    agent = AgentConfig(name=harness, model_name=model, kwargs=kwargs or {})
    config = TrialConfig(
        task=TaskConfig(path=Path("/tasks") / task),
        trial_name=name,
        trials_dir=job_dir,
        agent=agent,
    )
    (trial_dir / "config.json").write_text(config.model_dump_json())
    model_info = None if model is None else ModelInfo(name=model, provider=provider)
    result = TrialResult(
        task_name=task,
        trial_name=name,
        trial_uri=trial_dir.as_uri(),
        task_id=LocalTaskId(path=Path("/tasks") / task),
        task_checksum=checksum,
        config=config,
        agent_info=AgentInfo(name=harness, version=version, model_info=model_info),
        started_at=START,
        finished_at=START + timedelta(minutes=5),
        verifier_environment_mode=VerifierEnvironmentMode(verifier_mode),
    )
    if verifier != "skipped":
        result.verifier = TimingInfo(
            started_at=START + timedelta(minutes=4),
            finished_at=START + timedelta(minutes=5),
        )
    if exception is not None:
        result.exception_info = ExceptionInfo(
            exception_type=exception,
            exception_message="synthetic",
            exception_traceback="",
            occurred_at=START,
        )
    if agent_sec is not None:
        result.agent_execution = TimingInfo(
            started_at=START, finished_at=START + timedelta(seconds=agent_sec)
        )
        result.agent_result = AgentContext(
            n_input_tokens=tokens[0],
            n_cache_tokens=tokens[1],
            n_output_tokens=tokens[2],
        )
        (trial_dir / "artifacts").mkdir()
        (trial_dir / "artifacts" / "manifest.json").write_text(
            json.dumps(
                [
                    {
                        "source": "/work/output",
                        "destination": "artifacts/work/output",
                        "type": "directory",
                        "status": artifacts_status,
                        "service": None,
                        "exclude": [],
                    }
                ]
            )
        )
    if criteria is not None:
        evaluation = write_evaluation(trial_dir / "verifier", criteria)
        if verifier == "finished" and evaluation["completeness"] == "complete":
            reward = 1.0 if evaluation["verdict"] == "pass" else 0.0
            result.verifier_result = VerifierResult(rewards={"reward": reward})
    (trial_dir / "result.json").write_text(result.model_dump_json(indent=4))


def _compare(
    job_dirs: Sequence[Path], capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict]:
    status = main(["compare", *map(str, job_dirs)])
    return status, json.loads(capsys.readouterr().out)


def _trial_outcome(
    trial: str, outcome: str, reason: str | None = None, exception: str | None = None
) -> dict[str, str | None]:
    return {
        "job": "job-a",
        "trial": trial,
        "outcome": outcome,
        "reason": reason,
        "exception": exception,
    }


def test_each_trial_gets_one_outcome_and_missing_reward_is_not_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    kwargs: dict[str, object] = {"reasoning_effort": "high"}
    _trial(job, "a-pass", criteria=_criteria("pass", "pass"), kwargs=kwargs)
    _trial(job, "b-fail", criteria=_criteria("pass", "fail"), kwargs=kwargs)
    # Incomplete: no reward.json, so Harbor records a verifier exception.
    _trial(
        job,
        "c-unknown",
        criteria=_criteria("pass", "unknown"),
        kwargs=kwargs,
        exception="RewardFileNotFoundError",
    )
    # The agent timed out; the resulting state still proves a violation.
    _trial(
        job,
        "d-timeout",
        criteria=_criteria("fail", "unknown"),
        kwargs=kwargs,
        exception="AgentTimeoutError",
    )
    _trial(
        job,
        "e-setup",
        criteria=None,
        kwargs=kwargs,
        agent_sec=None,
        exception="EnvironmentStartTimeoutError",
    )
    _trial(
        job,
        "f-verifier",
        criteria=None,
        kwargs=kwargs,
        exception="VerifierTimeoutError",
        verifier="failed",
    )
    # The answer was not collected, so the verifier's proven `fail` is not trusted.
    _trial(
        job,
        "g-artifacts",
        criteria=_criteria("fail"),
        kwargs=kwargs,
        artifacts_status="failed",
    )

    status, report = _compare([job], capsys)

    assert status == 0
    assert report["incomplete_trials"] == []
    [pair] = report["pairs"]
    assert (pair["task"], pair["configuration"]) == ("t1", CODEX)
    assert pair["trials"] == [
        _trial_outcome("a-pass", "pass"),
        _trial_outcome("b-fail", "fail"),
        _trial_outcome("c-unknown", "unknown", exception="RewardFileNotFoundError"),
        _trial_outcome("d-timeout", "fail", exception="AgentTimeoutError"),
        _trial_outcome(
            "e-setup",
            "infra_error",
            "setup_failed",
            exception="EnvironmentStartTimeoutError",
        ),
        _trial_outcome(
            "f-verifier",
            "infra_error",
            "evaluation_missing",
            exception="VerifierTimeoutError",
        ),
        _trial_outcome("g-artifacts", "infra_error", "artifacts_failed"),
    ]
    assert pair["counts"] == {
        "trials": 7,
        "pass": 1,
        "fail": 2,
        "unknown": 1,
        "infra_error": 3,
    }
    assert pair["pass_rate"] == pytest.approx(1 / 3)
    assert pair["unknown_rate"] == pytest.approx(1 / 7)
    assert pair["infra_error_rate"] == pytest.approx(3 / 7)


def test_evaluation_not_produced_by_a_finished_separate_verifier_is_infra_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    # The candidate wrote a passing evaluation into the verifier directory
    # mounted in its container; an agent error then made Harbor skip the verifier.
    _trial(
        job,
        "a-skipped",
        criteria=_criteria("pass"),
        exception="RuntimeError",
        verifier="skipped",
    )
    # A shared verifier runs where the candidate's processes can still write.
    _trial(job, "b-shared", criteria=_criteria("pass"), verifier_mode="shared")
    # The verifier environment failed to start, so it never cleared the
    # directory: a complete evaluation without Harbor's verifier result.
    _trial(
        job,
        "c-not-started",
        criteria=_criteria("pass"),
        exception="EnvironmentStartTimeoutError",
        verifier="failed",
    )

    _, report = _compare([job], capsys)

    [pair] = report["pairs"]
    assert [
        (trial["trial"], trial["outcome"], trial["reason"]) for trial in pair["trials"]
    ] == [
        ("a-skipped", "infra_error", "verifier_skipped"),
        ("b-shared", "infra_error", "verifier_not_separate"),
        ("c-not-started", "infra_error", "verifier_result_missing"),
    ]


def test_trials_are_grouped_by_task_and_configuration_with_median_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    codex = _job(tmp_path, "job-a")
    sapiens = _job(tmp_path, "job-b")
    high: dict[str, object] = {"reasoning_effort": "high"}
    _trial(
        codex,
        "t1-1",
        criteria=_criteria("pass"),
        kwargs=high,
        agent_sec=10.0,
        tokens=(100, 40, 10),
    )
    _trial(
        codex,
        "t1-2",
        criteria=_criteria("fail"),
        kwargs=high,
        agent_sec=30.0,
        tokens=(300, 0, 30),
    )
    _trial(codex, "t1-3", criteria=_criteria("pass"), kwargs=high, agent_sec=20.0)
    _trial(
        codex,
        "t2-1",
        criteria=None,
        task="t2",
        checksum="c2",
        kwargs=high,
        agent_sec=None,
        exception="EnvironmentStartTimeoutError",
    )
    _trial(
        sapiens,
        "t1-1",
        criteria=_criteria("unknown"),
        harness="sapiens",
        version="71e93cb",
        kwargs={"config": {"model_reasoning_effort": "medium"}},
        agent_sec=60.0,
        tokens=(500, 100, 50),
    )

    _, report = _compare([sapiens, codex], capsys)

    def median(value: float | None, known: int) -> dict[str, float | int | None]:
        return {"median": value, "known": known}

    sapiens_configuration = {
        "harness": "sapiens",
        "harness_version": "71e93cb",
        "model": "openai/gpt-5",
        "reasoning": "medium",
    }
    summaries = [
        {key: value for key, value in pair.items() if key != "trials"}
        for pair in report["pairs"]
    ]
    assert summaries == [
        {
            "task": "t1",
            "task_checksum": "c1",
            "configuration": CODEX,
            "counts": {
                "trials": 3,
                "pass": 2,
                "fail": 1,
                "unknown": 0,
                "infra_error": 0,
            },
            "pass_rate": pytest.approx(2 / 3),
            "unknown_rate": 0.0,
            "infra_error_rate": 0.0,
            "agent_sec": median(20.0, 3),
            "input_tokens": median(200.0, 2),
            "cached_tokens": median(20.0, 2),
            "output_tokens": median(20.0, 2),
        },
        {
            "task": "t1",
            "task_checksum": "c1",
            "configuration": sapiens_configuration,
            "counts": {
                "trials": 1,
                "pass": 0,
                "fail": 0,
                "unknown": 1,
                "infra_error": 0,
            },
            "pass_rate": None,
            "unknown_rate": 1.0,
            "infra_error_rate": 0.0,
            "agent_sec": median(60.0, 1),
            "input_tokens": median(500.0, 1),
            "cached_tokens": median(100.0, 1),
            "output_tokens": median(50.0, 1),
        },
        {
            "task": "t2",
            "task_checksum": "c2",
            "configuration": CODEX,
            "counts": {
                "trials": 1,
                "pass": 0,
                "fail": 0,
                "unknown": 0,
                "infra_error": 1,
            },
            "pass_rate": None,
            "unknown_rate": 0.0,
            "infra_error_rate": 1.0,
            "agent_sec": median(None, 0),
            "input_tokens": median(None, 0),
            "cached_tokens": median(None, 0),
            "output_tokens": median(None, 0),
        },
    ]


def test_trial_without_harbor_result_is_reported_apart_from_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    _trial(job, "a-pass", criteria=_criteria("pass"))
    (job / "b-running").mkdir()
    (job / "c-corrupt").mkdir()
    (job / "c-corrupt" / "result.json").write_text("{")

    _, report = _compare([job], capsys)

    assert report["incomplete_trials"] == [
        {"job": "job-a", "trial": "b-running", "reason": "result_missing"},
        {"job": "job-a", "trial": "c-corrupt", "reason": "result_invalid"},
    ]
    [pair] = report["pairs"]
    assert pair["counts"]["trials"] == 1


def test_directory_that_is_not_a_harbor_job_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path / "jobs", "job-a")
    _trial(job, "a-pass", criteria=_criteria("pass"))

    for not_a_job in (tmp_path / "jobs", job / "a-pass"):
        with pytest.raises(SystemExit) as exit_info:
            main(["compare", str(not_a_job)])

        assert exit_info.value.code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert f"not a Harbor job directory: {not_a_job.name}" in captured.err


def test_repeated_job_directory_is_rejected_rather_than_counted_twice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    _trial(job, "a-pass", criteria=_criteria("pass"))

    with pytest.raises(SystemExit) as exit_info:
        main(["compare", str(job), str(tmp_path / "." / "job-a")])

    assert exit_info.value.code == 2
    assert capsys.readouterr().out == ""


def test_markdown_report_has_one_table_per_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    high: dict[str, object] = {"reasoning_effort": "high"}
    _trial(
        job,
        "a",
        criteria=_criteria("pass"),
        kwargs=high,
        agent_sec=10.0,
        tokens=(100, 40, 10),
    )
    _trial(
        job,
        "b",
        criteria=_criteria("fail"),
        kwargs=high,
        agent_sec=25.0,
        tokens=(301, 0, 30),
    )
    _trial(
        job,
        "c",
        criteria=None,
        kwargs=high,
        agent_sec=None,
        exception="EnvironmentStartTimeoutError",
    )
    _trial(
        job,
        "d",
        criteria=_criteria("pass"),
        model=None,
        agent_sec=None,
        exception="EnvironmentStartTimeoutError",
    )

    status = main(["compare", "--format", "markdown", str(job)])

    lines = capsys.readouterr().out.splitlines()
    assert status == 0
    codex = lines.index("## codex 0.162.1, model openai/gpt-5, reasoning high")
    assert lines[codex + 4] == (
        "| t1 | c1 | 3 | 1 | 1 | 0 | 1 | 0.50 | 17.5 | 200.5 / 20 / 20 |"
    )
    no_model = lines.index("## codex 0.162.1, model unknown, reasoning unknown")
    assert lines[no_model + 4] == (
        "| t1 | c1 | 1 | 0 | 0 | 0 | 1 | unknown | unknown "
        "| unknown / unknown / unknown |"
    )
