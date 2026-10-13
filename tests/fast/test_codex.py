"""Codex wiring at the native Harbor process seam, without Docker or models."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_bench.composer import (
    collect_codex_usage,
    read_codex_limits,
)
from workflow_bench.data import DataError


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
