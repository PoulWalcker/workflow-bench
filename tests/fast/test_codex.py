"""Codex wiring at the native Harbor process seam, without Docker or models."""

import asyncio
import json
from pathlib import Path

import pytest
from harbor.models.trial.config import AgentConfig
from harbor.trial.trial import Trial

from workflow_bench.cli import load_config
from workflow_bench.harbor import run_native_trial


def test_chatgpt_native_preflight_requires_authorization_not_api_spending_cap(
    config_data,
):
    from workflow_bench.composer import codex_preflight
    from workflow_bench.data import DataError

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


def test_model_free_label_cannot_enable_subscription_auth(config_data):
    from workflow_bench.composer import codex_preflight
    from workflow_bench.data import DataError

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
    tmp_path, monkeypatch, used, expected
):
    import os

    from workflow_bench.composer import read_codex_limits
    from workflow_bench.data import DataError

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
        "assert json.loads((Path(os.environ['CODEX_HOME'])/'auth.json').read_text())['auth_mode'] == 'chatgpt'\n"
        "for line in sys.stdin:\n"
        " d=json.loads(line)\n"
        " if d.get('method') == 'initialize': print(json.dumps({'id':d['id'],'result':{}}),flush=True)\n"
        f" elif d.get('method') == 'account/rateLimits/read': print(json.dumps({{'id':d['id'],'result':{limits!r}}}),flush=True)\n"
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


def test_native_trial_accepts_codex_config_and_bounds_setup(
    tmp_path, monkeypatch, config_data, native_task_files
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path)
    seen = []

    class ProcessObserved(Exception):
        pass

    async def create(configuration):
        seen.append(configuration)
        raise ProcessObserved()

    async def prepared(path):
        pytest.fail("process has not run")

    monkeypatch.setattr(Trial, "create", create)
    agent = AgentConfig(
        name="codex",
        model_name="openai/synthetic",
        kwargs={"version": "0.118.0", "config": {"web_search": "disabled"}},
    )
    with pytest.raises(ProcessObserved):
        asyncio.run(
            run_native_trial(
                native_task_files[0],
                "synthetic",
                prepared,
                config=config,
                agent=agent,
                verify=False,
            )
        )
    assert seen[0].agent.name == "codex"
    assert seen[0].agent.override_setup_timeout_sec == config.setup_timeout_sec
    assert seen[0].agent.override_timeout_sec == config.submission_timeout_sec
    assert seen[0].verifier.disable is True
    assert not seen[0].agent.resume_trajectory and not seen[0].agent.skills


@pytest.mark.parametrize("fault", [None, "stop", "creation", "connection"])
def test_generic_composer_preserves_human_instruction_on_setup_failure(
    tmp_path, monkeypatch, config_data, native_task_files, fault
):
    import os

    from harbor.environments.docker.docker import DockerEnvironment

    from workflow_bench.composer import submit_codex
    from workflow_bench.definition import export_public, load_task

    task, tools = native_task_files
    public = export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path / "run")
    command = tmp_path / "docker"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    class SetupFailed(Exception):
        pass

    async def start(self, **kwargs):
        if fault == "stop":
            (config.output_root / "submission-stop.json").write_text("{invalid")
        elif fault is not None:
            (config.output_root / (fault + ".json")).mkdir()
        raise SetupFailed()

    monkeypatch.setattr(DockerEnvironment, "start", start)
    with pytest.raises(SetupFailed):
        asyncio.run(
            submit_codex(
                public=public,
                root=config.output_root,
                run_id="run",
                attempt_id="attempt",
                previous=None,
                feedback=[],
                config=config,
                composer={
                    "mode": "model-free",
                    "image": config_data["app_image"],
                    "cli_version": "0.118.0",
                    "model": "synthetic",
                    "reasoning_effort": "low",
                    "exploration_max_calls": 4,
                },
            )
        )
    assert (config.output_root / "native-task/instruction.md").read_bytes() == (
        task / "instruction.md"
    ).read_bytes()


def test_measurement_requests_one_submission_and_never_retries_unknown(
    tmp_path, monkeypatch, config_data, native_task_files
):
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    task, tools = native_task_files
    toml = task / "task.toml"
    toml.write_text(
        toml.read_text().replace(
            "[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"'
        )
    )
    final = json.loads((task / "tests/cases.json").read_bytes())
    final["purpose"] = "final"
    for case in final["cases"]:
        case["id"] = "final-" + case["id"]
        case["input"]["item"] = "new-" + case["input"]["item"]
    (task / "tests/final.json").write_text(json.dumps(final))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    calls = []

    async def exported(config, **kwargs):
        return tools

    async def submit(**request):
        calls.append(request)
        assert {p.name for p in request["public"].root.iterdir()} == {
            "instruction.md",
            "task.json",
            "tools.json",
            "workflow.md",
            "workflow.schema.json",
            "composer.md",
        }
        assert request["previous"] is None and request["feedback"] == []
        return ControlledSubmission(
            None,
            "unknown",
            True,
            metrics={"input_tokens": None, "output_tokens": None, "model_calls": None},
        )

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported)
    report = asyncio.run(
        run_measurement(
            task,
            config=load_config(config_path, output=tmp_path / "run"),
            submit=submit,
        )
    )
    assert len(calls) == report["attempt_count"] == 1
    assert report["selection"]["blocked"] and report["score"] is None
    assert report["model_calls"] is None
    assert report["efficiency"]["creation"]["attempts"][0]["input_tokens"] is None


