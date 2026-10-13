"""Readiness of a Task directory: structure, helper image and oracle/no-op controls."""

import json
import logging
import math
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from harbor.models.task.config import TaskConfig, VerifierEnvironmentMode
from harbor.models.task.task import Task
from harbor.models.task.verifier_mode import resolve_task_verifier_mode

from workflow_bench.comparison import read_evaluation
from workflow_bench.data import DataError

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
HELPER_PROBE_TIMEOUT_SEC = 60.0
# Run by the host's and the base image's Python: a digest of every file of the
# installed `workflow_bench` package.
HELPER_DIGEST_SCRIPT = """
import hashlib, json, pathlib, workflow_bench
root = pathlib.Path(workflow_bench.__file__).parent
print(json.dumps({
    path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in root.rglob("*")
    if path.is_file() and "__pycache__" not in path.parts
}))
"""


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
    """Check the structure and helper image, then run the oracle and no-op controls.

    Controls run only for a structurally valid task whose base image carries
    this package's evaluation helper: the oracle must produce a ``pass``
    evaluation and the no-op agent a ``fail`` (not ``unknown``).
    """
    reasons = structure_reasons(task_dir) or helper_reasons(task_dir)
    if reasons:
        return ReadinessReport(task_dir.name, reasons)
    runner = _ControlRunner(task_dir, jobs_dir, run_timeout_sec, cleanup_timeout_sec)
    runs = [runner.run(agent) for agent, _ in CONTROLS]
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


def helper_reasons(task_dir: Path) -> list[str]:
    """Return why the task's base image may not carry this package's helper.

    Separate verifiers import the evaluation helper from the image, so a stale
    copy would silently apply outdated evaluation logic. The base image is the
    last ``FROM`` of ``environment/Dockerfile``; it is inspected locally, never
    pulled. ``stale:agents_helper`` means an installed helper file differs from
    this package; ``unverified:agents_helper`` means the image could not be
    inspected.
    """
    image = _base_image(task_dir)
    image_python = [
        "docker",
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--entrypoint",
        "python",
        image,
    ]
    try:
        image_digests = _package_digests(image_python)
        host_digests = _package_digests([sys.executable])
    except (OSError, subprocess.SubprocessError, ValueError):
        LOGGER.error(
            "phase=helper_check task=%s image=%s status=unverified",
            task_dir.name,
            image,
        )
        return ["unverified:agents_helper"]
    if not image_digests.items() <= host_digests.items():
        LOGGER.error(
            "phase=helper_check task=%s image=%s status=stale", task_dir.name, image
        )
        return ["stale:agents_helper"]
    LOGGER.info(
        "phase=helper_check task=%s image=%s status=current", task_dir.name, image
    )
    return []


def _config_reasons(config: TaskConfig) -> list[str]:
    reasons: list[str] = []
    if config.metadata.get("level") not in LEVELS:
        reasons.append("invalid:metadata.level")
    if config.metadata.get("horizon") not in HORIZONS:
        reasons.append("invalid:metadata.horizon")
    if config.agent.timeout_sec is None:
        reasons.append("missing:agent.timeout_sec")
    elif not math.isfinite(config.agent.timeout_sec):
        reasons.append("invalid:agent.timeout_sec")
    if resolve_task_verifier_mode(config) != VerifierEnvironmentMode.SEPARATE:
        reasons.append("invalid:verifier.environment_mode")
    return reasons


def _base_image(task_dir: Path) -> str:
    """Return the image of the final ``FROM`` in the task's Dockerfile, or ``""``."""
    image = ""
    for line in (task_dir / "environment" / "Dockerfile").read_text().splitlines():
        words = line.split()
        if words and words[0].upper() == "FROM":
            image = next((word for word in words[1:] if not word.startswith("--")), "")
    return image


def _package_digests(python_command: list[str]) -> dict[str, str]:
    """Return file digests of the package as installed for the given Python.

    Raises:
        OSError, subprocess.SubprocessError: The interpreter did not run.
        ValueError: Its output is not a mapping of paths to digests.
    """
    completed = subprocess.run(
        [*python_command, "-c", HELPER_DIGEST_SCRIPT],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=HELPER_PROBE_TIMEOUT_SEC,
    )
    digests = json.loads(completed.stdout)
    if not isinstance(digests, dict) or not all(
        isinstance(value, str) for value in digests.values()
    ):
        raise ValueError("unexpected package digests")
    return digests


