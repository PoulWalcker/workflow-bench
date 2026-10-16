"""Assess independently observed status lines and their collected final state."""

import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_bytes, read_json
from workflow_bench.evaluation import write_evaluation
from workflow_bench.window import read_window

EVIDENCE = Path("/window-evidence")
STATUS_PATH = Path("/work/output/status.log")
VERIFIER_DIR = Path("/logs/verifier")


def main() -> None:
    """Write four criteria, retaining final-state violations without a window."""
    expected = read_json(Path("/tests/expected/files.json"), "expected")
    if not isinstance(expected, dict) or type(expected.get("file_count")) is not int:
        raise DataError("invalid_expected", "expected")
    file_count = cast(int, expected["file_count"])
    final, content_reason = _final_content(file_count)
    lines = final.splitlines()
    duplicate_reason = "duplicate_lines" if len(set(lines)) != len(lines) else "pass"
    criteria: list[Criterion]
    try:
        criteria = _window_criteria(final, file_count)
    except (DataError, OSError, ValueError):
        criteria = [
            {
                "criterion_id": name,
                "status": "unknown",
                "reason_code": "window_incomplete",
            }
            for name in ("runs_count", "interval", "no_duplicates", "content")
        ]
    for criterion, reason in zip(
        criteria[2:], (duplicate_reason, content_reason), strict=True
    ):
        if reason != "pass":
            criterion.update(status="fail", reason_code=reason)
    for entry in VERIFIER_DIR.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    write_evaluation(VERIFIER_DIR, criteria)


def _final_content(file_count: int) -> tuple[bytes, str]:
    if any(path.is_symlink() for path in (STATUS_PATH, *STATUS_PATH.parents)):
        return b"", "invalid_content"
    try:
        final = read_bytes(STATUS_PATH, "status.log")
    except FileNotFoundError:
        return b"", "missing_status"
    except (DataError, OSError):
        return b"", "invalid_content"
    if any(
        _line_time(line, file_count) is None for line in final.splitlines(keepends=True)
    ):
        return final, "invalid_content"
    return final, "pass"


def _window_criteria(final: bytes, file_count: int) -> list[Criterion]:
    facts = read_window(EVIDENCE)
    if (
        facts.status != "completed"
        or facts.started_at is None
        or facts.elapsed_sec is None
        or facts.elapsed_sec < 660
        or not facts.samples
        or facts.samples[0].actual_offset_sec > 10
        or facts.samples[-1].actual_offset_sec < 660
    ):
        raise DataError("window_incomplete", "window")
    started = datetime.fromisoformat(facts.started_at)
    offsets: list[float] = []
    previous = b""
    previous_offset = -1.0
    has_batch = False
    content_reason = "pass"
    for sample in facts.samples:
        if sample.actual_offset_sec <= previous_offset:
            raise DataError("invalid_sample", "window")
        previous_offset = sample.actual_offset_sec
        observation = sample.paths.get(str(STATUS_PATH))
        if observation is None or observation["state"] not in {"regular", "missing"}:
            raise DataError("invalid_sample", "window")
        if observation["state"] == "missing":
            if observation["copy"] is not None or observation["sha256"] is not None:
                raise DataError("invalid_sample", "window")
            current = b""
        else:
            if observation["copy"] is None:
                current = previous
            else:
                current = read_bytes(EVIDENCE / observation["copy"], "sample")
            if hashlib.sha256(current).hexdigest() != observation["sha256"]:
                raise DataError("invalid_sample", "window")
        if not current.startswith(previous):
            content_reason = "rewritten"
        complete_lines = current.splitlines(keepends=True)
        if complete_lines and not complete_lines[-1].endswith(b"\n"):
            complete_lines.pop()
        previous_lines = previous.count(b"\n")
        added = complete_lines[previous_lines:]
        if 0 < sample.actual_offset_sec <= 660:
            offsets.extend([sample.actual_offset_sec] * len(added))
            has_batch = has_batch or len(added) > 1
            for line in added:
                claimed = _line_time(line, file_count)
                if (
                    claimed is None
                    or abs(
                        (claimed - started).total_seconds() - sample.actual_offset_sec
                    )
                    > 60
                ):
                    if content_reason == "pass":
                        content_reason = "wrong_time"
        previous = current
    if not final.startswith(previous):
        content_reason = "rewritten"
    return [
        _criterion(
            "runs_count", "pass" if 4 <= len(offsets) <= 6 else "wrong_runs_count"
        ),
        _criterion("interval", _interval(offsets)),
        _criterion("no_duplicates", "duplicate_lines" if has_batch else "pass"),
        _criterion("content", content_reason),
    ]


def _criterion(name: str, reason: str) -> Criterion:
    return {
        "criterion_id": name,
        "status": "pass" if reason == "pass" else "fail",
        "reason_code": reason,
    }


def _interval(offsets: list[float]) -> str:
    if len(offsets) < 2:
        return "too_few_runs"
    if offsets[0] > 180 or offsets[-1] < 420:
        return "outside_interval"
    if any(
        not 60 <= right - left <= 180
        for left, right in zip(offsets, offsets[1:], strict=False)
    ):
        return "outside_interval"
    return "pass"


def _line_time(line: bytes, file_count: int) -> datetime | None:
    pattern = (
        rb"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z "
        + str(file_count).encode()
        + rb"\n"
    )
    if re.fullmatch(pattern, line) is None:
        return None
    try:
        return datetime.strptime(
            line[:20].decode("ascii"), "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except ValueError:
        return None


if __name__ == "__main__":
    main()
