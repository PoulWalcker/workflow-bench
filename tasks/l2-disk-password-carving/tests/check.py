"""Assess recovered password guesses and preservation of the evidence files."""

import codecs
import errno
import hashlib
import json
import os
import stat
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

from workflow_bench.contracts import Criterion
from workflow_bench.evaluation import write_evaluation

APP = Path("/app")
EXPECTED = Path("/tests/expected")
VERIFIER_DIR = Path("/logs/verifier")
MAX_ANSWER_BYTES = 1024 * 1024
type ReadProblem = Literal["missing_or_invalid", "too_large", "unavailable"]


class ProtectedFileEntry(TypedDict):
    size: int
    sha256: str


class ProtectedManifest(TypedDict):
    files: dict[str, ProtectedFileEntry]


def main() -> None:
    """Write the three task criteria after reading the collected workspace."""
    started = time.monotonic()
    answer = _read_regular(APP, "recovered_passwords.txt", MAX_ANSWER_BYTES)
    criteria = [
        _recovery_file_exists(answer),
        _password_found(answer),
        _no_collateral_changes(),
    ]
    evaluation = write_evaluation(VERIFIER_DIR, criteria)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sys.stdout.write(
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"duration={time.monotonic() - started:.3f}s criteria={len(criteria)}\n"
    )


def _recovery_file_exists(answer: bytes | ReadProblem) -> Criterion:
    if answer == "missing_or_invalid":
        return _criterion("recovery_file_exists", "fail", "no_answer")
    if answer == "unavailable":
        return _criterion("recovery_file_exists", "unknown", "answer_unavailable")
    return _criterion("recovery_file_exists", "pass", "pass")


def _password_found(answer: bytes | ReadProblem) -> Criterion:
    if answer == "missing_or_invalid":
        return _criterion("password_found", "fail", "no_answer")
    if answer == "unavailable":
        return _criterion("password_found", "unknown", "answer_unavailable")
    expected = (EXPECTED / "password.txt").read_text().strip()
    if answer == "too_large":
        found = _scan_large_answer(expected)
        if found == "unavailable":
            return _criterion("password_found", "unknown", "answer_unavailable")
        if found == "invalid":
            return _criterion("password_found", "fail", "invalid_answer")
        if not found:
            return _criterion("password_found", "fail", "password_missing")
        return _criterion("password_found", "pass", "pass")
    try:
        guesses = answer.decode("utf-8").strip().split("\n")
    except UnicodeDecodeError:
        return _criterion("password_found", "fail", "invalid_answer")
    if expected not in guesses:
        return _criterion("password_found", "fail", "password_missing")
    return _criterion("password_found", "pass", "pass")


def _scan_large_answer(expected: str) -> bool | Literal["invalid", "unavailable"]:
    """Match complete lines with bounded memory, including file-edge whitespace."""
    descriptor = _open_regular(APP, "recovered_passwords.txt")
    if isinstance(descriptor, str):
        return "unavailable"
    found = False
    prefix: str | None = ""
    at_start = True
    trailing_candidate = False
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with os.fdopen(descriptor, "rb") as stream:
            while True:
                chunk = stream.read(65536)
                decoded = decoder.decode(chunk, final=not chunk)
                for character in decoded:
                    if at_start and character.isspace():
                        continue
                    at_start = False
                    if trailing_candidate and not character.isspace():
                        trailing_candidate = False
                    if character == "\n":
                        if prefix == expected:
                            found = True
                        prefix = ""
                    elif prefix is not None:
                        if (
                            len(prefix) < len(expected)
                            and character == expected[len(prefix)]
                        ):
                            prefix += character
                        elif prefix == expected and character.isspace():
                            trailing_candidate = True
                            prefix = None
                        else:
                            prefix = None
                if not chunk:
                    break
    except UnicodeDecodeError:
        return "invalid"
    except OSError:
        return "unavailable"
    return found or prefix == expected or trailing_candidate


def _no_collateral_changes() -> Criterion:
    manifest = cast(
        ProtectedManifest, json.loads((EXPECTED / "protected.json").read_text())
    )
    has_unknown = False
    for relative, entry in manifest["files"].items():
        content = _read_regular(APP, f"varsea/{relative}", entry["size"])
        if content == "unavailable":
            has_unknown = True
            continue
        if isinstance(content, str):
            return _criterion(
                "no_collateral_changes", "fail", "protected_file_missing_or_invalid"
            )
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            return _criterion("no_collateral_changes", "fail", "protected_file_changed")
    if has_unknown:
        return _criterion(
            "no_collateral_changes", "unknown", "protected_state_unavailable"
        )
    return _criterion("no_collateral_changes", "pass", "pass")


def _read_regular(root: Path, relative: str, max_bytes: int) -> bytes | ReadProblem:
    """Read a bounded file while rejecting symlinks in its entire path."""
    descriptor = _open_regular(root, relative)
    if isinstance(descriptor, str):
        return descriptor
    try:
        with os.fdopen(descriptor, "rb") as stream:
            content = stream.read(max_bytes + 1)
    except OSError:
        return "unavailable"
    if len(content) > max_bytes:
        return "too_large"
    return content


def _open_regular(
    root: Path, relative: str
) -> int | Literal["missing_or_invalid", "unavailable"]:
    """Open a regular file without following candidate-controlled symlinks."""
    components = Path(relative).parts
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for component in components[:-1]:
                child = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=directory,
                )
                os.close(directory)
                directory = child
            descriptor = os.open(
                components[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
        finally:
            os.close(directory)
        try:
            is_regular = stat.S_ISREG(os.fstat(descriptor).st_mode)
        except OSError:
            os.close(descriptor)
            raise
        if not is_regular:
            os.close(descriptor)
            return "missing_or_invalid"
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            return "missing_or_invalid"
        return "unavailable"
    return descriptor


def _criterion(
    identifier: str,
    status: Literal["pass", "fail", "unknown", "not_applicable"],
    reason: str,
) -> Criterion:
    return {"criterion_id": identifier, "status": status, "reason_code": reason}


if __name__ == "__main__":
    main()
