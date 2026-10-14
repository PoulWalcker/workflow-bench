"""Assess the candidate regex against a private sample log."""

import errno
import os
import re
import stat
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Literal

from workflow_bench.contracts import Criterion
from workflow_bench.evaluation import write_evaluation

REGEX_FILE = Path("/app/regex.txt")
VERIFIER_DIR = Path("/logs/verifier")
MAX_PATTERN_BYTES = 16 * 1024
MATCH_TIMEOUT_SECONDS = 3


class ReadProblem(Enum):
    """Classify candidate-file problems separately from valid pattern text."""

    INVALID = "invalid"
    TOO_LARGE = "too_large"
    UNAVAILABLE = "unavailable"


def main() -> None:
    """Write bounded candidate-file and private-match Criteria."""
    pattern = _read_pattern()
    regex_file = _regex_file_criterion(pattern)
    criteria = [
        regex_file,
        _matches_expected(pattern, regex_file),
        _criterion("no_collateral_changes", "not_applicable", "no_protected_state"),
    ]
    write_evaluation(VERIFIER_DIR, criteria)


def _read_pattern() -> str | ReadProblem:
    """Read a bounded regular file without following a candidate symlink."""
    try:
        descriptor = os.open(REGEX_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return ReadProblem.INVALID
            content = stream.read(MAX_PATTERN_BYTES + 1)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            return ReadProblem.INVALID
        return ReadProblem.UNAVAILABLE
    if len(content) > MAX_PATTERN_BYTES:
        return ReadProblem.TOO_LARGE
    try:
        return content.decode("utf-8").strip()
    except UnicodeDecodeError:
        return ReadProblem.INVALID


def _regex_file_criterion(pattern: str | ReadProblem) -> Criterion:
    """Confirm that the candidate supplied a readable, valid pattern."""
    if pattern in (ReadProblem.INVALID, ReadProblem.TOO_LARGE):
        return _criterion("regex_file", "fail", "missing_or_invalid_regex")
    if pattern is ReadProblem.UNAVAILABLE:
        return _criterion("regex_file", "unknown", "file_unavailable")
    if not isinstance(pattern, str):
        return _criterion("regex_file", "unknown", "file_unavailable")
    try:
        re.compile(pattern)
    except (re.error, RecursionError, OverflowError):
        return _criterion("regex_file", "fail", "invalid_regex")
    return _criterion("regex_file", "pass", "pass")


def _matches_expected(pattern: str | ReadProblem, regex_file: Criterion) -> Criterion:
    """Compare sample-log matches in a subprocess with a finite deadline."""
    if regex_file["status"] == "fail":
        return _criterion("matches_expected", "not_applicable", "invalid_regex_file")
    if regex_file["status"] != "pass" or not isinstance(pattern, str):
        return _criterion("matches_expected", "unknown", "regex_unavailable")
    try:
        process = subprocess.run(
            [sys.executable, "/tests/match.py"],
            input=pattern,
            capture_output=True,
            text=True,
            timeout=MATCH_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _criterion("matches_expected", "fail", "regex_timeout")
    except OSError:
        return _criterion("matches_expected", "unknown", "matcher_unavailable")
    if process.returncode != 0:
        return _criterion("matches_expected", "unknown", "matcher_error")
    if process.stdout == "pass\n":
        return _criterion("matches_expected", "pass", "pass")
    if process.stdout == "mismatch\n":
        return _criterion("matches_expected", "fail", "matches_mismatch")
    return _criterion("matches_expected", "unknown", "matcher_output_invalid")


def _criterion(
    identifier: str,
    status: Literal["pass", "fail", "unknown", "not_applicable"],
    reason: str,
) -> Criterion:
    """Build a Criterion without including candidate content in feedback."""
    return {"criterion_id": identifier, "status": status, "reason_code": reason}


if __name__ == "__main__":
    main()
