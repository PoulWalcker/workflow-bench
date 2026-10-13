"""Readiness of a Task directory: authoring structure and oracle/no-op controls."""

import logging
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from harbor.models.task.config import TaskConfig, VerifierEnvironmentMode
from harbor.models.task.task import Task
from harbor.models.task.verifier_mode import resolve_task_verifier_mode

from workflow_bench.contracts import Evaluation
from workflow_bench.data import DataError, read_json, validate_contract

LOGGER = logging.getLogger(__name__)

MANDATORY_FILES = (
    "instruction.md",
    "task.toml",
    "environment/Dockerfile",
    "solution/solve.sh",
    "tests/test.sh",
)
TOP_LEVEL_ENTRIES = frozenset(
    {"instruction.md", "task.toml", "environment", "solution", "tests"}
)
LEVELS = ("L1", "L2", "L3a", "L3b")
HORIZONS = ("single", "repeated")
# Each control agent and the verdict a ready task must give it.
CONTROLS = (("oracle", "pass"), ("nop", "fail"))
ENVIRONMENT_IMPORT_PATH = "workflow_bench.harbor:DeadlineDockerEnvironment"
PROGRESS_INTERVAL_SEC = 30.0


@dataclass(frozen=True)
class ControlRun:
    """One native `harbor run` of a control agent.

    Attributes:
        job: Harbor job name under the jobs directory.
        result: The evaluation verdict, or ``missing``, ``invalid_evaluation``,
            ``timeout`` or ``harbor_exit_<code>`` when no verdict was produced.
    """

    agent: str
    job: str
    result: str


@dataclass(frozen=True)
class ReadinessReport:
    """Readiness of one task; it is ready only when no reason was found."""

    task: str
    reasons: list[str] = field(default_factory=list)
    runs: list[ControlRun] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        return not self.reasons


def check_task(
    task_dir: Path,
    *,
    jobs_dir: Path,
    run_timeout_sec: float,
    cleanup_timeout_sec: float,
) -> ReadinessReport:
    """Check the authoring structure, then run the oracle and no-op controls.

    Controls run only for a structurally valid task: the oracle must produce a
    ``pass`` evaluation and the no-op agent a ``fail`` (not ``unknown``).
    """
    reasons = structure_reasons(task_dir)
    if reasons:
        return ReadinessReport(task_dir.name, reasons)
    runs = [
        _run_control(
            task_dir,
            agent,
            jobs_dir=jobs_dir,
            run_timeout_sec=run_timeout_sec,
            cleanup_timeout_sec=cleanup_timeout_sec,
        )
        for agent, _ in CONTROLS
    ]
    reasons = [
        f"{run.agent}_not_{expected}:{run.result}"
        for run, (_, expected) in zip(runs, CONTROLS, strict=True)
        if run.result != expected
    ]
    return ReadinessReport(task_dir.name, reasons, runs)


def structure_reasons(task_dir: Path) -> list[str]:
    """Return named violations of the task authoring structure, if any."""
    if not task_dir.is_dir():
        return ["missing:task_dir"]
    reasons = [
        f"unexpected:{entry.name}"
        for entry in sorted(task_dir.iterdir())
        if entry.name not in TOP_LEVEL_ENTRIES
    ]
    reasons += [
        f"missing:{name}" for name in MANDATORY_FILES if not (task_dir / name).is_file()
    ]
    if reasons:
        return reasons
    try:
        config = Task(task_dir).config
    except (OSError, ValueError):
        return ["invalid:task.toml"]
    return _config_reasons(config)


def _config_reasons(config: TaskConfig) -> list[str]:
    reasons = []
    if config.metadata.get("level") not in LEVELS:
        reasons.append("invalid:metadata.level")
    if config.metadata.get("horizon") not in HORIZONS:
        reasons.append("invalid:metadata.horizon")
    if config.agent.timeout_sec is None:
        reasons.append("missing:agent.timeout_sec")
    if resolve_task_verifier_mode(config) != VerifierEnvironmentMode.SEPARATE:
        reasons.append("invalid:verifier.environment_mode")
    return reasons


def _run_control(
    task_dir: Path,
    agent: str,
    *,
    jobs_dir: Path,
    run_timeout_sec: float,
    cleanup_timeout_sec: float,
) -> ControlRun:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    job = f"check-{task_dir.name}-{agent}-{stamp}"
    command = [
        sys.executable,
        "-m",
        "harbor.cli.main",
        "run",
        "--path",
        str(task_dir),
        "--agent",
        agent,
        "--env",
        ENVIRONMENT_IMPORT_PATH,
        "--ek",
        f"cleanup_timeout_sec={cleanup_timeout_sec}",
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        job,
        "--n-concurrent",
        "1",
        "--n-attempts",
        "1",
        "--quiet",
        "--yes",
    ]
    LOGGER.info("phase=readiness agent=%s job=%s status=started", agent, job)
    started = time.monotonic()
    exit_code = _run_bounded(
        command,
        agent=agent,
        run_timeout_sec=run_timeout_sec,
        cleanup_timeout_sec=cleanup_timeout_sec,
    )
    if exit_code is None:
        result = "timeout"
    elif exit_code:
        result = f"harbor_exit_{exit_code}"
    else:
        result = _read_verdict(jobs_dir / job)
    LOGGER.info(
        "phase=readiness agent=%s job=%s status=finished result=%s duration_sec=%.1f",
        agent,
        job,
        result,
        time.monotonic() - started,
    )
    return ControlRun(agent, job, result)


def _run_bounded(
    command: list[str],
    *,
    agent: str,
    run_timeout_sec: float,
    cleanup_timeout_sec: float,
) -> int | None:
    """Run Harbor with a deadline; return its exit code, or None on timeout.

    Harbor's console output goes to stderr so stdout keeps only command
    results. On the deadline Harbor is interrupted first, so its own cleanup
    can stop the Trial's containers before the process is killed.
    """
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=2, stderr=2)
    started = time.monotonic()
    try:
        while (remaining := run_timeout_sec - (time.monotonic() - started)) > 0:
            try:
                return process.wait(timeout=min(PROGRESS_INTERVAL_SEC, remaining))
            except subprocess.TimeoutExpired:
                LOGGER.info(
                    "phase=readiness agent=%s status=running elapsed_sec=%.0f",
                    agent,
                    time.monotonic() - started,
                )
        LOGGER.error("phase=readiness agent=%s status=timeout", agent)
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=cleanup_timeout_sec)
        except subprocess.TimeoutExpired:
            LOGGER.warning("phase=readiness agent=%s cleanup=unconfirmed", agent)
        return None
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def _read_verdict(job_dir: Path) -> str:
    paths = sorted(job_dir.glob("*/verifier/evaluation.json"))
    if len(paths) != 1:
        return "missing"
    try:
        document = read_json(paths[0], "evaluation")
        validate_contract("evaluation", document)
    except (DataError, OSError):
        return "invalid_evaluation"
    return cast(Evaluation, document)["verdict"]
