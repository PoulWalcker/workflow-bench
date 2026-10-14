"""Assess the collected repository against private replacements and protected files."""

import errno
import hashlib
import json
import os
import selectors
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from workflow_bench.contracts import Criterion
from workflow_bench.evaluation import write_evaluation

REPO = Path("/app/dclm")
EXPECTED = Path("/tests/expected")
VERIFIER_DIR = Path("/logs/verifier")
CONTAMINATED = (
    "ray_processing/ray_cluster.yaml",
    "ray_processing/process.py",
    (
        "exp_data/datasets/tokenized/"
        "rw_v2_fasttext_openhermes_vs_rw_v2_bigram_0.1_arcade100k.json"
    ),
)
MAX_CONTAMINATED_BYTES = 4 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 10
MAX_GIT_OUTPUT_BYTES = 1024 * 1024
EXPECTED_SUFFIXES = {"ray_processing/process.py": ".txt"}
type ReadProblem = Literal["missing_or_invalid", "too_large", "unavailable"]


def main() -> None:
    """Write one Criterion per upstream test and a safe verifier summary."""
    started = time.monotonic()
    token_hashes = _load_token_hashes()
    protected = _load_protected()
    candidate: dict[str, bytes | ReadProblem] = {
        relative: _read_regular(REPO / relative, MAX_CONTAMINATED_BYTES)
        for relative in CONTAMINATED
    }
    criteria: list[Criterion] = [
        _secrets_removed(candidate, token_hashes),
        _placeholders_exact(candidate),
        _no_collateral_changes(protected),
    ]
    evaluation = write_evaluation(VERIFIER_DIR, criteria)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sys.stdout.write(
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"duration={time.monotonic() - started:.3f}s criteria={len(criteria)}\n"
    )


def _secrets_removed(
    candidate: dict[str, bytes | ReadProblem], token_hashes: dict[int, set[str]]
) -> Criterion:
    """Check the five private fake values in every contaminated file, ignoring case."""
    has_unknown = False
    for content in candidate.values():
        if content == "missing_or_invalid":
            return _criterion("secrets_removed", "fail", "missing_or_invalid_file")
        if isinstance(content, str):
            has_unknown = True
            continue
        lowercase = content.lower()
        for length, expected_hashes in token_hashes.items():
            for offset in range(len(lowercase) - length + 1):
                digest = hashlib.sha256(lowercase[offset : offset + length]).hexdigest()
                if digest in expected_hashes:
                    return _criterion("secrets_removed", "fail", "secret_present")
    if has_unknown:
        return _criterion("secrets_removed", "unknown", "file_unavailable")
    return _criterion("secrets_removed", "pass", "pass")


def _placeholders_exact(candidate: dict[str, bytes | ReadProblem]) -> Criterion:
    """Compare each repaired file byte for byte with its private upstream copy."""
    has_unknown = False
    for relative, content in candidate.items():
        if content in ("missing_or_invalid", "too_large"):
            return _criterion("placeholders_exact", "fail", "missing_or_invalid_file")
        if content == "unavailable":
            has_unknown = True
            continue
        expected_name = relative + EXPECTED_SUFFIXES.get(relative, "")
        if content != (EXPECTED / expected_name).read_bytes():
            return _criterion("placeholders_exact", "fail", "replacement_mismatch")
    if has_unknown:
        return _criterion("placeholders_exact", "unknown", "file_unavailable")
    return _criterion("placeholders_exact", "pass", "pass")


def _no_collateral_changes(protected: dict[str, tuple[int, str]]) -> Criterion:
    """Verify authored protected paths have their original bytes and index entries."""
    tracked_paths = _tracked_paths(set(protected))
    has_unknown = tracked_paths is None
    for relative, (size, digest) in protected.items():
        if tracked_paths is not None and relative not in tracked_paths:
            return _criterion(
                "no_collateral_changes", "fail", "protected_index_missing"
            )
        content = _read_regular(REPO / relative, size)
        if content == "unavailable":
            has_unknown = True
            continue
        if isinstance(content, str):
            return _criterion(
                "no_collateral_changes", "fail", "protected_file_missing_or_invalid"
            )
        if hashlib.sha256(content).hexdigest() != digest:
            return _criterion("no_collateral_changes", "fail", "protected_file_changed")
    if has_unknown:
        return _criterion(
            "no_collateral_changes", "unknown", "protected_state_unavailable"
        )
    return _criterion("no_collateral_changes", "pass", "pass")


def _tracked_paths(protected_paths: set[str]) -> set[str] | None:
    """Read at most one MiB of git index names within the process deadline."""
    try:
        process = subprocess.Popen(
            ["git", "-c", "safe.directory=*", "-C", str(REPO), "ls-files", "-z"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    output = bytearray()
    try:
        if process.stdout is None:
            return None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                ready = selector.select(max(0, deadline - time.monotonic()))
                if not ready:
                    return None
                chunk = os.read(
                    process.stdout.fileno(),
                    min(65536, MAX_GIT_OUTPUT_BYTES + 1 - len(output)),
                )
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > MAX_GIT_OUTPUT_BYTES:
                    return None
        process.wait(timeout=max(0, deadline - time.monotonic()))
        if process.returncode != 0:
            return None
        tracked_paths: set[str] = set()
        for path in bytes(output).split(b"\0"):
            if path:
                relative = os.fsdecode(path)
                if relative in protected_paths:
                    tracked_paths.add(relative)
        return tracked_paths
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()
        if process.stdout is not None:
            process.stdout.close()


def _read_regular(path: Path, max_bytes: int) -> bytes | ReadProblem:
    """Read a bounded regular file without following candidate-controlled symlinks."""
    relative = path.relative_to(REPO)
    try:
        directory = os.open(REPO, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in relative.parts[:-1]:
                child = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory,
                )
                os.close(directory)
                directory = child
            descriptor = os.open(
                relative.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return "missing_or_invalid"
            content = stream.read(max_bytes + 1)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            return "missing_or_invalid"
        return "unavailable"
    if len(content) > max_bytes:
        return "too_large"
    return content


def _load_token_hashes() -> dict[int, set[str]]:
    """Load only lengths and lowercase SHA-256 values from verifier-owned data."""
    raw = json.loads((EXPECTED / "token_hashes.json").read_text())
    tokens: dict[int, set[str]] = {}
    for item in raw["tokens"]:
        tokens.setdefault(item["length"], set()).add(item["sha256"])
    return tokens


def _load_protected() -> dict[str, tuple[int, str]]:
    """Load the finite authored list of tracked files at the pinned source commit."""
    raw = json.loads((EXPECTED / "protected.json").read_text())
    return {
        relative: (entry["size"], entry["sha256"])
        for relative, entry in raw["files"].items()
    }


def _criterion(
    identifier: str,
    status: Literal["pass", "fail", "unknown", "not_applicable"],
    reason: str,
) -> Criterion:
    """Build a Criterion without exposing repository contents in feedback."""
    return {"criterion_id": identifier, "status": status, "reason_code": reason}


if __name__ == "__main__":
    main()
