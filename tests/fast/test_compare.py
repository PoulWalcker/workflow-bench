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


def test_transcript_masks_injected_values_across_saved_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    auth_value = "DUMMY_UNLABELLED_AUTH_VALUE_123456"
    nested_value = "DUMMY_NESTED_AUTH_VALUE_123456"
    api_key = "DUMMY_ENV_API_VALUE_123456"
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"auth": {"access": auth_value, "nested": [nested_value]}})
    )
    monkeypatch.setenv("CODEX_AUTH_JSON_PATH", str(auth))
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    job = _job(tmp_path, "private-job")
    _trial(job, "codex", criteria=_criteria("pass"))
    _session(
        job / "codex" / "agent",
        "rollout.jsonl",
        [
            _message("2026-01-01T00:00:00Z", "user", f"bare {auth_value}"),
            {
                "timestamp": "2026-01-01T00:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "one",
                    "output": f'{{"url":"https://example.test/{nested_value}"}}',
                },
            },
            _message("2026-01-01T00:00:02Z", "assistant", f"Done {api_key}"),
        ],
    )
    _trial(job, "sapiens", criteria=_criteria("pass"), harness="sapiens")
    agent = job / "sapiens" / "agent"
    agent.mkdir()
    (agent / "sapiens-state.json").write_text(
        json.dumps(
            {
                "agents": [{"id": "chief", "name": "Chief", "role": "admin"}],
                "turns": [
                    {
                        "id": "one",
                        "agent": "chief",
                        "input": f"bare {nested_value}",
                        "output": f'{{"value":"{auth_value}"}}',
                        "status": "done",
                        "created": "2026-01-01T00:00:00Z",
                    }
                ],
                "workloads": [
                    {
                        "calls": [{"request": auth_value, "output": api_key}],
                        "decisions": [
                            {
                                "agent": "chief",
                                "node": "Assessing",
                                "created": "2026-01-01T00:00:01Z",
                                "response": {
                                    "event": "Completed",
                                    "reason": nested_value,
                                },
                            }
                        ],
                    }
                ],
            }
        )
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert all(value not in output for value in (auth_value, nested_value, api_key))
    assert "[REDACTED]" in output


def test_transcript_marks_unavailable_exact_masking_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CODEX_AUTH_JSON_PATH", raising=False)
    monkeypatch.delenv("CODEX_FORCE_AUTH_JSON", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    job = _job(tmp_path, "offline-job")
    _trial(job, "offline", criteria=_criteria("pass"))
    assert main(["compare", "--transcript", str(job)]) == 0
    assert "[missing: exact-value masking source]" in capsys.readouterr().out


def test_transcript_resolves_saved_agent_auth_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CODEX_AUTH_JSON_PATH", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    secret = "DUMMY_SAVED_AUTH_VALUE_123456"
    api_key = "DUMMY_SAVED_API_VALUE_123456"
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"nested": [{"value": secret}]}))
    job = _job(tmp_path, "saved-source-job")
    config_path = job / "config.json"
    config = json.loads(config_path.read_text())
    config["agents"] = [
        {
            "name": "codex",
            "env": {"CODEX_AUTH_JSON_PATH": str(auth), "OPENAI_API_KEY": api_key},
        }
    ]
    config_path.write_text(json.dumps(config))
    _trial(job, "saved-source", criteria=_criteria("pass"))
    _session(
        job / "saved-source" / "agent",
        "rollout.jsonl",
        [_message("2026-01-01T00:00:00Z", "user", f"{secret} {api_key}")],
    )
    assert main(["compare", "--transcript", str(job)]) == 0
    output = capsys.readouterr().out
    assert secret not in output and api_key not in output
    assert "[missing: exact-value masking source]" not in output


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
    codex = lines.index("## codex 0.162.1, model openai/gpt-5, reasoning high")
    assert lines[codex + 4] == (
        "| t1 | c1 | 3 | 1 | 1 | 0 | 1 | 0.50 | 17.5 | 200.5 / 20 / 20 | unknown |"
    )
    no_model = lines.index("## codex 0.162.1, model unknown, reasoning unknown")
    assert lines[no_model + 4] == (
        "| t1 | c1 | 1 | 0 | 0 | 0 | 1 | unknown | unknown "
        "| unknown / unknown / unknown | unknown |"
    )
