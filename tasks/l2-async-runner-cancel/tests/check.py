"""Assess the async runner with the private upstream harness."""

import errno
import os
import pwd
import resource
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal

from workflow_bench.contracts import Criterion
from workflow_bench.evaluation import write_evaluation

CANDIDATE = Path("/app/run.py")
HARNESS = Path("/tests/test.py")
VERIFIER_DIR = Path("/logs/verifier")
MAX_CANDIDATE_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
STOP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Case:
    """An upstream harness invocation and its expected observable result."""

    criterion_id: str
    n_tasks: int
    max_concurrent: int
    timeout_seconds: float
    is_cancelled: bool = False
    minimum_seconds: float = 0.0


CASES = (
    Case("runs_concurrently", 2, 2, 5),
    Case("obeys_max_concurrent", 2, 1, 10, minimum_seconds=6),
    Case("cancel_below_max", 2, 3, 5, is_cancelled=True),
    Case("cancel_at_max", 2, 2, 5, is_cancelled=True),
    Case("cancel_above_max", 3, 2, 5, is_cancelled=True),
)


def main() -> None:
    """Run each private test in a fresh unprivileged process, then write evaluation."""
    candidate = _read_candidate()
    if candidate is None:
        criteria = [_criterion("run_file_exists", "fail", "no_answer")]
        criteria.extend(
            _criterion(case.criterion_id, "fail", "no_answer") for case in CASES
        )
    else:
        criteria = [_criterion("run_file_exists", "pass", "pass")]
        with tempfile.TemporaryDirectory(prefix="async-runner-runtime-") as directory:
            runtime_root = Path(directory)
            _prepare_runtime(runtime_root)
            criteria.extend(_run_case(case, candidate, runtime_root) for case in CASES)
    criteria.append(
        _criterion("no_collateral_changes", "not_applicable", "no_protected_state")
    )
    _clear_verifier_dir()
    write_evaluation(VERIFIER_DIR, criteria)


def _read_candidate() -> bytes | None:
    """Read only a bounded regular answer file without following a symlink."""
    try:
        descriptor = os.open(CANDIDATE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            content = stream.read(MAX_CANDIDATE_BYTES + 1)
    except OSError as error:
        if error.errno in (
            errno.ENOENT,
            errno.ENOTDIR,
            errno.EACCES,
            errno.EPERM,
            errno.ELOOP,
        ):
            return None
        raise
    if len(content) > MAX_CANDIDATE_BYTES:
        return None
    return content


def _prepare_runtime(runtime_root: Path) -> None:
    """Copy the public Python runtime into a root that cannot reach private tests."""
    (runtime_root / "usr/local/bin").mkdir(parents=True)
    shutil.copy2(
        Path(sys.executable).resolve(), runtime_root / sys.executable.lstrip("/")
    )
    shutil.copytree("/usr/local/lib", runtime_root / "usr/local/lib", symlinks=True)
    shutil.copytree("/usr/lib", runtime_root / "usr/lib", symlinks=True)
    os.symlink("usr/lib", runtime_root / "lib")
    (runtime_root / "work").mkdir()
    (runtime_root / "tmp").mkdir()
    os.chmod(runtime_root / "tmp", 0o1777)
    os.chmod(runtime_root, 0o755)


def _run_case(case: Case, candidate: bytes, runtime_root: Path) -> Criterion:
    """Preserve upstream timings and counts while isolating one invocation."""
    status: Literal["pass", "fail", "unknown"] = "unknown"
    reason = "candidate_unavailable"
    with tempfile.TemporaryDirectory(
        prefix="async-runner-", dir=runtime_root / "work"
    ) as directory:
        working_dir = Path(directory)
        os.chmod(working_dir, 0o755)
        runner_copy = working_dir / "run.py"
        harness_copy = working_dir / "test.py"
        runner_copy.write_bytes(candidate)
        harness_copy.write_bytes(HARNESS.read_bytes())
        runner_copy.chmod(0o644)
        harness_copy.chmod(0o644)
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            started = time.monotonic()
            process: subprocess.Popen[bytes] | None = None
            try:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "test.py",
                        "--n-tasks",
                        str(case.n_tasks),
                        "--max-concurrent",
                        str(case.max_concurrent),
                    ],
                    cwd=working_dir,
                    stdout=stdout,
                    stderr=stderr,
                    env={**os.environ, "LD_LIBRARY_PATH": "/usr/local/lib"},
                    start_new_session=True,
                    preexec_fn=partial(
                        _drop_privileges, runtime_root, working_dir.name
                    ),
                )
                if case.is_cancelled:
                    time.sleep(0.5)
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                process.wait(timeout=case.timeout_seconds)
                elapsed = time.monotonic() - started
                stdout.seek(0)
                output = stdout.read(MAX_OUTPUT_BYTES + 1)
                if len(output) >= MAX_OUTPUT_BYTES:
                    status, reason = "fail", "output_limit"
                elif not case.is_cancelled and process.returncode != 0:
                    status, reason = "fail", "runner_error"
                elif elapsed < case.minimum_seconds:
                    status, reason = "fail", "concurrency_limit"
                elif _output_matches(case, output):
                    status, reason = "pass", "pass"
                else:
                    status, reason = "fail", "output_mismatch"
            except subprocess.TimeoutExpired:
                status, reason = "fail", "runner_timeout"
            except (OSError, subprocess.SubprocessError):
                status, reason = "unknown", "runner_unavailable"
            finally:
                if not _stop_candidate(process):
                    status, reason = "unknown", "candidate_not_stopped"
    return _criterion(case.criterion_id, status, reason)


def _drop_privileges(runtime_root: Path, working_name: str) -> None:
    """Confine the candidate to its runtime and run it as nobody."""
    nobody = pwd.getpwnam("nobody")
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))
    os.chroot(runtime_root)
    os.chdir(f"/work/{working_name}")
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)


def _stop_candidate(process: subprocess.Popen[bytes] | None) -> bool:
    """Kill all nobody processes and confirm none remain before assessment continues."""
    try:
        killed = subprocess.run(
            ["pkill", "-KILL", "-u", "nobody"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=STOP_TIMEOUT_SECONDS,
        )
        if killed.returncode not in (0, 1):
            return False
        if process is not None:
            process.wait(timeout=STOP_TIMEOUT_SECONDS)
        deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            remaining = subprocess.run(
                ["pgrep", "-u", "nobody"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=STOP_TIMEOUT_SECONDS,
            )
            if remaining.returncode == 1:
                return True
            if remaining.returncode != 0:
                return False
            time.sleep(0.05)
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _output_matches(case: Case, output: bytes) -> bool:
    """Count the exact stdout lines asserted by the upstream tests."""
    expected = case.max_concurrent if case.criterion_id == "cancel_above_max" else 2
    if output.count(b"Task started.") != expected:
        return False
    if output.count(b"Cleaned up.") != expected:
        return False
    return case.is_cancelled or output.count(b"Task finished.") == 2


def _clear_verifier_dir() -> None:
    """Remove candidate-written files before the verifier writes its own verdict."""
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    for path in VERIFIER_DIR.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _criterion(
    identifier: str,
    status: Literal["pass", "fail", "unknown", "not_applicable"],
    reason: str,
) -> Criterion:
    """Return safe criterion feedback without candidate output or private details."""
    return {"criterion_id": identifier, "status": status, "reason_code": reason}


if __name__ == "__main__":
    main()
