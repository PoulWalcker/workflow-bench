"""Controlled submissions, fresh native replays and independent verification."""

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass, replace
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from workflow_bench.contracts import E1Config, JsonValue, WorkflowArtifact
from workflow_bench.data import DataError, read_json, validate_contract
from workflow_bench.definition import export_public, load_cases, load_task
from workflow_bench.execution import ArtifactError, accept_artifact, replay
from workflow_bench.harbor import (
    LifecycleFacts,
    replay_environment,
    run_native_trial,
    tool_contract,
)

LOGGER = logging.getLogger(__name__)


def _write(path: Path, document: JsonValue) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2))


async def run_manual(
    task_path: Path,
    case_ids: tuple[str, ...] | None,
    *,
    config: E1Config,
    purpose: str | None = None,
    submission: WorkflowArtifact | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    cancel: asyncio.Event | None = None,
) -> dict[str, JsonValue]:
    started = time.monotonic()
    lifecycle = LifecycleFacts()
    config.output_root.mkdir(mode=0o700)
    task = asyncio.current_task()

    async def cancelled():
        await cancel.wait()
        task.cancel()

    watcher = asyncio.create_task(cancelled()) if cancel is not None else None
    try:
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError()

        async with asyncio.timeout(config.total_timeout_sec):
            result = await _run_manual(
                task_path,
                case_ids,
                config=config,
                lifecycle=lifecycle,
                purpose=purpose,
                submission=submission,
                run_id=run_id,
                attempt_id=attempt_id,
            )
        LOGGER.info(
            "phase=manual result=completed elapsed=%.2fs", time.monotonic() - started
        )
        return result
    except (Exception, asyncio.CancelledError) as error:
        if config.output_root.is_dir():
            report = {
                "evaluation": {"schema_version": "1.0", "cases": []},
                "completeness": "invalid"
                if isinstance(error, DataError) and error.relative_path == "evaluation"
                else "unavailable",
                "score": None,
                "error": "cancelled"
                if isinstance(error, asyncio.CancelledError)
                else (
                    error.code if isinstance(error, DataError) else type(error).__name__
                ),
                "execution_refs": [
                    str(p.relative_to(config.output_root))
                    for p in config.output_root.glob("wb04-replay-*/execution.json")
                ],
                "cleanup_errors": lifecycle.cleanup_errors,
                "residual_resources": lifecycle.residual_resources,
            }
            _write(config.output_root / "report.json", report)
        LOGGER.error(
            "phase=manual result=failed elapsed=%.2fs", time.monotonic() - started
        )
        if (
            isinstance(error, asyncio.CancelledError)
            and cancel is not None
            and cancel.is_set()
        ):
            return report
        raise
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


