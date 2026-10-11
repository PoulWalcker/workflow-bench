"""One manual submission followed by fresh replays and native separate verification."""

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import asdict, replace
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from workflow_bench.contracts import E1Config, JsonValue
from workflow_bench.data import read_json, validate_contract
from workflow_bench.definition import export_public, load_cases, load_task
from workflow_bench.execution import accept_artifact, replay
from workflow_bench.harbor import replay_environment, run_native_trial, tool_contract

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
    except Exception:
        LOGGER.error(
            "phase=manual result=failed elapsed=%.2fs", time.monotonic() - started
        )
        raise


async def _run_manual(
    task_path: Path, case_ids: tuple[str, ...], *, config: E1Config
) -> dict[str, JsonValue]:
    config.output_root.mkdir(mode=0o700)
    run_id, attempt_id = uuid4().hex, uuid4().hex
    contract = await tool_contract(config)
    materials = load_task(task_path, tool_contract=contract)
    stage = config.output_root / "native-task"
    shutil.copytree(
        task_path, stage, symlinks=True, ignore=shutil.ignore_patterns("__pycache__")
    )
    materials = replace(
        materials,
        private_paths=tuple(
            stage / path.relative_to(task_path) for path in materials.private_paths
        ),
    )
    cases = load_cases(materials, case_ids)
    rubric = read_json(materials.private_paths[1], "rubric")
    validate_contract("rubric", rubric)
    profile_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
    public = export_public(materials, config.output_root / "public")
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
            "rubric_snapshot": {
                "ref": str((inputs / "rubric.json").relative_to(config.output_root)),
                "sha256": hashlib.sha256(
                    (inputs / "rubric.json").read_bytes()
                ).hexdigest(),
            },
            "case_snapshot": {
                "ref": str(materials.private_paths[0].relative_to(config.output_root)),
                "sha256": hashlib.sha256(
                    materials.private_paths[0].read_bytes()
                ).hexdigest(),
                "schema_version": "1.0",
            },
            "model_calls": 0,
            "model_calls_source": "manual_control",
        },
    )
    replays: list[dict[str, JsonValue]] = []
    artifact_hash = None

    async def prepared(collected_file: Path) -> None:
        nonlocal artifact_hash
        artifact = accept_artifact(
            collected_file,
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

    native_result = await run_native_trial(stage, attempt_id, prepared, config=config)
    evaluation = native_result.evaluation
    report = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "artifact_hash": artifact_hash,
        "replays": replays,
        "evaluation": evaluation,
        "harbor_exception": native_result.exception_type,
        "harbor_result_ref": native_result.result_ref,
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
