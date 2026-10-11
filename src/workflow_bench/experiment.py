"""One manual submission followed by fresh replays and native separate verification."""

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from harbor.models.trial.config import TrialConfig
from harbor.trial.hooks import TrialEvent, TrialHookEvent
from harbor.trial.trial import Trial

from workflow_bench.contracts import E1Config, JsonValue
from workflow_bench.data import read_json, validate_contract
from workflow_bench.definition import export_public, load_cases, load_task
from workflow_bench.execution import accept_artifact, replay
from workflow_bench.harbor import assert_stopped, replay_environment, tool_contract

LOGGER = logging.getLogger(__name__)


def _write(path: Path, document: JsonValue) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2))


async def run_manual(
    task_path: Path, case_ids: tuple[str, ...], *, config: E1Config
) -> dict[str, JsonValue]:
    started = time.monotonic()
    try:
        async with asyncio.timeout(config.total_timeout_sec):
            result = await _run_manual(task_path, case_ids, config=config)
        LOGGER.info(
            "phase=manual result=completed elapsed=%.2fs", time.monotonic() - started
        )
        return result
    except Exception as error:
        LOGGER.error("phase=manual result=failed error=%s", type(error).__name__)
        raise


async def _run_manual(
    task_path: Path, case_ids: tuple[str, ...], *, config: E1Config
) -> dict[str, JsonValue]:
    config.output_root.mkdir(mode=0o700)
    run_id, attempt_id = uuid4().hex, uuid4().hex
    contract = await tool_contract(config)
    materials = load_task(task_path, tool_contract=contract)
    cases = load_cases(materials, case_ids)
    rubric = read_json(materials.private_paths[1], "rubric")
    validate_contract("rubric", rubric)
    profile_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
    public = export_public(materials, config.output_root / "public")
    stage = config.output_root / "native-task"
    shutil.copytree(task_path, stage, ignore=shutil.ignore_patterns("__pycache__"))
    native = materials.native_task.config.model_copy(deep=True)
    native.environment.docker_image = config.app_image
    native.environment.cpus = config.cpus
    native.environment.memory_mb = config.memory_mb
    native.environment.build_timeout_sec = config.setup_timeout_sec
    native.agent.timeout_sec = config.submission_timeout_sec
    native.verifier.timeout_sec = config.verifier_timeout_sec
    (stage / "task.toml").write_text(native.model_dump_toml())
    inputs = stage / "tests/bench-input"
    inputs.mkdir()
    _write(inputs / "index.json", list(case_ids))
    _write(inputs / "rubric.json", rubric)
    _write(
        config.output_root / "manifest.json",
        {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "source": "manual",
            "harbor_version": version("harbor"),
            "aiohttp_version": version("aiohttp"),
            "config": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in asdict(config).items()
            },
            "materials": dict(materials.hashes),
            "public_files": dict(public.files),
            "profile_hash": profile_hash,
            "case_ids": list(case_ids),
            "model_calls": 0,
            "model_calls_source": "manual_control",
        },
    )
    trial_name = "wb04-manual-" + attempt_id
    trial_config = TrialConfig.model_validate(
        {
            "task": {"path": str(stage)},
            "trial_name": trial_name,
            "trials_dir": str(config.output_root / "harbor"),
            "agent": {
                "name": "oracle",
                "override_timeout_sec": config.submission_timeout_sec,
            },
            "verifier": {"override_timeout_sec": config.verifier_timeout_sec},
            "environment": {
                "delete": True,
                "override_cpus": config.cpus,
                "override_memory_mb": config.memory_mb,
            },
        }
    )
    trial = await Trial.create(trial_config)
    replays: list[dict[str, JsonValue]] = []
    artifact_hash = None

    async def check_submission(event: TrialHookEvent) -> None:
        checked = await trial.agent_environment.exec(
            'set -eu; test ! -e /tests; test ! -e /solution; test ! -e /bench/input; test ! -e /var/run/docker.sock; test ! -e /app/workflow_bench/experiment.py; test -z "${WB_CONTROL_KEY:-}"',
            timeout_sec=int(config.control_timeout_sec),
        )
        if checked.return_code:
            raise RuntimeError("submission_isolation_failed")
        LOGGER.info("phase=isolation submission=%s result=confirmed", event.trial_name)

    async def prepared(event: TrialHookEvent) -> None:
        nonlocal artifact_hash
        LOGGER.info("phase=submission result=collected")
        await assert_stopped(event.trial_name + "__env", deleted=True)
        manifest = read_json(trial.paths.artifacts_dir / "manifest.json", "collection")
        if not any(
            item["source"] == "/work/workflow.json"
            and item["status"] == "ok"
            and item["type"] == "file"
            for item in manifest
        ):
            raise RuntimeError("artifact_collection_failed")
        artifact = accept_artifact(
            trial.paths.artifacts_dir / "work/workflow.json",
            submission_stopped=True,
            destination=config.output_root / "accepted.json",
        )
        artifact_hash = artifact.sha256
        for case in cases:
            identity = {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "replay_id": uuid4().hex,
                "artifact_hash": artifact.sha256,
                "case_id": case.id,
                "profile_hash": profile_hash,
                "profile": materials.tool_contract["profile"],
            }
            case_root = inputs / case.id
            case_root.mkdir()
            _write(
                case_root / "case.json",
                {
                    "id": case.id,
                    "input": case.input,
                    "expected": case.expected,
                    "identity": identity,
                },
            )
            async with replay_environment(config, identity) as context:
                await context.control(
                    "reset",
                    {
                        "identity": identity,
                        "state": case.state,
                        "profile": identity["profile"],
                        "limits": {"call_timeout_sec": config.tool_timeout_sec},
                    },
                )
                for service in ("n8n", "runner"):
                    boundary = await context.environment.service_exec(
                        'set -eu; test ! -e /tests; test ! -e /solution; test ! -e /bench/input; test ! -e /var/run/docker.sock; test ! -e /app/workflow_bench/experiment.py; test -z "${WB_CONTROL_KEY:-}"',
                        service=service,
                        timeout_sec=int(config.control_timeout_sec),
                    )
                    if boundary.return_code:
                        raise RuntimeError("isolation_failed")
                fresh = await context.environment.service_exec(
                    "test ! -e /home/node/.n8n/database.sqlite",
                    service="n8n",
                    timeout_sec=int(config.control_timeout_sec),
                )
                if fresh.return_code:
                    raise RuntimeError("replay_database_not_fresh")
                await context.check_isolation()
                execution, bound = await replay(
                    artifact, case.input, context=context, config=config
                )
                evidence = await context.control("export")
                _write(case_root / "evidence.json", evidence)
                _write(case_root / "execution.json", execution)
                replays.append(
                    {
                        "identity": identity,
                        "execution": execution,
                        "bound_hash": bound.bound_hash,
                        "isolation_confirmed": True,
                        "database_fresh": True,
                        "replacements": list(bound.replacements),
                        "evidence_ref": str(
                            (case_root / "evidence.json").relative_to(
                                config.output_root
                            )
                        ),
                        "log_ref": str(
                            context.root.relative_to(config.output_root)
                            / "harbor/agent"
                        ),
                    }
                )
        LOGGER.info("phase=verification inputs=protected result=ready")

    trial.add_hook(TrialEvent.AGENT_START, check_submission)
    trial.add_hook(TrialEvent.VERIFICATION_START, prepared)
    LOGGER.info("phase=submission run_id=%s log=%s", run_id, trial.paths.trial_dir)
    native_result = await trial.run()
    await assert_stopped(trial_name + "__env", deleted=True)
    await assert_stopped(trial_name + "__verifier__trial", deleted=True)
    path = trial.paths.verifier_dir / "evaluation.json"
    evaluation = (
        read_json(path, "evaluation")
        if path.exists()
        else {"schema_version": "1.0", "cases": []}
    )
    for result in evaluation["cases"]:
        validate_contract("evaluation", result)
    report = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "artifact_hash": artifact_hash,
        "replays": replays,
        "evaluation": evaluation,
        "harbor_exception": native_result.exception_info.exception_type
        if native_result.exception_info
        else None,
        "harbor_result_ref": str(
            trial.paths.result_path.relative_to(config.output_root)
        ),
        "cleanup_errors": [],
        "residual_resources": [],
    }
    _write(config.output_root / "report.json", report)
    LOGGER.info(
        "phase=verification result=%s report=%s",
        "completed" if evaluation["cases"] else "unavailable",
        config.output_root / "report.json",
    )
    return report
