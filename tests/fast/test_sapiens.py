"""Sapiens state and native-session behavior at the adapter seam."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
import yaml
from harbor.agents.factory import AgentFactory
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.job.config import JobConfig

from workflow_bench.composer import collect_sapiens_usage
from workflow_bench_integrations.sapiens import SapiensCompletion, SapiensInstalledAgent


def test_direct_chief_reply_finishes_after_two_distinct_quiet_pulses() -> None:
    completion = SapiensCompletion()
    snapshot = {
        "pulse": {"id": "pulse-a", "numbers": {"bpm60": 4}},
        "turns": [{"status": "done"}],
        "workloads": [],
        "run_activity": {},
    }
    assert completion.observe(snapshot) == "working"
    assert completion.observe(snapshot) == "working"
    snapshot["pulse"] = {"id": "pulse-a", "numbers": {"bpm60": 5}}
    assert completion.observe(snapshot) == "completed"


def test_quiet_pulses_must_be_consecutive_after_delegated_work() -> None:
    completion = SapiensCompletion()
    snapshot = {
        "pulse": {"id": "pulse-a", "numbers": {"bpm60": 1}},
        "turns": [{"status": "done"}],
        "workloads": [{"state": "Completed"}],
        "run_activity": {},
    }
    assert completion.observe(snapshot) == "working"
    snapshot["pulse"] = {"id": "pulse-a", "numbers": {"bpm60": 3}}
    assert completion.observe(snapshot) == "working"
    snapshot["workloads"] = [{"state": "Delegated"}]
    assert completion.observe(snapshot) == "working"
    snapshot["workloads"] = [{"state": "Completed"}]
    snapshot["pulse"] = {"id": "pulse-a", "numbers": {"bpm60": 4}}
    assert completion.observe(snapshot) == "working"
    snapshot["pulse"] = {"id": "pulse-a", "numbers": {"bpm60": 5}}
    assert completion.observe(snapshot) == "completed"


@pytest.mark.parametrize(
    "state,expected",
    [
        ("WaitingForAdmin", "agent_outcome"),
        ("Failed", "agent_outcome"),
        ("Interrupted", "agent_outcome"),
        ("Unresolved", "agent_outcome"),
        ("Completed", "completed"),
    ],
)
def test_terminal_workload_is_an_agent_outcome_or_completion(
    state: str, expected: str
) -> None:
    completion = SapiensCompletion()
    for tick in (1, 2):
        decision = completion.observe(
            {
                "pulse": {"id": "pulse-a", "numbers": {"bpm60": tick}},
                "turns": [{"status": "done"}],
                "workloads": [{"state": state}],
                "run_activity": {},
            }
        )
    assert decision == expected


@pytest.mark.parametrize(
    "turn_status,workload_state,activity",
    [
        ("queued", "Completed", {}),
        ("running", "Completed", {}),
        ("output_pending", "Completed", {}),
        ("done", "Queued", {}),
        ("done", "Running", {}),
        ("done", "Delegated", {}),
        ("done", "Completed", {"turn": "active"}),
    ],
)
def test_active_state_never_looks_finished(
    turn_status: str, workload_state: str, activity: dict[str, str]
) -> None:
    completion = SapiensCompletion()
    for tick in (1, 2, 3):
        assert (
            completion.observe(
                {
                    "pulse": {"id": "pulse-a", "numbers": {"bpm60": tick}},
                    "turns": [{"status": turn_status}],
                    "workloads": [{"state": workload_state}],
                    "run_activity": activity,
                }
            )
            == "working"
        )


def test_active_state_remains_bounded_by_agent_timeout() -> None:
    completion = SapiensCompletion()

    async def poll_until_complete() -> None:
        tick = 0
        while True:
            tick += 1
            if (
                completion.observe(
                    {
                        "pulse": {"id": "pulse-a", "numbers": {"bpm60": tick}},
                        "turns": [{"status": "running"}],
                        "workloads": [],
                        "run_activity": {},
                    }
                )
                != "working"
            ):
                return
            await asyncio.sleep(0.001)

    with pytest.raises(TimeoutError):
        asyncio.run(asyncio.wait_for(poll_until_complete(), timeout=0.01))


def test_sapiens_usage_sums_last_cumulative_event_of_every_session(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for name, totals in {
        "chief.jsonl": [(2, 0, 1), (5, 1, 3)],
        "specialist.jsonl": [(7, 2, 4), (10, 3, 6)],
    }.items():
        (sessions / name).write_text(
            "".join(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": input_tokens,
                                    "cached_input_tokens": cached_tokens,
                                    "output_tokens": output_tokens,
                                }
                            },
                        },
                    }
                )
                + "\n"
                for input_tokens, cached_tokens, output_tokens in totals
            )
        )
    usage = collect_sapiens_usage(tmp_path)
    assert usage == {
        "input_tokens": 15,
        "cached_input_tokens": 4,
        "output_tokens": 9,
        "session_count": 2,
    }


def test_sapiens_usage_keeps_last_cumulative_event_after_unmeasured_event(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "chief.jsonl").write_text(
        "\n".join(
            json.dumps(event)
            for event in (
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 5,
                                "cached_input_tokens": 1,
                                "output_tokens": 2,
                            }
                        },
                    },
                },
                {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
            )
        )
        + "\n"
    )
    assert collect_sapiens_usage(tmp_path) == {
        "input_tokens": 5,
        "cached_input_tokens": 1,
        "output_tokens": 2,
        "session_count": 1,
    }


def test_sapiens_usage_rejects_invalid_counters_within_one_session(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for name, input_tokens, cached_tokens in (
        ("chief.jsonl", 1, 2),
        ("specialist.jsonl", 9, 0),
    ):
        (sessions / name).write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": input_tokens,
                                "cached_input_tokens": cached_tokens,
                                "output_tokens": 0,
                            }
                        },
                    },
                }
            )
            + "\n"
        )
    assert collect_sapiens_usage(tmp_path) == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "session_count": 2,
    }


@pytest.mark.parametrize("content,count", [("{broken\n", None), ("{}\n", 1)])
def test_malformed_or_unmeasured_session_keeps_tokens_unknown(
    tmp_path: Path, content: str, count: int | None
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "rollout.jsonl").write_text(content)
    assert collect_sapiens_usage(tmp_path) == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "session_count": count,
    }


def test_missing_session_logs_do_not_claim_zero_sessions(tmp_path: Path) -> None:
    assert collect_sapiens_usage(tmp_path) == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "session_count": None,
    }


def test_sapiens_example_builds_agent_with_native_model_and_reasoning(
    tmp_path: Path,
) -> None:
    config = JobConfig.model_validate(
        yaml.safe_load(Path("examples/sapiens/job.yaml").read_text())
    )
    agent = AgentFactory.create_agent_from_config(config.agents[0], logs_dir=tmp_path)
    assert isinstance(agent, SapiensInstalledAgent)
    assert agent.model_name == "openai/gpt-6.1-sol"
    assert agent.version() == "0.162.1"
    assert isinstance(agent.config_source, dict)
    assert agent.config_source["model_reasoning_effort"] == "low"
    assert config.agents[0].kwargs["reasoning_effort"] == "low"
    assert config.jobs_dir.is_absolute()
    assert (
        config.environment.import_path
        == "workflow_bench.harbor:DeadlineDockerEnvironment"
    )


def test_sapiens_agent_populates_harbor_context_from_native_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "one.jsonl").write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 2,
                            "output_tokens": 3,
                        }
                    },
                },
            }
        )
        + "\n"
    )
    config = JobConfig.model_validate(
        yaml.safe_load(Path("examples/sapiens/job.yaml").read_text())
    )
    agent = AgentFactory.create_agent_from_config(config.agents[0], logs_dir=tmp_path)
    monkeypatch.setattr(agent, "_resolve_auth_json_path", lambda: None)
    monkeypatch.setattr(agent, "_upload_effective_config", AsyncMock(return_value=None))
    monkeypatch.setattr(
        agent,
        "exec_as_agent",
        AsyncMock(return_value=SimpleNamespace(return_code=0)),
    )

    def state(tick: int) -> str:
        return json.dumps(
            {
                "pulse": {"id": "pulse-a", "numbers": {"bpm60": tick}},
                "turns": [{"status": "done"}],
                "workloads": [],
                "run_activity": {},
            }
        )

    environment = cast(
        BaseEnvironment,
        SimpleNamespace(
            exec=AsyncMock(
                side_effect=[
                    SimpleNamespace(return_code=0, stdout="{}"),
                    SimpleNamespace(
                        return_code=0,
                        stdout=json.dumps(
                            {
                                "schema_version": 1,
                                "ok": True,
                                "data": {"id": "a" * 32},
                            }
                        ),
                    ),
                    SimpleNamespace(return_code=0, stdout=state(1)),
                    SimpleNamespace(return_code=0, stdout=state(2)),
                ]
            )
        ),
    )
    context = AgentContext()
    asyncio.run(agent.run("fixture instruction", environment, context))
    assert context.is_empty(), "Harbor populates native usage only for empty contexts"
    agent.populate_context_post_run(context)
    assert (
        context.n_input_tokens,
        context.n_cache_tokens,
        context.n_output_tokens,
    ) == (
        10,
        2,
        3,
    )
    assert context.metadata == {
        "sapiens_outcome": "completed",
        "sapiens_session_count": 1,
    }
    assert context.model_usage == {}
