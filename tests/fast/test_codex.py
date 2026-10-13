"""Codex wiring at the native Harbor process seam, without Docker or models."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_bench.composer import (
    codex_preflight,
    collect_codex_usage,
    read_codex_limits,
)
from workflow_bench.contracts import JsonValue
from workflow_bench.data import DataError


def test_chatgpt_native_preflight_requires_authorization_not_api_spending_cap(
    config_data: dict[str, JsonValue],
) -> None:
    composer = {
        "mode": "model",
        "image": "sha256:" + "d" * 64,
        "cli_version": "0.118.0",
        "model": "gpt-6.1-sol",
        "reasoning_effort": "low",
        "exploration_max_calls": 40,
        "authentication": "chatgpt",
    }
    with pytest.raises(DataError, match="model_not_authorized"):
        codex_preflight(composer, budget=None, runtime=config_data, authorized=False)
    with pytest.raises(DataError, match="codex_auth_required"):
        codex_preflight(composer, budget=None, runtime=config_data, authorized=True)
    plan = codex_preflight(
        composer,
        budget=None,
        runtime=config_data,
        authorized=True,
        auth_path=Path("/explicit/host/auth.json"),
    )
    assert plan["execution_enabled"] is True
    assert plan["provider"] == "chatgpt_subscription"
    assert plan["max_attempts"] == 2


def test_model_free_label_cannot_enable_subscription_auth(
    config_data: dict[str, JsonValue],
) -> None:
    with pytest.raises(DataError, match="invalid_model_free_config"):
        codex_preflight(
            {
                "mode": "model-free",
                "image": "sha256:" + "d" * 64,
                "cli_version": "0.118.0",
                "model": "synthetic",
                "reasoning_effort": "low",
                "exploration_max_calls": 4,
                "authentication": "chatgpt",
            },
            budget=None,
            runtime=config_data,
            authorized=False,
            auth_path=Path("/explicit/host/auth.json"),
        )


@pytest.mark.parametrize("used,expected", [(25, None), (100, "subscription_exhausted")])
def test_subscription_limits_come_from_native_account_not_run_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, used: int, expected: str | None
) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"auth_mode": "chatgpt", "tokens": {"access_token": "test"}})
    )
    executable = tmp_path / "codex"
    limits = {
        "ordinaryUsageAllowed": True,
        "rateLimits": {
            "primary": {"usedPercent": used, "windowDurationMins": 10080},
            "secondary": None,
            "rateLimitReachedType": None,
        },
    }
    executable.write_text(
        "#!/usr/bin/env python3\nimport json, sys, os\n"
        "from pathlib import Path\n"
        "assert json.loads((Path(os.environ['CODEX_HOME'])/'auth.json').read_text())"
        "['auth_mode'] == 'chatgpt'\n"
        "for line in sys.stdin:\n"
        " d=json.loads(line)\n"
        " if d.get('method') == 'initialize':"
        " print(json.dumps({'id':d['id'],'result':{}}),flush=True)\n"
        " elif d.get('method') == 'account/rateLimits/read':"
        f" print(json.dumps({{'id':d['id'],'result':{limits!r}}}),flush=True)\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    if expected:
        with pytest.raises(DataError, match=expected):
            read_codex_limits(auth, timeout_sec=5)
    else:
        assert (
            read_codex_limits(auth, timeout_sec=5)["rateLimits"]["primary"][
                "usedPercent"
            ]
            == 25
        )


@pytest.mark.parametrize(
    "authorized,expected",
    [(False, "model_not_authorized"), (True, "provider_enforcement_unverified")],
)
def test_codex_preflight_never_trusts_declared_enforcement_or_opens_credentials(
    config_data: dict[str, JsonValue], authorized: bool, expected: str
) -> None:
    # A run config can declare a finalized cap and enforcement; it cannot attest them.
    budget = {
        "finalized": True,
        "credential_cap_usd": 5,
        "enforcement": {"usd": "credential_cap"},
    }
    composer = {
        "mode": "model",
        "image": "sha256:" + "d" * 64,
        "cli_version": "0.118.0",
        "model": "synthetic",
        "reasoning_effort": "low",
        "exploration_max_calls": 40,
    }
    with pytest.raises(DataError, match=expected):
        codex_preflight(
            composer, budget=budget, runtime=config_data, authorized=authorized
        )


def test_usage_reads_last_cumulative_event_preserving_missing_and_zero(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    rollout = sessions / "rollout-synthetic.jsonl"
    events = [
        {
            "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": counts}},
        }
        for counts in [
            {"input_tokens": 7, "output_tokens": 2, "cached_input_tokens": 0},
            {"input_tokens": 10, "output_tokens": 3, "cached_input_tokens": 0},
            {"input_tokens": 10, "output_tokens": 3, "cached_input_tokens": 0},
        ]
    ]
    rollout.write_text("".join(json.dumps(e) + "\n" for e in events))
    usage = collect_codex_usage(
        tmp_path,
        prices={
            "input_per_million": 2,
            "cached_input_per_million": 1,
            "output_per_million": 4,
        },
    )
    assert usage["input_tokens"] == 10 and usage["output_tokens"] == 3
    assert usage["cached_input_tokens"] == 0
    assert usage["usd"] == pytest.approx(0.000032)
    assert usage["model_calls"] is None
    rollout.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "info": {"total_token_usage": {"input_tokens": 0}},
                },
            }
        )
        + "\n"
    )
    usage = collect_codex_usage(tmp_path)
    assert usage["input_tokens"] == 0 and usage["output_tokens"] is None
    assert usage["usd"] is None
    rollout.write_text("{partial")
    assert collect_codex_usage(tmp_path)["input_tokens"] is None
    rollout.write_bytes(b"\xff")
    assert collect_codex_usage(tmp_path)["input_tokens"] is None


def test_special_session_file_cannot_block_usage_collection(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    os.mkfifo(sessions / "rollout.jsonl")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; from pathlib import Path; "
                "from workflow_bench.composer import collect_codex_usage; "
                "print(json.dumps(collect_codex_usage(Path(sys.argv[1]))))"
            ),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    usage = json.loads(result.stdout)
    assert usage["raw_refs"] == ["sessions/rollout.jsonl"]
    assert usage["input_tokens"] is None and usage["usd"] is None


@pytest.mark.parametrize(
    "kind", ["fifo", "symlink", "large", "linked_directory", "derived_directory"]
)
def test_native_session_ingestion_is_bounded_and_cannot_read_linked_data(
    tmp_path: Path, kind: str
) -> None:
    sessions = tmp_path / "sessions/2026/10/12"
    sessions.mkdir(parents=True)
    path = sessions / "rollout.jsonl"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "large":
        with path.open("wb") as stream:
            stream.truncate(33 * 1024 * 1024)
    else:
        private = tmp_path / "private"
        private.mkdir()
        (private / "rollout.jsonl").write_text('{"secret":"must not read"}\n')
        if kind == "symlink":
            path.symlink_to(private / "rollout.jsonl")
        else:
            (sessions / "linked").symlink_to(private, target_is_directory=True)
    if kind == "derived_directory":
        (tmp_path / "trajectory.json").mkdir()
        (tmp_path / "trajectory.json/child").write_text("candidate")
    else:
        os.mkfifo(tmp_path / "trajectory.json")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pathlib import Path; import sys; "
                "from harbor.agents.factory import AgentFactory; "
                "from harbor.models.trial.config import AgentConfig; "
                "from harbor.models.agent.context import AgentContext; "
                "p=Path(sys.argv[1]); "
                "a=AgentFactory.create_agent_from_config("
                "AgentConfig(import_path='workflow_bench.composer:SessionSafeCodex'),"
                " logs_dir=p); "
                "assert a.convert_trajectory(p) is None; "
                "context=AgentContext(); a.populate_context_post_run(context); "
                "assert context.n_input_tokens is None; "
                "assert context.model_usage == {}"
            ),
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field", ["mode", "reasoning_effort"])
def test_invalid_composer_config_is_rejected_without_setup(
    config_data: dict[str, JsonValue], field: str
) -> None:
    composer = {
        "mode": "model-free",
        "image": "sha256:" + "d" * 64,
        "cli_version": "0.118.0",
        "model": "synthetic",
        "reasoning_effort": "low",
        "exploration_max_calls": 4,
    }
    composer[field] = []
    with pytest.raises(DataError, match="invalid_composer_config"):
        codex_preflight(composer, budget=None, runtime=config_data, authorized=False)
