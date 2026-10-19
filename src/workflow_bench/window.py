"""Run and read bounded task-owned observation windows."""

import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from workflow_bench._window_common import (
    CHUNK_BYTES,
    MAX_ACTIONS,
    MAX_DURATION_SEC,
    MAX_ENTRIES,
    MAX_EVIDENCE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PATH_LENGTH,
    MAX_SAMPLES,
    MAX_SCHEDULE_BYTES,
    MAX_SKIPPED,
    MAX_TAIL_SEC,
    MAX_WATCH,
    SCHEMA_VERSION,
    _has_symlink_component,
)
from workflow_bench._window_copy import BoundedCopy
from workflow_bench._window_evidence import (
    Drop,
    Observation,
    Sample,
    Skipped,
    Snapshot,
    WindowFacts,
    read_window,
)
from workflow_bench._window_schedule import DropPlan, SnapshotPlan, read_schedule
from workflow_bench.data import DataError, read_bytes

__all__ = [
    "CHUNK_BYTES",
    "MAX_ACTIONS",
    "MAX_DURATION_SEC",
    "MAX_ENTRIES",
    "MAX_EVIDENCE_BYTES",
    "MAX_MANIFEST_BYTES",
    "MAX_SAMPLES",
    "MAX_SCHEDULE_BYTES",
    "MAX_SKIPPED",
    "MAX_TAIL_SEC",
    "SCHEMA_VERSION",
    "Skipped",
    "MAX_PATH_LENGTH",
    "MAX_WATCH",
    "Observation",
    "Drop",
    "Snapshot",
    "Sample",
    "WindowFacts",
    "read_window",
    "read_schedule",
    "run_window",
]

LOGGER = logging.getLogger(__name__)


def run_window(
    schedule_path: Path,
    evidence_dir: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Execute a validated task schedule and atomically retain each action.

    Offsets start at invocation. A snapshot at a shared offset precedes its drop.
    Invalid schedules raise DataError before evidence or task files are changed.
    Runtime failures retain earlier evidence, mark it failed, and raise DataError.
    """
    schedule = read_schedule(schedule_path)
    start = clock()
    writer = _EvidenceWriter(evidence_dir, start, clock)
    previous_identities: dict[str, tuple[str, str]] = {}
    events: list[tuple[float, int, Callable[[], None]]] = []
    for index, snapshot in enumerate(schedule.snapshots):
        events.append(
            (snapshot.at_sec, 0, partial(_execute_snapshot, writer, snapshot, index))
        )
    for drop in schedule.drops:
        events.append((drop.at_sec, 1, partial(_execute_drop, writer, drop)))
    total = schedule.duration_sec + schedule.tail_sec
    for index, offset in enumerate(schedule.sample_offsets_sec):
        events.append(
            (
                offset,
                2,
                partial(
                    _execute_sample, writer, schedule.watch, previous_identities, index
                ),
            )
        )
    events.sort(key=lambda event: (event[0], event[1]))
    try:
        for offset, _, execute in events:
            _wait_until(start + offset, clock, sleep)
            execute()
            writer.save()
        _wait_until(start + total, clock, sleep)
        writer.manifest = replace(writer.manifest, status="completed")
    except Exception as error:
        writer.manifest = replace(
            writer.manifest,
            status="failed",
            error_code=(
                error.code if isinstance(error, DataError) else "window_action_failed"
            ),
        )
        LOGGER.error("phase=window status=failed code=%s", writer.manifest.error_code)
        raise DataError(str(writer.manifest.error_code), "window") from None
    finally:
        writer.manifest = replace(
            writer.manifest,
            ended_at=datetime.now(UTC).isoformat(),
            elapsed_sec=writer.offset(),
        )
        try:
            writer.save()
        except Exception as error:
            if writer.manifest.error_code is None:
                code = (
                    error.code
                    if isinstance(error, DataError)
                    else "window_action_failed"
                )
                raise DataError(code, "manifest.json") from None
            LOGGER.error("phase=window status=failed code=manifest_save_failed")


def main(argv: list[str] | None = None) -> int:
    """Run one collect hook, writing diagnostics only to stderr."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        sys.stderr.write(
            "usage: python -m workflow_bench.window <schedule.json> <evidence-dir>\n"
        )
        return 2
    try:
        run_window(Path(arguments[0]), Path(arguments[1]))
    except Exception as error:
        code = error.code if isinstance(error, DataError) else "window_action_failed"
        sys.stderr.write(f"window: {code}\n")
        return 1
    return 0