def _read_verdict(job_dir: Path) -> str:
    paths = sorted(job_dir.glob("*/verifier/evaluation.json"))
    if len(paths) != 1:
        return "missing"
    try:
        return read_evaluation(paths[0])["verdict"]
    except (DataError, OSError):
        return "invalid_evaluation"


@dataclass(frozen=True)
class _ControlRunner:
    """Runs one task's control agents as bounded native `harbor run` jobs.

    Attributes:
        run_timeout_sec: Deadline of each control's Harbor process.
        cleanup_timeout_sec: Grace Harbor gets after an interrupt to stop the
            Trial's containers before it is killed; also passed to
            ``DeadlineDockerEnvironment``.
    """

    task_dir: Path
    jobs_dir: Path
    run_timeout_sec: float
    cleanup_timeout_sec: float

    def run(self, agent: str) -> ControlRun:
        """Run one control agent and read the verdict of its Trial.

        Raises:
            KeyboardInterrupt: The operator interrupted the run; Harbor was
                given the cleanup grace before the interrupt propagates.
        """
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        job = f"check-{self.task_dir.name}-{agent}-{stamp}"
        LOGGER.info("phase=readiness agent=%s job=%s status=started", agent, job)
        started = time.monotonic()
        exit_code = self._run_harbor(self._command(agent, job), job)
        if exit_code is None:
            result = "timeout"
        elif exit_code:
            result = f"harbor_exit_{exit_code}"
        else:
            result = _read_verdict(self.jobs_dir / job)
        LOGGER.info(
            "phase=readiness agent=%s job=%s status=finished result=%s "
            "duration_sec=%.1f",
            agent,
            job,
            result,
            time.monotonic() - started,
        )
        return ControlRun(agent, job, result)

    def _command(self, agent: str, job: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "harbor.cli.main",
            "run",
            "--path",
            str(self.task_dir),
            "--agent",
            agent,
            "--env",
            ENVIRONMENT_IMPORT_PATH,
            "--ek",
            f"cleanup_timeout_sec={self.cleanup_timeout_sec}",
            "--jobs-dir",
            str(self.jobs_dir),
            "--job-name",
            job,
            "--n-concurrent",
            "1",
            "--n-attempts",
            "1",
            "--quiet",
            "--yes",
        ]

    def _run_harbor(self, command: list[str], job: str) -> int | None:
        """Run Harbor with a deadline; return its exit code, or None on timeout.

        Harbor's console output goes to stderr so stdout keeps only command
        results. Harbor runs in its own session so that a terminal interrupt
        reaches only this process, which then stops Harbor exactly once.
        """
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=2,
            stderr=2,
            start_new_session=True,
        )
        try:
            exit_code = self._wait(process, job)
        except KeyboardInterrupt:
            LOGGER.warning("phase=readiness job=%s status=interrupted", job)
            self._stop(process, job)
            raise
        if exit_code is None:
            LOGGER.error("phase=readiness job=%s status=timeout", job)
            self._stop(process, job)
        return exit_code

    def _wait(self, process: subprocess.Popen[bytes], job: str) -> int | None:
        """Return Harbor's exit code, or None once the run deadline has passed."""
        started = time.monotonic()
        while (remaining := self.run_timeout_sec - (time.monotonic() - started)) > 0:
            try:
                return process.wait(timeout=min(PROGRESS_INTERVAL_SEC, remaining))
            except subprocess.TimeoutExpired:
                LOGGER.info(
                    "phase=readiness job=%s status=running elapsed_sec=%.0f",
                    job,
                    time.monotonic() - started,
                )
        return None

    def _stop(self, process: subprocess.Popen[bytes], job: str) -> None:
        """Interrupt Harbor so it can stop the Trial, then kill it after the grace.

        A kill, including one forced by a second interrupt, leaves the Trial's
        cleanup unconfirmed.
        """
        process.send_signal(signal.SIGINT)
        try:
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=self.cleanup_timeout_sec)
        finally:
            if process.poll() is None:
                LOGGER.warning("phase=readiness job=%s cleanup=unconfirmed", job)
                process.kill()
                process.wait()
