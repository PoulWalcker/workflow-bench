"""`wb compare` over synthetic Harbor job directories, against hand-computed reports."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

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
from harbor.publisher.packager import Packager

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
    sessions: int | None = None,
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
            metadata={"sapiens_session_count": sessions}
            if sessions is not None
            else None,
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


def _session(agent_dir: Path, name: str, rows: list[dict[str, object]]) -> None:
    sessions = agent_dir / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / name).write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def _state(job: Path, trial: str, state: dict[str, object]) -> None:
    agent = job / trial / "agent"
    agent.mkdir(exist_ok=True)
    (agent / "sapiens-state.json").write_text(json.dumps(state))


def test_compare_reports_direct_sapiens_work_from_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "direct", criteria=_criteria("pass"), harness="sapiens")
    _state(
        job,
        "direct",
        {
            "agents": [{"id": "chief"}],
            "turns": [],
            "workloads": [
                {
                    "calls": [{"addressedTo": "chief", "causedBy": None}],
                    "decisions": [
                        {"agent": "chief", "node": "Assessing"},
                        {"agent": "chief", "node": "ReadyToWork"},
                        {"agent": "chief", "node": "Execution"},
                    ],
                }
            ],
        },
    )
    _, report = _compare([job], capsys)
    assert report["pairs"][0]["trials"][0]["delegation"] == {
        "status": "ok",
        "sapi": 1,
        "delegations": 0,
        "specialists_created": 0,
        "steps_by_node": {"Assessing": 1, "Execution": 1, "ReadyToWork": 1},
    }
    assert report["pairs"][0]["delegation"] == {
        "known": 1,
        "delegated": 0,
        "unknown": 0,
    }


def test_compare_reports_delegation_and_clarification_separately(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "delegated", criteria=_criteria("pass"), harness="sapiens")
    _state(
        job,
        "delegated",
        {
            "agents": [{"id": "chief"}, {"id": "specialist"}],
            "turns": [],
            "workloads": [
                {
                    "calls": [
                        {"addressedTo": "chief", "causedBy": None},
                        {"addressedTo": "specialist", "causedBy": "root"},
                        {
                            "addressedTo": "chief",
                            "causedBy": "root",
                            "activation": "RequestClarified",
                        },
                    ],
                    "decisions": [
                        {"agent": "chief", "node": "Assessing"},
                        {"agent": "chief", "node": "Assessing"},
                        {"agent": "chief", "node": "ChiefTriage"},
                        {"agent": "chief", "node": "CreatingSapi"},
                        {"agent": "chief", "node": "Delegation"},
                        {"agent": "chief", "node": "ReadyToWork"},
                        {"agent": "specialist", "node": "Execution"},
                    ],
                }
            ],
        },
    )
    _, report = _compare([job], capsys)
    assert report["pairs"][0]["trials"][0]["delegation"] == {
        "status": "ok",
        "sapi": 2,
        "delegations": 1,
        "specialists_created": 1,
        "steps_by_node": {
            "Assessing": 2,
            "ChiefTriage": 1,
            "CreatingSapi": 1,
            "Delegation": 1,
            "Execution": 1,
            "ReadyToWork": 1,
        },
    }
    assert report["pairs"][0]["delegation"] == {
        "known": 1,
        "delegated": 1,
        "unknown": 0,
    }


def test_compare_preserves_unknown_delegation_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    for name in ("direct", "delegated", "invalid"):
        _trial(job, name, criteria=_criteria("pass"), harness="sapiens")
    _state(
        job,
        "direct",
        {
            "agents": [{"id": "chief"}],
            "turns": [],
            "workloads": [{"calls": [{"addressedTo": "chief"}], "decisions": []}],
        },
    )
    _state(
        job,
        "delegated",
        {
            "agents": [{"id": "chief"}, {"id": "child"}],
            "turns": [],
            "workloads": [
                {
                    "calls": [
                        {"addressedTo": "chief"},
                        {"addressedTo": "child", "causedBy": "root"},
                    ],
                    "decisions": [],
                }
            ],
        },
    )
    (job / "invalid" / "agent").mkdir()
    (job / "invalid" / "agent" / "sapiens-state.json").write_text("{")
    _, three_trial_report = _compare([job], capsys)
    assert three_trial_report["pairs"][0]["delegation"] == {
        "known": 2,
        "delegated": 1,
        "unknown": 1,
    }
    _trial(job, "truncated", criteria=_criteria("pass"), harness="sapiens")
    _state(
        job,
        "truncated",
        {
            "agents": [{"id": "chief"}],
            "turns": [],
            "workloads": [
                {
                    "calls": [{"addressedTo": "chief"}],
                    "decisions": [{"agent": "chief", "node": "Execution"}],
                }
            ],
            "truncated": {"calls": True},
        },
    )
    _, report = _compare([job], capsys)
    trials = {
        trial["trial"]: trial["delegation"] for trial in report["pairs"][0]["trials"]
    }
    assert trials["invalid"] == {
        "status": "invalid",
        "sapi": None,
        "delegations": None,
        "specialists_created": None,
        "steps_by_node": None,
    }
    assert trials["truncated"] == {
        "status": "truncated",
        "sapi": None,
        "delegations": None,
        "specialists_created": None,
        "steps_by_node": {"Execution": 1},
    }
    assert report["pairs"][0]["delegation"] == {
        "known": 2,
        "delegated": 1,
        "unknown": 2,
    }
    assert main(["compare", "--format", "markdown", str(job)]) == 0
    assert "1/2 +2 unknown" in capsys.readouterr().out


def test_delegation_reaches_summary_and_markdown_without_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sapiens = _job(tmp_path, "sapiens-job")
    codex = _job(tmp_path, "codex-job")
    _trial(sapiens, "direct", criteria=_criteria("pass"), harness="sapiens")
    _trial(codex, "plain", criteria=_criteria("pass"))
    _state(
        sapiens,
        "direct",
        {
            "agents": [{"id": "chief"}],
            "turns": [],
            "workloads": [
                {
                    "calls": [{"addressedTo": "chief"}],
                    "decisions": [{"agent": "chief", "node": "Execution"}],
                }
            ],
        },
    )
    assert main(["compare", "--format", "summary", str(sapiens), str(codex)]) == 0
    summary = json.loads(capsys.readouterr().out)
    by_job = {trial["job"]: trial["delegation"] for trial in summary["trials"]}
    assert by_job["sapiens-job"] == {
        "status": "ok",
        "sapi": 1,
        "delegations": 0,
        "specialists_created": 0,
        "steps_by_node": {"Execution": 1},
    }
    assert by_job["codex-job"] is None
    assert main(["compare", "--format", "markdown", str(sapiens), str(codex)]) == 0
    output = capsys.readouterr().out
    assert "| Delegated |" in output
    assert "0/1" in output
    assert "## Trial delegation" in output
    assert "| sapiens-job | direct | ok | 1 | 0 | 0 | Execution: 1 |" in output
    assert (
        "state snapshot is produced inside the agent environment and is diagnostic"
        in output
    )
    assert "—" in output


def test_compare_marks_malformed_decision_nodes_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "malformed", criteria=_criteria("pass"), harness="sapiens")
    _state(
        job,
        "malformed",
        {
            "agents": [{"id": "chief"}],
            "turns": [],
            "workloads": [
                {
                    "calls": [{"addressedTo": "chief"}],
                    "decisions": [{"agent": "chief", "node": "a|injected"}],
                }
            ],
        },
    )
    _, report = _compare([job], capsys)
    assert report["pairs"][0]["trials"][0]["delegation"] == {
        "status": "invalid",
        "sapi": None,
        "delegations": 0,
        "specialists_created": 0,
        "steps_by_node": None,
    }
    assert main(["compare", "--format", "markdown", str(job)]) == 0
    assert "a|injected" not in capsys.readouterr().out


def test_compare_marks_oversized_state_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "oversized", criteria=_criteria("pass"), harness="sapiens")
    agent = job / "oversized" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    _, report = _compare([job], capsys)
    assert report["pairs"][0]["trials"][0]["delegation"] == {
        "status": "too large",
        "sapi": None,
        "delegations": None,
        "specialists_created": None,
        "steps_by_node": None,
    }


def _condition_lock(
    job: Path,
    trial: str,
    task_dir: Path,
    *,
    timeout_sec: int | None = 600,
    hosts: list[str] | None = None,
) -> None:
    digest, _ = Packager.compute_content_hash(task_dir)
    (job / trial / "lock.json").write_text(
        json.dumps(
            {
                "task": {"digest": f"sha256:{digest}", "path": str(task_dir)},
                "agent": {
                    "override_timeout_sec": timeout_sec,
                    "extra_allowed_hosts": hosts or [],
                },
            }
        )
    )


def _task_directory(root: Path, *, level: str = "L1") -> Path:
    root.mkdir(parents=True)
    (root / "task.toml").write_text(
        f'[metadata]\nlevel = "{level}"\n[agent]\ntimeout_sec = 600\n'
        '[environment]\nnetwork_mode = "no-network"\n'
    )
    return root


def _message(
    at: str, role: str, text: str, *, phase: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "message",
        "role": role,
        "content": [
            {"type": "input_text" if role == "user" else "output_text", "text": text}
        ],
    }
    if phase is not None:
        payload["phase"] = phase
    return {"timestamp": at, "type": "response_item", "payload": payload}


def test_transcript_shows_codex_reasoning_summaries_per_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "codex-reasoning")
    _trial(
        job,
        "two-steps",
        criteria=_criteria("pass"),
        kwargs={"config": {"model_reasoning_summary": "auto"}},
    )
    agent = job / "two-steps" / "agent"
    _session(
        agent,
        "first.jsonl",
        [
            {"type": "turn_context", "payload": {"summary": "none"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": [
                        {
                            "type": "summary_text",
                            "text": "I should add 7 and 5. token=SECRET",
                        }
                    ],
                    "encrypted_content": "NEVER_SHOW_CIPHER",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "X" * 600}],
                },
            },
            _message("2026-01-01T00:00:01Z", "assistant", "The sum is 12."),
        ],
    )
    _session(
        agent,
        "second.jsonl",
        [
            {"type": "turn_context", "payload": {"summary": "none"}},
            _message("2026-01-01T00:00:02Z", "assistant", "Finished."),
        ],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Reasoning summary: I should add 7 and 5." in output
    assert "X" * 100 in output and "X" * 501 not in output
    assert "SECRET" not in output and "NEVER_SHOW_CIPHER" not in output
    assert "Reasoning summary: [no summary]" in output
    assert "Reasoning summary setting: auto" in output
    assert "steps with a reasoning summary: 1 of 2" in output
    assert "reasoning summaries: unavailable" not in output


def test_transcript_shows_sapiens_summary_next_to_each_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-reasoning")
    _trial(
        job,
        "three-steps",
        criteria=_criteria("fail"),
        harness="sapiens",
        kwargs={"config": {"model_reasoning_summary": "auto"}},
    )
    agent = job / "three-steps" / "agent"
    for index, summary in enumerate(
        [
            [{"type": "summary_text", "text": "I need a basket total."}],
            [],
            None,
        ]
    ):
        prompt = f"decision at node Step{index}\nContext:\n{{}}"
        reasoning: dict[str, object] = {
            "type": "reasoning",
            "encrypted_content": "NEVER_SHOW_CIPHER",
        }
        if summary is not None:
            reasoning["summary"] = summary
        _session(
            agent,
            f"{index}.jsonl",
            [
                {"type": "turn_context", "payload": {"summary": "none"}},
                _message(f"2026-01-01T00:00:0{index}Z", "user", prompt),
                {"type": "response_item", "payload": reasoning},
                _message(
                    f"2026-01-01T00:00:0{index + 1}Z",
                    "assistant",
                    json.dumps({"event": "Outcome", "reason": "Done"}),
                ),
            ],
        )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert output.index("Reasoning summary: I need a basket total.") < output.index(
        "Decision: Outcome"
    )
    assert output.count("Reasoning summary: [no summary]") == 2
    assert "NEVER_SHOW_CIPHER" not in output
    assert "Reasoning summary setting: auto" in output
    assert "steps with a reasoning summary: 1 of 3" in output


@pytest.mark.parametrize(
    ("setting", "is_unavailable"),
    [("none", False), ("auto", True), (None, True)],
)
def test_transcript_marks_reasoning_unavailable_only_when_requested(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    setting: str | None,
    is_unavailable: bool,
) -> None:
    job = _job(tmp_path, "no-reasoning")
    kwargs: dict[str, object] | None = (
        {"config": {"model_reasoning_summary": setting}}
        if setting is not None
        else None
    )
    _trial(job, "step", criteria=_criteria("pass"), kwargs=kwargs)
    rows: list[dict[str, object]] = [
        _message("2026-01-01T00:00:01Z", "assistant", "Done.")
    ]
    recorded_summary = "auto" if setting == "none" else "none"
    rows.insert(0, {"type": "turn_context", "payload": {"summary": recorded_summary}})
    _session(job / "step" / "agent", "rollout.jsonl", rows)
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert f"Reasoning summary setting: {setting or 'unknown'}" in output
    assert "Reasoning summary: [no summary]" in output
    assert "steps with a reasoning summary: 0 of 1" in output
    assert ("reasoning summaries: unavailable" in output) is is_unavailable


def test_transcript_marks_sapiens_state_only_summary_as_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "state-only")
    _trial(job, "step", criteria=_criteria("fail"), harness="sapiens")
    agent = job / "step" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [{"id": "chief", "name": "Chief"}],
                "turns": [],
                "workloads": [{"decisions": [{"node": "Execution", "agent": "chief"}]}],
            }
        )
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Reasoning summary: [unknown: no aligned Codex session]" in output
    assert "Reasoning summary setting: unknown" in output
    assert "steps with a reasoning summary: unknown of 1" in output
    assert "reasoning summaries: unavailable" not in output


def test_transcript_marks_codex_summary_count_unknown_without_sessions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "missing-session")
    _trial(
        job,
        "step",
        criteria=_criteria("pass"),
        kwargs={"config": {"model_reasoning_summary": "auto"}},
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "[missing: Codex sessions (not collected)]" in output
    assert "steps with a reasoning summary: unknown of unknown" in output
    assert "steps with a reasoning summary: 0 of 0" not in output
    assert "reasoning summaries: unavailable" not in output


def test_transcript_marks_summary_unknown_when_session_has_no_response(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "no-response")
    _trial(job, "step", criteria=_criteria("fail"))
    _session(
        job / "step" / "agent",
        "rollout.jsonl",
        [_message("2026-01-01T00:00:01Z", "user", "Compute the answer")],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Reasoning summary: [unknown: no assistant response]" in output
    assert "steps with a reasoning summary: unknown of 1" in output
    assert "reasoning summaries: unavailable" not in output


def test_transcript_marks_partial_sapiens_summary_evidence_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "partial-sessions")
    _trial(
        job,
        "step",
        criteria=_criteria("pass"),
        harness="sapiens",
        kwargs={"config": {"model_reasoning_summary": "auto"}},
    )
    agent = job / "step" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [{"id": "chief", "name": "Chief"}],
                "turns": [],
                "workloads": [
                    {
                        "decisions": [
                            {"agent": "chief", "node": "First"},
                            {"agent": "chief", "node": "Second"},
                        ]
                    }
                ],
            }
        )
    )
    _session(
        agent,
        "first.jsonl",
        [
            _message(
                "2026-01-01T00:00:01Z",
                "user",
                'decision at node First\nContext:\n{"selfId":"chief"}',
            ),
            {
                "type": "response_item",
                "payload": {
                    "type": "reasoning",
                    "summary": [{"text": "I should check the first step."}],
                },
            },
        ],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Chief — First" in output
    assert "Chief — Second" in output
    assert "Reasoning summary: I should check the first step." in output
    assert "Reasoning summary: [unknown: no aligned Codex session]" in output
    assert "steps with a reasoning summary: unknown of 2" in output
    assert "reasoning summaries: unavailable" not in output


def test_transcript_renders_codex_conversation_and_redacts_identifiers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "codex-job")
    _trial(job, "conversation", criteria=_criteria("pass"), tokens=(12, 2, 3))
    agent = job / "conversation" / "agent"
    _session(
        agent,
        "rollout.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {"creator_account_id": "acct_SECRET"},
            },
            _message(
                "2026-01-01T00:00:01Z",
                "user",
                "Write basket total. OPENAI_API_KEY=sk-secret123456 person@example.com",
            ),
            _message(
                "2026-01-01T00:00:02Z",
                "assistant",
                "I will calculate it.",
                phase="commentary",
            ),
            {
                "timestamp": "2026-01-01T00:00:03Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "call1",
                    "input": "python sum.py",
                },
            },
            {
                "timestamp": "2026-01-01T00:00:04Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call1",
                    "output": [
                        {
                            "type": "text",
                            "text": '{"account_id":"accSensitive","total":1178}',
                        }
                    ],
                },
            },
            _message(
                "2026-01-01T00:00:05Z", "assistant", "Total 1178.", phase="final_answer"
            ),
            {
                "timestamp": "2026-01-01T00:00:06Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 12,
                            "cached_input_tokens": 2,
                            "output_tokens": 3,
                        }
                    },
                },
            },
        ],
    )
    status = main(["compare", "--transcript", str(job)])
    output = capsys.readouterr().out
    assert status == 0
    assert "Write basket total" in output
    assert "I will calculate it" in output
    assert "exec" in output and "python sum.py" in output and "1178" in output
    assert "Final reply" in output and "Total 1178" in output
    assert "00:00:01" in output and "6s" in output
    assert "12 input" in output and "3 output" in output
    assert "Verdict: pass" in output and "c0: pass" in output
    assert all(
        secret not in output
        for secret in (
            "acct_SECRET",
            "sk-secret123456",
            "accSensitive",
            "person@example.com",
        )
    )


def test_transcript_redacts_common_secrets_and_invalid_session_counters(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "codex-job")
    _trial(job, "private", criteria=_criteria("pass"))
    _session(
        job / "private" / "agent",
        "rollout.jsonl",
        [
            _message(
                "2026-01-01T00:00:00Z",
                "user",
                "Authorization: Basic dXNlcjpwYXNz; "
                "AWS_ACCESS_KEY_ID=AKIAEXAMPLE00000000; "
                'account ID is 123456789; password: "a secret phrase"; '
                "password: another secret phrase; "
                "api_token=DEMO_API_TOKEN_123; token=DEMO_TOKEN_123; "
                "Authorization: token DEMO_AUTH_TOKEN_123; "
                "account identifier is 987654321",
            ),
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": "OPENAI_API_KEY=sk-secret123456",
                            "output_tokens": 3,
                        }
                    },
                },
            },
        ],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "[REDACTED]" in output
    assert "unknown input" in output and "3 output" in output
    for secret in (
        "dXNlcjpwYXNz",
        "AKIAEXAMPLE00000000",
        "123456789",
        "a secret phrase",
        "another secret phrase",
        "secret phrase",
        "sk-secret123456",
        "DEMO_API_TOKEN_123",
        "DEMO_TOKEN_123",
        "DEMO_AUTH_TOKEN_123",
        "987654321",
    ):
        assert secret not in output


def test_transcript_uses_pattern_masking_independent_of_host_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unlabelled_value = "DUMMY_UNLABELLED_VALUE_123456"
    auth_a = tmp_path / "auth-a.json"
    auth_b = tmp_path / "auth-b.json"
    auth_a.write_text(json.dumps({"access": unlabelled_value}))
    auth_b.write_text(json.dumps({"access": "DUMMY_OTHER_VALUE_123456"}))
    job = _job(tmp_path, "pattern-only-job")
    config_path = job / "config.json"
    config = json.loads(config_path.read_text())
    config["agents"] = [
        {
            "name": "codex",
            "env": {
                "CODEX_AUTH_JSON_PATH": str(auth_a),
                "OPENAI_API_KEY": "DUMMY_SAVED_API_VALUE_123456",
            },
        }
    ]
    config_path.write_text(json.dumps(config))
    _trial(job, "first", criteria=_criteria("pass"))
    _trial(job, "second", criteria=_criteria("pass"))
    _session(
        job / "first" / "agent",
        "rollout.jsonl",
        [_message("2026-01-01T00:00:00Z", "user", f"bare {unlabelled_value}")],
    )
    monkeypatch.setenv("CODEX_AUTH_JSON_PATH", str(auth_a))
    monkeypatch.setenv("OPENAI_API_KEY", "DUMMY_AMBIENT_API_VALUE_123456")
    assert main(["compare", "--transcript", str(job)]) == 0
    first_output = capsys.readouterr().out
    monkeypatch.setenv("CODEX_AUTH_JSON_PATH", str(auth_b))
    monkeypatch.setenv("OPENAI_API_KEY", "DUMMY_CHANGED_API_VALUE_123456")
    config["agents"][0]["env"]["CODEX_AUTH_JSON_PATH"] = str(auth_b)
    config_path.write_text(json.dumps(config))
    assert main(["compare", "--transcript", str(job)]) == 0
    second_output = capsys.readouterr().out
    notice = (
        "Masking is pattern-based best-effort; check the transcript before sharing it."
    )
    assert first_output == second_output
    assert first_output.startswith(notice + "\n")
    assert first_output.count(notice) == 2
    assert unlabelled_value in first_output


def test_transcript_marks_mixed_timestamp_styles_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "codex-job")
    _trial(job, "mixed-time", criteria=_criteria("pass"))
    _session(
        job / "mixed-time" / "agent",
        "rollout.jsonl",
        [
            _message("2026-01-01T00:00:00Z", "user", "Compute basket"),
            _message("2026-01-01T00:00:01", "assistant", "Done"),
        ],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    assert "Time: [missing: time]" in capsys.readouterr().out


def test_transcript_marks_invalid_sapiens_state_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "invalid-state", criteria=_criteria("pass"), harness="sapiens")
    agent = job / "invalid-state" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text("{}")
    assert main(["compare", "--transcript", str(job)]) == 0
    assert "[missing: Sapiens state (invalid)]" in capsys.readouterr().out
    (agent / "sapiens-state.json").write_text("{")
    assert main(["compare", "--transcript", str(job)]) == 0
    assert "[missing: Sapiens state (unreadable)]" in capsys.readouterr().out
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [],
                "turns": [],
                "workloads": [],
                "truncated": {"account ID is 123456789": True},
            }
        )
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "[missing: Sapiens state (invalid)]" in output
    assert "123456789" not in output


def test_transcript_bounds_entire_session_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "codex-job")
    _trial(job, "crowded", criteria=_criteria("pass"))
    agent = job / "crowded" / "agent"
    _session(agent, "rollout.jsonl", [_message("2026-01-01T00:00:00Z", "user", "Task")])
    for index in range(256):
        (agent / "sessions" / f"extra-{index}.txt").touch()
    assert main(["compare", "--transcript", str(job)]) == 0
    assert "[missing: Codex sessions (too many entries)]" in capsys.readouterr().out


def test_transcript_does_not_assign_missing_chief_transition_to_specialist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "partial", criteria=_criteria("pass"), harness="sapiens")
    agent = job / "partial" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"id": "chief", "name": "Chief"},
                    {"id": "specialist", "name": "BasketExpert"},
                ],
                "turns": [{"input": "Compute basket", "output": "Done"}],
                "workloads": [
                    {
                        "calls": [],
                        "decisions": [
                            {
                                "agent": "chief",
                                "node": "ChiefTriage",
                                "transition": {
                                    "before": "ChiefTriage",
                                    "after": "Delegation",
                                },
                            },
                            {
                                "agent": "specialist",
                                "node": "Execution",
                                "transition": {
                                    "before": "Execution",
                                    "after": "Outcome",
                                },
                            },
                        ],
                    }
                ],
            }
        )
    )
    prompt = (
        "You are handling a Sapiens4 decision at node Execution.\nContext:\n"
        + json.dumps({"selfId": "specialist", "chiefId": "chief"})
    )
    _session(
        agent,
        "specialist.jsonl",
        [_message("2026-01-01T00:00:02Z", "user", prompt)],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "BasketExpert — Execution" in output
    assert "Transition: Execution → Outcome" in output
    assert "Transition: ChiefTriage → Delegation" not in output
    assert "[missing: Codex session for 1 Sapiens decision(s)]" in output


def test_transcript_discloses_truncated_sapiens_chronology(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "truncated", criteria=_criteria("pass"), harness="sapiens")
    agent = job / "truncated" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [],
                "turns": [],
                "workloads": [],
                "truncated": {"decisions": True, "calls": False},
            }
        )
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    assert "[missing: Sapiens state truncated (decisions)]" in capsys.readouterr().out


def test_transcript_does_not_reuse_agentless_transition_between_sapis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "ambiguous", criteria=_criteria("pass"), harness="sapiens")
    agent = job / "ambiguous" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [],
                "turns": [],
                "workloads": [
                    {
                        "calls": [],
                        "decisions": [
                            {
                                "node": "Execution",
                                "transition": {
                                    "before": "Execution",
                                    "after": "Outcome",
                                },
                            }
                        ],
                    }
                ],
            }
        )
    )
    for actor in ("chief", "specialist"):
        prompt = (
            "You are handling a Sapiens4 decision at node Execution.\nContext:\n"
            + json.dumps({"selfId": actor, "chiefId": "chief"})
        )
        _session(
            agent,
            f"{actor}.jsonl",
            [_message("2026-01-01T00:00:00Z", "user", prompt)],
        )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Transition: Execution → Outcome" not in output
    assert "[missing: Codex session for 1 Sapiens decision(s)]" in output


def test_transcript_renders_sapiens_delegation_under_specialist_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "delegated", criteria=_criteria("pass"), harness="sapiens", sessions=2)
    agent = job / "delegated" / "agent"
    agent.mkdir()
    state = {
        "agents": [
            {"id": "chief", "name": "Chief"},
            {"id": "sapi_a", "name": "BasketExpert"},
        ],
        "turns": [{"input": "Calculate basket total", "output": "Basket done"}],
        "workloads": [
            {
                "calls": [
                    {"callId": "first", "addressedTo": "chief", "state": "Delegated"},
                    {
                        "callId": "second",
                        "addressedTo": "sapi_a",
                        "causedBy": "first",
                        "state": "Completed",
                        "request": "Calculate the basket",
                    },
                ],
                "decisions": [
                    {
                        "node": "ChiefTriage",
                        "transition": {
                            "before": "ChiefTriage",
                            "after": "CreatingSapi",
                        },
                    },
                    {
                        "node": "Execution",
                        "transition": {"before": "Execution", "after": "Outcome"},
                    },
                ],
            }
        ],
    }
    (agent / "sapiens-state.json").write_text(json.dumps(state))
    for index, (node, actor, event, reason) in enumerate(
        [
            ("ChiefTriage", "chief", "NewSpecialistNeeded", "Outside my scope"),
            ("Execution", "sapi_a", "Outcome", "I wrote the answer"),
        ]
    ):
        prompt = (
            f"You are handling a Sapiens4 decision at node {node}.\nContext:\n"
            + json.dumps(
                {
                    "selfId": actor,
                    "chiefId": "chief",
                    "originalIntent": "Calculate basket total",
                }
            )
        )
        _session(
            agent,
            f"{index}.jsonl",
            [
                {
                    "timestamp": f"2026-01-01T00:00:0{index}Z",
                    "type": "session_meta",
                    "payload": {},
                },
                _message(f"2026-01-01T00:00:0{index}Z", "user", prompt),
                _message(
                    f"2026-01-01T00:00:0{index + 1}Z",
                    "assistant",
                    json.dumps(
                        {
                            "event": event,
                            "reason": reason,
                            "evidence": ["Fixture request"],
                            "reply": "Basket done" if index else "",
                        }
                    ),
                    phase="final_answer",
                ),
                {
                    "timestamp": f"2026-01-01T00:00:0{index + 1}Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 20,
                                "cached_input_tokens": 0,
                                "output_tokens": 4,
                            }
                        },
                    },
                },
            ],
        )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Chief — ChiefTriage" in output
    assert "BasketExpert — Execution" in output
    assert "NewSpecialistNeeded" in output and "Outside my scope" in output
    assert "Delegation to BasketExpert: Calculate the basket" in output
    assert "Transition: ChiefTriage → CreatingSapi" in output
    assert "Final reply: Basket done" in output
    assert "20 input" in output
    assert "[missing: Sapiens state" not in output


def test_transcript_marks_waiting_for_admin_and_missing_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "waiting", criteria=_criteria("fail"), harness="sapiens")
    agent = job / "waiting" / "agent"
    agent.mkdir()
    prompt = (
        "You are handling a Sapiens4 decision at node ChiefTriage.\nContext:\n"
        + json.dumps(
            {
                "selfId": "chief",
                "chiefId": "chief",
                "originalIntent": "Ambiguous basket",
            }
        )
    )
    _session(
        agent,
        "node.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {},
            },
            _message("2026-01-01T00:00:00Z", "user", prompt),
            _message(
                "2026-01-01T00:00:01Z",
                "assistant",
                json.dumps(
                    {
                        "event": "RequestUnclear",
                        "reason": "Need basket",
                        "evidence": [],
                        "question": "Which basket?",
                    }
                ),
            ),
        ],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    missing = capsys.readouterr().out
    assert "[missing: Sapiens state" in missing
    assert "Question to Admin: Which basket?" in missing
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [{"id": "chief", "name": "Chief"}],
                "turns": [{"input": "Ambiguous basket"}],
                "workloads": [
                    {"calls": [{"state": "WaitingForAdmin"}], "decisions": []}
                ],
            }
        )
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert "WaitingForAdmin: awaiting Admin clarification" in output
    assert "[missing: Sapiens state" not in output


def test_transcript_renders_direct_chief_decision_without_delegation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(job, "direct", criteria=_criteria("pass"), harness="sapiens", sessions=1)
    agent = job / "direct" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [{"id": "chief", "name": "Chief"}],
                "turns": [{"input": "Compute basket", "output": "Completed basket"}],
                "workloads": [
                    {
                        "calls": [{"addressedTo": "chief", "state": "Completed"}],
                        "decisions": [
                            {
                                "agent": "chief",
                                "node": "Execution",
                                "transition": {
                                    "before": "Execution",
                                    "after": "Outcome",
                                },
                            }
                        ],
                    }
                ],
            }
        )
    )
    prompt = (
        "You are handling a Sapiens4 decision at node Execution. "
        + "X" * 200
        + " FULL_PROMPT_MARKER\nContext:\n"
        + json.dumps(
            {"selfId": "chief", "chiefId": "chief", "originalIntent": "Compute basket"}
        )
    )
    _session(
        agent,
        "direct.jsonl",
        [
            {
                "timestamp": "2026-01-01T00:00:00Z",
                "type": "session_meta",
                "payload": {},
            },
            _message("2026-01-01T00:00:00Z", "user", prompt),
            _message(
                "2026-01-01T00:00:01Z",
                "assistant",
                json.dumps(
                    {"event": "Outcome", "reason": "Done", "evidence": ["answer file"]}
                ),
            ),
        ],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    brief = capsys.readouterr().out
    assert "Chief — Execution" in brief and "Decision: Outcome" in brief
    assert "Final reply: Completed basket" in brief
    assert "Delegation to" not in brief
    assert "FULL_PROMPT_MARKER" not in brief
    assert main(["compare", "--transcript", "--full-prompts", str(job)]) == 0
    assert "FULL_PROMPT_MARKER" in capsys.readouterr().out


def test_summary_reads_trial_facts_and_reuses_report_outcomes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    _trial(job, "a-pass", criteria=_criteria("pass"), tokens=(120, 20, 8))
    _trial(job, "b-fail", criteria=_criteria("fail"))
    _trial(job, "c-unknown", criteria=_criteria("unknown"))
    _trial(job, "d-infra", criteria=_criteria("fail"), artifacts_status="failed")

    _, report = _compare([job], capsys)
    status = main(["compare", "--format", "summary", str(job)])
    summary = json.loads(capsys.readouterr().out)

    assert status == 0
    reported = {
        trial["trial"]: trial for pair in report["pairs"] for trial in pair["trials"]
    }
    assert {trial["trial"]: trial["outcome"] for trial in summary["trials"]} == {
        trial: outcome["outcome"] for trial, outcome in reported.items()
    }
    passed = summary["trials"][0]
    assert passed["phases"]["agent_execution"] == {
        "started_at": "2026-01-01T00:00:00Z",
        "duration_seconds": 10.0,
        "status": "finished",
    }
    assert passed["evaluation"]["verdict"] == "pass"
    assert passed["evaluation"]["criteria"] == _criteria("pass")
    assert passed["tokens"] == {
        "input": 120,
        "cached": 20,
        "output": 8,
        "sessions": None,
    }
    assert passed["artifact_manifest"]["status"] == "ok"
    assert passed["artifact_manifest"]["entries"] == [
        {"destination": "artifacts/work/output", "status": "ok"}
    ]
    assert passed["errors"] == []
    assert passed["paths"]["result"] == str(job / "a-pass" / "result.json")
    assert passed["paths"]["evaluation"] == str(
        job / "a-pass" / "verifier" / "evaluation.json"
    )
    assert summary["trials"][3]["artifact_manifest"]["status"] == "failed"
    assert summary["trials"][3]["errors"] == ["artifacts_failed"]


def test_sapiens_session_count_reaches_compare_reports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "sapiens-job")
    _trial(
        job,
        "direct",
        criteria=_criteria("pass"),
        harness="sapiens",
        tokens=(15, 4, 9),
        sessions=2,
    )
    _, report = _compare([job], capsys)
    assert report["pairs"][0]["session_count"] == {"median": 2.0, "known": 1}
    assert report["pairs"][0]["input_tokens"] == {"median": 15.0, "known": 1}
    status = main(["compare", "--format", "summary", str(job)])
    summary = json.loads(capsys.readouterr().out)
    assert status == 0
    assert summary["trials"][0]["tokens"] == {
        "input": 15,
        "cached": 4,
        "output": 9,
        "sessions": 2,
    }


def test_summary_keeps_report_outcomes_for_replayed_trial_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first_job = _job(tmp_path / "first", "job-a")
    second_job = _job(tmp_path / "second", "job-a")
    _trial(first_job, "same-trial", criteria=_criteria("fail"))
    _trial(second_job, "same-trial", criteria=_criteria("pass"))

    _, report = _compare([first_job, second_job], capsys)
    status = main(["compare", "--format", "summary", str(first_job), str(second_job)])
    summary = json.loads(capsys.readouterr().out)

    assert status == 0
    report_outcomes = [
        trial["outcome"] for pair in report["pairs"] for trial in pair["trials"]
    ]
    assert report_outcomes == ["fail", "pass"]
    assert [trial["outcome"] for trial in summary["trials"]] == ["fail", "pass"]


def test_summary_reports_agent_exception_as_safe_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job-a")
    _trial(
        job,
        "agent-timeout",
        criteria=_criteria("fail"),
        exception="AgentTimeoutError",
    )

    status = main(["compare", "--format", "summary", str(job)])
    summary = json.loads(capsys.readouterr().out)

    assert status == 0
    assert summary["trials"][0]["errors"] == ["AgentTimeoutError"]
    assert summary["trials"][0]["phases"]["agent_execution"]["status"] == "finished"


def _trial_outcome(
    trial: str, outcome: str, reason: str | None = None, exception: str | None = None
) -> dict[str, str | None]:
    return {
        "job": "job-a",
        "trial": trial,
        "outcome": outcome,
        "reason": reason,
        "exception": exception,
        "delegation": None,
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
    assert pair["task"] == "t1"
    assert {key: pair["configuration"][key] for key in CODEX} == CODEX
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
    old_fields = {
        "task",
        "task_checksum",
        "counts",
        "pass_rate",
        "unknown_rate",
        "infra_error_rate",
        "agent_sec",
        "input_tokens",
        "cached_tokens",
        "output_tokens",
        "session_count",
    }
    summaries = [
        {
            **{key: pair[key] for key in old_fields},
            "configuration": {key: pair["configuration"][key] for key in CODEX},
        }
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
            "session_count": median(None, 0),
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
            "session_count": median(None, 0),
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
            "session_count": median(None, 0),
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
    codex = lines.index(
        "## codex 0.162.1, model openai/gpt-5, reasoning high, "
        "reasoning summary unknown, web search unknown"
    )
    assert "| t1 | c1 | 3 | — | 1/2 | 1 | 0 | 1 | 0.50 | unknown |" in lines[codex + 4]
    assert (
        "17.5 | 200.5 / 20 / 20 | unknown | high | "
        "0 observed; 3 Trials missing | 0 observed; 3 Trials missing | 3 |"
        in lines[codex + 4]
    )
    no_model = lines.index(
        "## codex 0.162.1, model unknown, reasoning unknown, "
        "reasoning summary unknown, web search unknown"
    )
    assert (
        "| t1 | c1 | 1 | — | 0/0 | 0 | 0 | 1 | unknown | unknown |"
        in lines[no_model + 4]
    )


def test_compare_reports_reliability_criteria_and_observed_effort(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    job = _job(tmp_path, "job")
    for index, statuses in enumerate(
        [("pass", "pass"), ("fail", "unknown"), ("fail", "fail")]
    ):
        name = f"trial-{index}"
        _trial(
            job,
            name,
            criteria=_criteria(
                *cast(tuple[Literal["pass", "fail", "unknown"], ...], statuses)
            ),
            kwargs={
                "reasoning_effort": "medium",
                "config": {"model_reasoning_summary": "auto"},
            },
        )
        _condition_lock(job, name, task)
        if index == 1:
            # A saved external verifier result confirms the producer even
            # when its evaluation contains an unknown criterion.
            result_path = job / name / "result.json"
            saved_result = json.loads(result_path.read_text())
            saved_result["verifier_result"] = VerifierResult(rewards={}).model_dump(
                mode="json"
            )
            result_path.write_text(json.dumps(saved_result))
    for index, effort in enumerate(("low", "xhigh", None)):
        rows: list[dict[str, object]] = []
        if effort is not None:
            rows.append(
                {
                    "type": "turn_context",
                    "payload": {"effort": effort, "summary": "none"},
                }
            )
        if index == 1:
            rows.append(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "summary": [{"text": "Useful thought"}],
                    },
                }
            )
        _session(job / f"trial-{index}" / "agent", "rollout.jsonl", rows)

    _, report = _compare([job], capsys)
    [pair] = report["pairs"]
    assert pair["valid"] == 3
    assert pair["pass_hat_k"] == 0.0
    assert report["pass_hat_k"] == 3
    assert pair["failed_criteria"] == {
        "c0": {"fail": 2, "unknown": 0},
        "c1": {"fail": 1, "unknown": 1},
    }
    assert pair["session_efforts"] == {"low": 1, "xhigh": 1}
    assert pair["sessions"] == {"median": 1.0, "known": 3}
    assert pair["xhigh_sessions"] == 1
    assert pair["unknown_effort_sessions"] == 1
    assert pair["sessions_with_summary"] == 1
    assert pair["configuration"]["reasoning_summary"] == "auto"
    assert report["levels"][0]["level"] == "L1"


def test_compare_counts_criteria_only_after_trusted_verifier_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job")
    _trial(job, "checked", criteria=_criteria("fail"))
    _trial(job, "skipped", criteria=_criteria("fail"), verifier="skipped")
    _trial(job, "shared", criteria=_criteria("fail"), verifier_mode="shared")
    _trial(job, "no-result", criteria=_criteria("unknown"), verifier="failed")

    _, report = _compare([job], capsys)
    [pair] = report["pairs"]
    assert pair["failed_criteria"] == {"c0": {"fail": 1, "unknown": 0}}
    assert {entry["trial"]: entry["outcome"] for entry in pair["trials"]} == {
        "checked": "fail",
        "skipped": "infra_error",
        "shared": "infra_error",
        "no-result": "unknown",
    }


def test_compare_counts_each_criterion_status_once_per_trial(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job")
    _trial(job, "duplicate", criteria=_criteria("fail"))
    evaluation_path = job / "duplicate" / "verifier" / "evaluation.json"
    evaluation = json.loads(evaluation_path.read_text())
    evaluation["criteria"].append(dict(evaluation["criteria"][0]))
    evaluation_path.write_text(json.dumps(evaluation))

    _, report = _compare([job], capsys)
    assert report["pairs"][0]["failed_criteria"] == {"c0": {"fail": 1, "unknown": 0}}


def test_markdown_marks_session_counts_incomplete_when_evidence_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job")
    _trial(job, "observed", criteria=_criteria("pass"), sessions=1)
    _session(
        job / "observed" / "agent",
        "rollout.jsonl",
        [{"type": "turn_context", "payload": {"effort": "xhigh"}}],
    )
    _trial(job, "missing", criteria=_criteria("pass"), sessions=2)

    assert main(["compare", "--format", "markdown", str(job)]) == 0
    output = capsys.readouterr().out
    assert "Session evidence missing Trials" in output
    assert "1 observed; 1 Trial missing" in output
    assert "0 observed; 1 Trial missing" in output


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        (("pass", "pass", "pass"), 1.0),
        (("pass", "pass", "fail"), 0.0),
        (("pass", "fail", "fail"), 0.0),
        (("pass", "pass", "infra"), None),
    ],
)
def test_pass_cubed_uses_only_valid_trials(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    outcomes: tuple[str, str, str],
    expected: float | None,
) -> None:
    job = _job(tmp_path, "job")
    for index, outcome in enumerate(outcomes):
        _trial(
            job,
            f"trial-{index}",
            criteria=None
            if outcome == "infra"
            else _criteria(cast(Literal["pass", "fail", "unknown"], outcome)),
            agent_sec=None if outcome == "infra" else 10,
        )
    _, report = _compare([job], capsys)
    [pair] = report["pairs"]
    assert pair["valid"] == (2 if "infra" in outcomes else 3)
    assert pair["pass_hat_k"] == expected


def test_compare_labels_equal_and_unequal_conditions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    jobs = [_job(tmp_path, "codex-job"), _job(tmp_path, "sapiens-job")]
    for job, harness in zip(jobs, ("codex", "sapiens"), strict=True):
        for index in range(2):
            name = f"trial-{index}"
            _trial(
                job,
                name,
                criteria=_criteria("pass"),
                harness=harness,
                kwargs={"reasoning_effort": "medium"},
            )
            _condition_lock(job, name, task)
    _, report = _compare(jobs, capsys)
    assert report["comparisons"] == [
        {"task": "t1", "status": "comparable", "reasons": []}
    ]

    (task / "instruction.md").write_text("Changed task")
    _condition_lock(
        jobs[1], "trial-0", task, timeout_sec=900, hosts=["provider.example"]
    )
    _, changed = _compare(jobs, capsys)
    assert changed["comparisons"] == [
        {
            "task": "t1",
            "status": "incomparable",
            "reasons": [
                "task_digest_differs",
                "agent_timeout_differs",
                "agent_network_differs",
            ],
        }
    ]


def test_compare_detects_insufficient_valid_model_and_effort(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    codex = _job(tmp_path, "codex-job")
    sapiens = _job(tmp_path, "sapiens-job")
    for index in range(2):
        name = f"trial-{index}"
        _trial(
            codex,
            name,
            criteria=_criteria("pass"),
            kwargs={"reasoning_effort": "medium"},
        )
        _condition_lock(codex, name, task, timeout_sec=None)
        _trial(
            sapiens,
            name,
            criteria=_criteria("pass") if index == 0 else None,
            harness="sapiens",
            model="gpt-6",
            agent_sec=10 if index == 0 else None,
            kwargs={"reasoning_effort": "high"},
        )
        _condition_lock(sapiens, name, task, timeout_sec=None)
    _, report = _compare([codex, sapiens], capsys)
    assert report["comparisons"] == [
        {
            "task": "t1",
            "status": "incomparable",
            "reasons": [
                "insufficient_valid_trials",
                "model_differs",
                "reasoning_effort_differs",
            ],
        }
    ]


def test_compare_uses_trial_environment_hosts_in_agent_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    jobs = [_job(tmp_path, "codex-job"), _job(tmp_path, "sapiens-job")]
    for job, harness in zip(jobs, ("codex", "sapiens"), strict=True):
        for index in range(2):
            name = f"trial-{index}"
            _trial(
                job,
                name,
                criteria=_criteria("pass"),
                harness=harness,
                kwargs={"reasoning_effort": "medium"},
            )
            _condition_lock(job, name, task, hosts=[])
            lock_path = job / name / "lock.json"
            lock = json.loads(lock_path.read_text())
            lock["environment"] = {
                "extra_allowed_hosts": ["provider.example"]
                if harness == "sapiens"
                else []
            }
            lock_path.write_text(json.dumps(lock))

    _, report = _compare(jobs, capsys)
    assert report["comparisons"] == [
        {
            "task": "t1",
            "status": "incomparable",
            "reasons": ["agent_network_differs"],
        }
    ]


def test_compare_ignores_agent_hosts_under_explicit_public_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    (task / "task.toml").write_text(
        '[metadata]\nlevel = "L1"\n[environment]\nnetwork_mode = "no-network"\n'
        '[agent]\ntimeout_sec = 600\nnetwork_mode = "public"\n'
    )
    jobs = [_job(tmp_path, "codex-job"), _job(tmp_path, "sapiens-job")]
    for job, harness in zip(jobs, ("codex", "sapiens"), strict=True):
        for index in range(2):
            name = f"trial-{index}"
            _trial(
                job,
                name,
                criteria=_criteria("pass"),
                harness=harness,
                kwargs={"reasoning_effort": "medium"},
            )
            hosts = ["unused.example"] if harness == "sapiens" else []
            _condition_lock(job, name, task, hosts=hosts)

    _, report = _compare(jobs, capsys)
    assert report["comparisons"] == [
        {"task": "t1", "status": "comparable", "reasons": []}
    ]


def test_compare_uses_effective_agent_timeout_cap_and_multiplier(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    jobs = [_job(tmp_path, "codex-job"), _job(tmp_path, "sapiens-job")]
    for job, harness in zip(jobs, ("codex", "sapiens"), strict=True):
        for index in range(2):
            name = f"trial-{index}"
            _trial(
                job,
                name,
                criteria=_criteria("pass"),
                harness=harness,
                kwargs={"reasoning_effort": "medium"},
            )
            _condition_lock(job, name, task)
            if harness == "sapiens":
                lock_path = job / name / "lock.json"
                lock = json.loads(lock_path.read_text())
                lock["agent"]["max_timeout_sec"] = 300
                lock["timeout_multiplier"] = 2
                lock_path.write_text(json.dumps(lock))

    _, report = _compare(jobs, capsys)
    assert report["comparisons"] == [
        {"task": "t1", "status": "comparable", "reasons": []}
    ]

    for index in range(2):
        lock_path = jobs[1] / f"trial-{index}" / "lock.json"
        lock = json.loads(lock_path.read_text())
        lock["agent_timeout_multiplier"] = 1
        lock_path.write_text(json.dumps(lock))
    _, changed = _compare(jobs, capsys)
    assert changed["comparisons"] == [
        {
            "task": "t1",
            "status": "incomparable",
            "reasons": ["agent_timeout_differs"],
        }
    ]


def test_level_summary_uses_verified_task_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _task_directory(tmp_path / "first")
    second = _task_directory(tmp_path / "second")
    missing = _task_directory(tmp_path / "missing")
    vanished = _task_directory(tmp_path / "vanished")
    job = _job(tmp_path, "job")
    for name, task_name, task_dir, status in (
        ("a", "t1", first, "pass"),
        ("b", "t2", second, "fail"),
        ("c", "t3", missing, "unknown"),
        ("d", "t4", vanished, "unknown"),
    ):
        _trial(
            job,
            name,
            task=task_name,
            checksum=task_name,
            criteria=_criteria(status),
        )
        _condition_lock(job, name, task_dir)
    (missing / "instruction.md").write_text("Changed after Trial")
    vanished.rename(tmp_path / "moved")
    _, report = _compare([job], capsys)
    levels = {entry["level"]: entry for entry in report["levels"]}
    assert levels["L1"]["tasks"] == 2
    assert levels["L1"]["covered_tasks"] == 2
    assert levels["L1"]["mean_pass_rate"] == 0.5
    assert levels["L1"]["failed_criteria"] == {"c0": {"fail": 1, "unknown": 0}}
    assert levels["unknown"]["tasks"] == 2
    assert levels["unknown"]["unknown"] == 2


def test_markdown_shows_descriptive_comparison_and_levels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    jobs = [_job(tmp_path, "codex-job"), _job(tmp_path, "sapiens-job")]
    for job, harness in zip(jobs, ("codex", "sapiens"), strict=True):
        for index, status in enumerate(("pass", "fail", "pass")):
            name = f"trial-{index}"
            _trial(
                job,
                name,
                criteria=_criteria(cast(Literal["pass", "fail"], status)),
                harness=harness,
                kwargs={
                    "reasoning_effort": "medium",
                    "config": {
                        "model_reasoning_summary": "auto",
                        "web_search": "disabled",
                    },
                },
                tokens=(100, 20, 10),
                sessions=1,
            )
            _condition_lock(job, name, task)
    assert main(["compare", "--format", "markdown", *map(str, jobs)]) == 0
    output = capsys.readouterr().out
    assert "Pass^3 (k=3)" in output
    assert "2/3" in output
    assert "Median tokens in / cached / out" in output
    assert "Base effort" in output and "xhigh sessions" in output
    assert "reasoning summary auto" in output
    assert "web search disabled" in output
    assert "## Comparison" in output and "comparable" in output
    assert "## Per-level summary" in output and "L1" in output
    assert "overall score" not in output.lower()
    assert "better" not in output.lower() and "worse" not in output.lower()


def test_level_summary_assigns_each_trial_by_its_own_verified_level(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    job = _job(tmp_path, "job")
    _trial(job, "pass", criteria=_criteria("pass"))
    _condition_lock(job, "pass", task)
    _trial(job, "unknown", criteria=_criteria("unknown"))
    _condition_lock(job, "unknown", task)
    (job / "unknown" / "lock.json").write_text(
        json.dumps(
            {
                "task": {"digest": "sha256:stale", "path": str(task)},
                "agent": {"override_timeout_sec": 600, "extra_allowed_hosts": []},
            }
        )
    )
    _, report = _compare([job], capsys)
    levels = {entry["level"]: entry for entry in report["levels"]}
    assert levels["L1"]["tasks"] == 1
    assert levels["L1"]["covered_tasks"] == 1
    assert levels["L1"]["mean_pass_rate"] == 1.0
    assert levels["unknown"]["tasks"] == 1
    assert levels["unknown"]["covered_tasks"] == 0
    assert levels["unknown"]["unknown"] == 1


def test_level_is_unknown_when_task_exceeds_digest_read_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = _task_directory(tmp_path / "task")
    (task / "tests").mkdir()
    with (task / "tests" / "large.bin").open("wb") as stream:
        stream.seek(64 * 1024 * 1024)
        stream.write(b"x")
    job = _job(tmp_path, "job")
    _trial(job, "trial", criteria=_criteria("pass"))
    _condition_lock(job, "trial", task)

    _, report = _compare([job], capsys)
    assert report["pairs"][0]["level"] == "unknown"
    assert report["levels"][0]["level"] == "unknown"


def test_summary_setting_is_part_of_the_saved_configuration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job")
    _trial(
        job,
        "auto",
        criteria=_criteria("pass"),
        kwargs={"config": {"model_reasoning_summary": "auto"}},
    )
    _trial(
        job,
        "detailed",
        criteria=_criteria("pass"),
        kwargs={"reasoning_summary": "detailed"},
    )
    _trial(job, "absent", criteria=_criteria("pass"))
    _, report = _compare([job], capsys)
    assert [pair["configuration"]["reasoning_summary"] for pair in report["pairs"]] == [
        None,
        "auto",
        "detailed",
    ]


def test_session_effort_counts_each_observed_value_once_per_session(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job")
    _trial(job, "one", criteria=_criteria("pass"))
    _session(
        job / "one" / "agent",
        "rollout.jsonl",
        [
            {"type": "turn_context", "payload": {"effort": "low"}},
            {"type": "turn_context", "payload": {"effort": "xhigh"}},
            {"type": "turn_context", "payload": {"effort": "xhigh"}},
        ],
    )
    _, report = _compare([job], capsys)
    [pair] = report["pairs"]
    assert pair["session_efforts"] == {"low": 1, "xhigh": 1}
    assert pair["xhigh_sessions"] == 1


def test_price_estimate_uses_harbor_tokens_for_both_harnesses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prices = tmp_path / "openai-api-prices-2026-10-14.json"
    prices.write_text(
        json.dumps(
            {
                "models": {
                    "openai/gpt-5": {
                        "input_per_million": 2.0,
                        "cached_input_per_million": 0.1,
                        "output_per_million": 10.0,
                        "tier": "standard",
                        "context_band": "short (<=272K input tokens per request)",
                        "source_url": "https://developers.openai.com/api/docs/pricing",
                        "retrieved_on": "2026-10-14",
                    }
                }
            }
        )
    )
    codex = _job(tmp_path, "codex")
    sapiens = _job(tmp_path, "sapiens")
    _trial(codex, "one", criteria=_criteria("pass"), tokens=(100, 20, 10))
    saved = codex / "one" / "result.json"
    native_result = json.loads(saved.read_text())
    native_result["agent_result"]["cost_usd"] = 999.0
    saved.write_text(json.dumps(native_result))
    _trial(codex, "two", criteria=_criteria("fail"), tokens=(200, 50, 20))
    _trial(codex, "unknown-tokens", criteria=_criteria("pass"), tokens=(None, 0, 10))
    _trial(codex, "bad-cache", criteria=_criteria("pass"), tokens=(5, 10, 1))
    _trial(
        sapiens,
        "one",
        criteria=_criteria("pass"),
        harness="sapiens",
        tokens=(100, 20, 10),
    )
    _trial(
        sapiens,
        "missing-model",
        criteria=_criteria("pass"),
        harness="sapiens",
        model="other",
    )

    assert main(["compare", "--prices", str(prices), str(codex), str(sapiens)]) == 0
    report = json.loads(capsys.readouterr().out)
    pairs = {
        pair["configuration"]["harness"]: pair
        for pair in report["pairs"]
        if pair["configuration"]["model"] == "openai/gpt-5"
    }
    codex_cost = pairs["codex"]["cost_usd"]
    assert codex_cost == {
        "median": pytest.approx(0.0003835),
        "total": pytest.approx(0.000767),
        "known": 2,
    }
    assert {
        trial["trial"]: trial["cost_usd"] for trial in pairs["codex"]["trial_costs"]
    } == {
        "one": pytest.approx(0.000262),
        "two": pytest.approx(0.000505),
        "unknown-tokens": None,
        "bad-cache": None,
    }
    assert pairs["sapiens"]["trial_costs"][0]["cost_usd"] == pytest.approx(0.000262)
    assert next(
        pair
        for pair in report["pairs"]
        if pair["configuration"]["model"] == "openai/other"
    )["cost_usd"] == {"median": None, "total": None, "known": 0}
    assert (
        report["price_estimate"]["label"]
        == "estimate by OpenAI API list price as of 2026-10-14"
    )
    assert (
        report["price_estimate"]["source_url"]
        == "https://developers.openai.com/api/docs/pricing"
    )
    assert (
        "cache-write tokens and the long-context band are not modelled"
        in report["price_estimate"]["limits"]
    )

    assert (
        main(["compare", "--format", "markdown", "--prices", str(prices), str(codex)])
        == 0
    )
    markdown = capsys.readouterr().out
    assert "estimate by OpenAI API list price as of 2026-10-14" in markdown
    assert "https://developers.openai.com/api/docs/pricing" in markdown
    assert "cache-write tokens and the long-context band are not modelled" in markdown
    assert "unknown" in markdown


def test_price_estimate_is_unknown_without_price_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(tmp_path, "job")
    _trial(job, "one", criteria=_criteria("pass"), tokens=(100, 20, 10))
    _, report = _compare([job], capsys)
    assert report["pairs"][0]["trial_costs"][0]["cost_usd"] is None
    assert report["pairs"][0]["cost_usd"] == {"median": None, "total": None, "known": 0}


@pytest.mark.parametrize("invalid", ["missing", "negative", "infinite"])
def test_invalid_price_file_exits_two_without_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], invalid: str
) -> None:
    job = _job(tmp_path, "job")
    model = {
        "input_per_million": 2.0,
        "cached_input_per_million": 0.1,
        "output_per_million": 10.0,
        "tier": "standard",
        "context_band": "short (<=272K input tokens per request)",
        "source_url": "https://developers.openai.com/api/docs/pricing",
        "retrieved_on": "2026-10-14",
    }
    if invalid == "missing":
        del model["tier"]
    elif invalid == "negative":
        model["input_per_million"] = -1.0
    else:
        model["input_per_million"] = float("inf")
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"models": {"openai/gpt-5": model}}))
    with pytest.raises(SystemExit) as error:
        main(["compare", "--prices", str(prices), str(job)])
    captured = capsys.readouterr()
    assert error.value.code == 2
    assert captured.out == ""
    assert "invalid price file" in captured.err