async def _run_manual(
    task_path: Path,
    case_ids: tuple[str, ...] | None,
    *,
    config: E1Config,
    purpose: str | None = None,
    submission: WorkflowArtifact | None = None,
    run_id: str | None = None,
    attempt_id: str | None = None,
    lifecycle: LifecycleFacts,
) -> dict[str, JsonValue]:
    run_id, attempt_id = run_id or uuid4().hex, attempt_id or uuid4().hex
    contract = await tool_contract(config, lifecycle=lifecycle)
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
    if submission is not None:
        destination = stage / "solution/workflow.json"
        if any(path.is_symlink() for path in (destination, *destination.parents)):
            raise DataError("unsafe_path", "solution/workflow.json")
        shutil.copyfile(submission.path, destination)
    cases = load_cases(materials, case_ids, purpose=purpose or "development")
    case_ids = tuple(case.id for case in cases)
    rubric = read_json(materials.private_paths[1], "rubric")
    validate_contract("rubric", rubric)
    profile_hash = hashlib.sha256(contract.read_bytes()).hexdigest()
    public = export_public(materials, config.output_root / "public")
    inputs = stage / "tests/bench-input"
    inputs.mkdir()
    _write(inputs / "index.json", list(case_ids))
    if purpose is not None:
        _write(inputs / "purpose.json", purpose)
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
            "purpose": purpose or "technical",
            "rubric_snapshot": {
                "ref": str((inputs / "rubric.json").relative_to(config.output_root)),
                "sha256": hashlib.sha256(
                    (inputs / "rubric.json").read_bytes()
                ).hexdigest(),
            },
            "case_snapshot": {
                "ref": str(
                    materials.private_paths[2 if purpose == "final" else 0].relative_to(
                        config.output_root
                    )
                ),
                "sha256": hashlib.sha256(
                    materials.private_paths[2 if purpose == "final" else 0].read_bytes()
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
        if submission is not None and artifact.sha256 != submission.sha256:
            raise ArtifactError("artifact_hash_mismatch")
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
            setup_started = time.monotonic()
            async with replay_environment(
                config, identity, lifecycle=lifecycle
            ) as context:
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
                setup_ms = (time.monotonic() - setup_started) * 1000
                replay_started = time.monotonic()
                try:
                    execution, bound = await replay(
                        artifact, case.input, context=context, config=config
                    )
                finally:
                    evidence = await context.control("export")
                    _write(case_root / "evidence.json", evidence)
                _write(case_root / "execution.json", execution)
                replays.append(
                    {
                        "identity": identity,
                        "metrics": {
                            "setup_ms": setup_ms,
                            "replay_ms": (time.monotonic() - replay_started) * 1000,
                            "tool_calls": sum(
                                e["stage"] == "accepted" for e in evidence["events"]
                            ),
                            "source": "host_monotonic_and_frozen_events",
                            "model_calls": 0,
                            "input_tokens": None,
                            "output_tokens": None,
                            "usd": None,
                        },
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

    native_result = await run_native_trial(
        stage, attempt_id, prepared, config=config, lifecycle=lifecycle
    )
    evaluation = native_result.evaluation
    if not evaluation["cases"]:
        completeness = "unavailable"
    elif any(c["completeness"] == "invalid" for c in evaluation["cases"]):
        completeness = "invalid"
    elif (
        lifecycle.cleanup_errors
        or lifecycle.residual_resources
        or (purpose != "development" and native_result.reward_status != "complete")
        or any(c["completeness"] != "complete" for c in evaluation["cases"])
    ):
        completeness = "partial"
    else:
        completeness = "complete"
    aggregate = evaluation.get("aggregate")
    report = {
        "score": aggregate["score"] if aggregate else None,
        "verdict": aggregate["verdict"] if aggregate else "unknown",
        "business_completeness": aggregate["completeness"]
        if aggregate
        else completeness,
        "reward_required": purpose == "final",
        "efficiency": {
            "native_phase_timings_ref": native_result.result_ref,
            "replay_metrics": [r["metrics"] for r in replays],
            "model_calls": 0,
            "judge_calls": 0,
            "source": "manual_control",
            "usd": None,
        },
        "run_id": run_id,
        "attempt_id": attempt_id,
        "artifact_hash": artifact_hash,
        "replays": replays,
        "evaluation": evaluation,
        "harbor_exception": native_result.exception_type,
        "harbor_result_ref": native_result.result_ref,
        "reward_status": native_result.reward_status,
        "cleanup_errors": lifecycle.cleanup_errors,
        "residual_resources": lifecycle.residual_resources,
        "completeness": completeness,
    }
    _write(config.output_root / "report.json", report)
    LOGGER.info(
        "phase=verification result=%s report=%s",
        "completed" if evaluation["cases"] else "unavailable",
        config.output_root / "report.json",
    )
    return report


@dataclass(frozen=True)
class Attempt:
    """A controlled, stopped submission and its development result."""

    attempt_id: str
    artifact: WorkflowArtifact | None
    development: dict[str, JsonValue] | None
    process_status: str
    stop_confirmed: bool
    submission_code: str | None = None


def select_attempts(
    attempts: tuple[Attempt, ...], *, feedback_rules: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Apply T1's bounded choice, without consulting final results."""
    if not 1 <= len(attempts) <= 2:
        raise DataError("attempt_limit", "attempts")
    selected = None
    reason = "no_valid_submission"
    blocked = False
    for attempt in attempts:
        if attempt.development is not None:
            validate_contract("aggregate", attempt.development)
            if (
                attempt.development["purpose"] != "development"
                or attempt.artifact is None
                or any(
                    result["identity"]["artifact_hash"] != attempt.artifact.sha256
                    or result["identity"]["attempt_id"] != attempt.attempt_id
                    for result in attempt.development["cases"]
                )
            ):
                raise DataError("identity_mismatch", "attempts")
        if attempt.artifact is not None:
            selected = attempt
            reason = "last_valid"
        if (
            not attempt.stop_confirmed
            or attempt.process_status == "unknown"
            or (
                attempt.artifact is not None
                and (
                    attempt.development is None
                    or attempt.development["completeness"] != "complete"
                )
            )
        ):
            blocked = True
            break
        if attempt.development is not None and attempt.development["verdict"] == "pass":
            selected = attempt
            reason = "first_development_pass"
            break
    feedback = []
    last = attempts[-1]
    if not blocked and last.development is not None:
        allowed_ids = set(feedback_rules["criterion_ids"])
        allowed_codes = set(feedback_rules.get("reason_codes", []))
        for case in last.development["cases"]:
            for criterion in case["criteria"]:
                if criterion["criterion_id"] in allowed_ids:
                    code = criterion["reason_code"]
                    feedback.append(
                        {
                            "criterion_id": criterion["criterion_id"],
                            "status": criterion["status"],
                            "reason_code": code
                            if code in allowed_codes
                            else criterion["status"],
                        }
                    )
    elif not blocked and last.artifact is None:
        feedback = [
            {
                "submission": last.submission_code
                if last.submission_code in feedback_rules.get("reason_codes", [])
                else "invalid_or_missing"
            }
        ]
    return {
        "selected_attempt_id": selected.attempt_id if selected else None,
        "artifact_hash": selected.artifact.sha256 if selected else None,
        "reason": reason,
        "blocked": blocked,
        "continue": not blocked
        and reason != "first_development_pass"
        and len(attempts) < 2,
        "feedback": feedback,
    }


@dataclass(frozen=True)
class ControlledSubmission:
    path: Path | None
    process_status: str = "completed"
    stop_confirmed: bool = True


async def _run_measurement(
    task_path: Path,
    submissions: tuple[ControlledSubmission, ...],
    *,
    config: E1Config,
) -> dict[str, JsonValue]:
    """Exercise the two-attempt policy with controlled files, never a model."""
    run_id = uuid4().hex
    attempts = []
    reports = []
    snapshot = config.output_root / "task-snapshot"
    contract = await tool_contract(config)
    materials = load_task(task_path, tool_contract=contract)
    shutil.copytree(
        task_path, snapshot, symlinks=True, ignore=shutil.ignore_patterns("__pycache__")
    )
    materials = load_task(snapshot, tool_contract=contract)
    development = load_cases(materials, purpose="development")
    final = load_cases(materials, purpose="final")
    rubric = read_json(materials.private_paths[1], "rubric")
    validate_contract("rubric", rubric)
    policy = rubric["scoring_policy"]
    if (
        policy is None
        or len(development) != policy["case_count"]
        or len(final) != policy["case_count"]
    ):
        raise DataError("invalid_measurement_sets", "cases")
    _write(
        config.output_root / "manifest.json",
        {
            "run_id": run_id,
            "source": "controlled",
            "max_attempts": 2,
            "model_calls": 0,
            "model_calls_source": "controlled_submissions",
            "sets": {
                purpose: {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "ref": str(path.relative_to(config.output_root)),
                }
                for purpose, path in [
                    ("development", materials.private_paths[0]),
                    ("final", materials.private_paths[2]),
                ]
            },
            "rubric": {
                "ref": str(materials.private_paths[1].relative_to(config.output_root)),
                "sha256": hashlib.sha256(
                    materials.private_paths[1].read_bytes()
                ).hexdigest(),
            },
        },
    )
    for index, submission in enumerate(submissions, 1):
        attempt_id = uuid4().hex
        root = config.output_root / f"attempt-{index}"
        root.mkdir(mode=0o700)
        artifact = None
        artifact_status = "missing" if submission.path is None else "invalid"
        submission_code = (
            "missing" if submission.path is None else "unconfirmed_submission"
        )
        if (
            submission.path is not None
            and submission.stop_confirmed
            and submission.process_status != "unknown"
        ):
            try:
                artifact = accept_artifact(
                    submission.path,
                    submission_stopped=True,
                    destination=root / "accepted.json",
                )
                artifact_status, submission_code = "valid", None
            except ArtifactError as error:
                artifact_status = "missing" if error.code == "missing" else "invalid"
                submission_code = error.code
        _write(
            root / "submission.json",
            {
                "artifact_status": artifact_status,
                "process_status": submission.process_status,
                "stop_confirmed": submission.stop_confirmed,
                "error_code": submission_code,
            },
        )
        reports.append(
            {
                "attempt_id": attempt_id,
                "artifact_status": artifact_status,
                "submission_ref": f"attempt-{index}/submission.json",
                "error_code": submission_code,
                "artifact_hash": artifact.sha256 if artifact else None,
                "process_status": submission.process_status,
                "stop_confirmed": submission.stop_confirmed,
                "report_ref": None,
            }
        )
        development_result = None
        if artifact is not None:
            report = await run_manual(
                snapshot,
                None,
                config=replace(config, output_root=root / "development"),
                purpose="development",
                submission=artifact,
                run_id=run_id,
                attempt_id=attempt_id,
            )
            reports[-1]["report_ref"] = f"attempt-{index}/development/report.json"
            development_result = report["evaluation"].get("aggregate")
        attempts.append(
            Attempt(
                attempt_id,
                artifact,
                development_result,
                submission.process_status,
                submission.stop_confirmed,
                submission_code,
            )
        )
        selection = select_attempts(
            tuple(attempts), feedback_rules=materials.public_data["feedback"]
        )
        _write(root / "feedback.json", selection["feedback"])
        if not selection["continue"]:
            break
    selected = next(
        (a for a in attempts if a.attempt_id == selection["selected_attempt_id"]), None
    )
    selection["artifact_ref"] = (
        str(selected.artifact.path.relative_to(config.output_root))
        if selected
        else None
    )
    _write(config.output_root / "selection.json", selection)
    final_report = None
    if selection["selected_attempt_id"] is not None and not selection["blocked"]:
        final_report = await run_manual(
            snapshot,
            None,
            config=replace(config, output_root=config.output_root / "final"),
            purpose="final",
            submission=selected.artifact,
            run_id=run_id,
            attempt_id=selected.attempt_id,
        )
    report = {
        "selection": selection,
        "attempts": reports,
        "attempt_count": len(attempts),
        "final_report_ref": "final/report.json" if final_report else None,
        "score": final_report["score"] if final_report else None,
        "verdict": final_report["verdict"] if final_report else "unknown",
        "completeness": final_report["completeness"] if final_report else "unavailable",
        "model_calls": 0,
        "judge_calls": 0,
        "efficiency": {
            "creation": {
                "source": "controlled_files",
                "model_calls": 0,
                "input_tokens": None,
                "output_tokens": None,
                "usd": None,
            },
            "development_refs": [r["report_ref"] for r in reports if r["report_ref"]],
            "final_ref": "final/report.json" if final_report else None,
        },
    }
    _write(config.output_root / "report.json", report)
    return report


async def run_measurement(
    task_path: Path,
    submissions: tuple[ControlledSubmission, ...],
    *,
    config: E1Config,
    cancel: asyncio.Event | None = None,
) -> dict[str, JsonValue]:
    """Bound the entire controlled run, preserving an interrupted measurement."""
    if not 1 <= len(submissions) <= 2:
        raise DataError("attempt_limit", "attempts")
    config.output_root.mkdir(mode=0o700)
    task = asyncio.current_task()

    async def cancelled():
        await cancel.wait()
        task.cancel()

    watcher = asyncio.create_task(cancelled()) if cancel is not None else None
    try:
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError()
        async with asyncio.timeout(config.total_timeout_sec):
            return await _run_measurement(task_path, submissions, config=config)
    except (Exception, asyncio.CancelledError) as error:
        if config.output_root.is_dir():
            selection_path = config.output_root / "selection.json"
            _write(
                config.output_root / "report.json",
                {
                    "score": None,
                    "verdict": "unknown",
                    "completeness": "unavailable",
                    "error": "cancelled"
                    if isinstance(error, asyncio.CancelledError)
                    else error.code
                    if isinstance(error, DataError)
                    else type(error).__name__,
                    "selection_ref": "selection.json"
                    if selection_path.exists()
                    else None,
                    "phase_report_refs": [
                        str(p.relative_to(config.output_root))
                        for p in config.output_root.glob("*/**/report.json")
                    ],
                },
            )
        raise
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