class _EvidenceWriter:
    """Own one window's manifest and aggregate copy limits."""

    def __init__(self, root: Path, start: float, clock: Callable[[], float]) -> None:
        self.root = root
        self.start = start
        self.clock = clock
        self.copier = BoundedCopy()
        self.manifest = WindowFacts(
            status="running",
            started_at=datetime.now(UTC).isoformat(),
            ended_at=None,
            elapsed_sec=None,
            error_code=None,
            drops=(),
            snapshots=(),
            samples=(),
            skipped=(),
            skipped_truncated=False,
        )
        if _has_symlink_component(root):
            raise DataError("unsafe_file", "evidence")
        root.mkdir(parents=True, exist_ok=True)
        if any(
            path.name != "manifest.json" or path.is_symlink() or not path.is_file()
            for path in root.iterdir()
        ):
            self.manifest = replace(
                self.manifest,
                status="failed",
                error_code="unsafe_file",
                ended_at=datetime.now(UTC).isoformat(),
                elapsed_sec=self.offset(),
            )
            self.save()
            raise DataError("unsafe_file", "evidence")
        self.save()

    def offset(self) -> float:
        """Return elapsed monotonic seconds."""
        return max(0.0, self.clock() - self.start)

    def save(self) -> None:
        """Replace the manifest atomically after a completed action."""
        self.manifest = replace(
            self.manifest,
            skipped=self.copier.skipped,
            skipped_truncated=self.copier.skipped_truncated,
        )
        content = (
            json.dumps(
                {"schema_version": SCHEMA_VERSION, **asdict(self.manifest)},
                sort_keys=True,
            )
            + "\n"
        ).encode()
        if len(content) > MAX_MANIFEST_BYTES:
            raise DataError("too_large", "manifest.json")
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".manifest-", dir=self.root, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        try:
            os.replace(temporary, self.root / "manifest.json")
        finally:
            temporary.unlink(missing_ok=True)


def _wait_until(
    deadline: float, clock: Callable[[], float], sleep: Callable[[float], None]
) -> None:
    """Sleep in short increments until an absolute monotonic deadline."""
    while clock() < deadline:
        sleep(min(0.1, deadline - clock()))


def _execute_drop(writer: _EvidenceWriter, plan: DropPlan) -> None:
    if (
        _has_symlink_component(plan.source)
        or not plan.source.is_file()
        or _has_symlink_component(plan.target)
        or (plan.target.exists() and not plan.target.is_file())
    ):
        raise DataError("unsafe_file", "drop")
    content = read_bytes(plan.source, "drop", limit=MAX_EVIDENCE_BYTES)
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".drop-",
            dir=plan.target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, plan.target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    writer.manifest = replace(
        writer.manifest,
        drops=(
            *writer.manifest.drops,
            Drop(
                planned_offset_sec=plan.at_sec,
                actual_offset_sec=writer.offset(),
                target=str(plan.target),
                sha256=hashlib.sha256(content).hexdigest(),
            ),
        ),
    )


def _execute_snapshot(writer: _EvidenceWriter, plan: SnapshotPlan, index: int) -> None:
    writer.copier.reset_observation()
    directory = f"snapshots/{index:03d}"
    destination = writer.root / directory
    destination.mkdir(parents=True)
    count = 0
    byte_count = 0
    truncated = False
    for path_index, path in enumerate(plan.paths):
        copied = writer.copier.copy_path(
            path, destination / f"{path_index:02d}-{path.name}"
        )
        count += copied.entries
        byte_count += copied.bytes
        truncated |= copied.truncated
    writer.manifest = replace(
        writer.manifest,
        snapshots=(
            *writer.manifest.snapshots,
            Snapshot(
                planned_offset_sec=plan.at_sec,
                actual_offset_sec=writer.offset(),
                directory=directory,
                entries=count,
                bytes=byte_count,
                truncated=truncated,
            ),
        ),
    )


def _execute_sample(
    writer: _EvidenceWriter,
    watch: tuple[Path, ...],
    previous: dict[str, tuple[str, str]],
    index: int,
) -> None:
    writer.copier.reset_observation()
    paths: dict[str, Observation] = {}
    for path_index, path in enumerate(watch):
        destination = writer.root / f"samples/{index:04d}/{path_index:02d}-{path.name}"
        result = writer.copier.copy_changed(path, destination, previous.get(str(path)))
        state, digest = result.kind, result.sha256
        if result.truncated:
            state = "truncated"
        copied = None
        if destination.exists():
            copied = destination.relative_to(writer.root).as_posix()
        if digest is not None:
            previous[str(path)] = (result.kind, digest)
        else:
            previous.pop(str(path), None)
        paths[str(path)] = {"state": state, "sha256": digest, "copy": copied}
    writer.manifest = replace(
        writer.manifest,
        samples=(
            *writer.manifest.samples,
            Sample(actual_offset_sec=writer.offset(), paths=paths),
        ),
    )


if __name__ == "__main__":
    raise SystemExit(main())