@pytest.mark.parametrize(
    "authorized,expected",
    [(False, "model_not_authorized"), (True, "provider_enforcement_unverified")],
)
def test_codex_preflight_never_trusts_declared_enforcement_or_opens_credentials(
    config_data, authorized, expected
):
    from tests.fast.test_measurement import budget_document

    from workflow_bench.composer import codex_preflight
    from workflow_bench.data import DataError

    budget = budget_document()
    budget["finalized"] = True
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


def test_api_billed_model_mode_is_closed_without_cli_budget_planning(
    config_data, monkeypatch
):
    import sys

    from workflow_bench.composer import codex_preflight
    from workflow_bench.data import DataError

    # The closed mode must be rejected by Composer alone, not by CLI budget planning.
    monkeypatch.setitem(sys.modules, "workflow_bench.cli", None)
    composer = {
        "mode": "model",
        "image": "sha256:" + "d" * 64,
        "cli_version": "0.118.0",
        "model": "gpt-6.1-sol",
        "reasoning_effort": "low",
        "exploration_max_calls": 40,
    }
    with pytest.raises(DataError, match="provider_enforcement_unverified"):
        codex_preflight(composer, budget=None, runtime=config_data, authorized=True)


def test_usage_reads_last_cumulative_event_preserving_missing_and_zero(tmp_path):
    from workflow_bench.composer import collect_codex_usage

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


def test_special_session_file_cannot_block_usage_collection(tmp_path):
    import os
    import subprocess
    import sys

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    os.mkfifo(sessions / "rollout.jsonl")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, sys; from pathlib import Path; "
            "from workflow_bench.composer import collect_codex_usage; "
            "print(json.dumps(collect_codex_usage(Path(sys.argv[1]))))",
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
    tmp_path, kind
):
    import os
    import subprocess
    import sys

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
            "from pathlib import Path; import sys; "
            "from harbor.agents.factory import AgentFactory; "
            "from harbor.models.trial.config import AgentConfig; "
            "from harbor.models.agent.context import AgentContext; "
            "p=Path(sys.argv[1]); "
            "a=AgentFactory.create_agent_from_config("
            "AgentConfig(import_path='workflow_bench.composer:SessionSafeCodex'), logs_dir=p); "
            "assert a.convert_trajectory(p) is None; "
            "context=AgentContext(); a.populate_context_post_run(context); "
            "assert context.n_input_tokens is None; assert context.model_usage == {}",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field", ["mode", "reasoning_effort"])
def test_invalid_composer_config_is_rejected_without_setup(config_data, field):
    from workflow_bench.composer import codex_preflight
    from workflow_bench.data import DataError

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


def test_cli_codex_gate_rejects_before_resources_and_ambient_auth(
    tmp_path, config_data
):
    import os
    import subprocess
    import sys

    from tests.fast.test_measurement import budget_document

    budget = budget_document()
    budget["finalized"] = True
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "runtime": config_data,
                "budget": budget,
                "composer": {
                    "mode": "model",
                    "image": "sha256:" + "d" * 64,
                    "cli_version": "0.118.0",
                    "model": "synthetic",
                    "reasoning_effort": "low",
                    "exploration_max_calls": 4,
                },
            }
        )
    )
    output = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "workflow_bench.cli",
            "--codex",
            "--config",
            str(config),
            "--output",
            str(output),
            "--task",
            str(tmp_path / "missing-task"),
        ],
        env={
            **os.environ,
            "CODEX_FORCE_AUTH_JSON": "true",
            "CODEX_AUTH_JSON_PATH": str(tmp_path / "must-not-read"),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert "model_not_authorized" in result.stderr
    assert not output.exists() and not result.stdout


@pytest.mark.parametrize("remaining_known", [None, "unknown"])
def test_unknown_remaining_creation_budget_blocks_second_attempt(
    tmp_path, monkeypatch, config_data, native_task_files, remaining_known
):
    from workflow_bench.experiment import ControlledSubmission, run_measurement

    task, tools = native_task_files
    toml = task / "task.toml"
    toml.write_text(
        toml.read_text().replace(
            "[metadata]", '[metadata]\nwb_final_cases = "tests/final.json"'
        )
    )
    final = json.loads((task / "tests/cases.json").read_bytes())
    final["purpose"] = "final"
    for case in final["cases"]:
        case["id"] = "final-" + case["id"]
        case["input"]["item"] = "new-" + case["input"]["item"]
    (task / "tests/final.json").write_text(json.dumps(final))
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    calls = []

    async def exported(config, **kwargs):
        return tools

    async def submit(**request):
        calls.append(request)
        return ControlledSubmission(
            None,
            metrics={
                "model_calls": None,
                "usd": None,
                "budget_remaining_known": remaining_known,
            },
        )

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported)
    report = asyncio.run(
        run_measurement(
            task,
            config=load_config(config_path, output=tmp_path / "run"),
            submit=submit,
        )
    )
    assert len(calls) == report["attempt_count"] == 1
    assert report["selection"]["blocked"]
    assert report["model_calls"] is None
