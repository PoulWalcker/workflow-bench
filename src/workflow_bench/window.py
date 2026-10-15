"""Run and read bounded task-owned observation windows."""

import hashlib
import itertools
import json
import logging
import math
import os
import stat
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from workflow_bench.data import DataError, decode_json, read_bytes

LOGGER = logging.getLogger(__name__)
SCHEMA_VERSION = 1
MAX_SCHEDULE_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_SAMPLES = 128
MAX_SKIPPED = 1024
MAX_ACTIONS = 128
MAX_WATCH = 32
MAX_PATH_LENGTH = 256
MAX_DURATION_SEC = 3600
MAX_TAIL_SEC = 600
CHUNK_BYTES = 64 * 1024


class _DropRecord(TypedDict):
    planned_offset_sec: float
    actual_offset_sec: float
    target: str
    sha256: str


class _SnapshotRecord(TypedDict):
    planned_offset_sec: float
    actual_offset_sec: float
    directory: str
    entries: int
    bytes: int
    truncated: bool


class Observation(TypedDict):
    """Validated state, digest, and optional stored copy of one watched path."""

    state: str
    sha256: str | None
    copy: str | None


class _SampleRecord(TypedDict):
    actual_offset_sec: float
    paths: dict[str, Observation]


class _SkippedRecord(TypedDict):
    path: str
    kind: Literal["symlink", "special"]


class _Manifest(TypedDict):
    """Window state: only terminal states have end/elapsed values.

    `not_started` exists only in task-seeded evidence. A running window has a
    start time and no end, elapsed time, or error. Completion has no error;
    failure has an error code and retains earlier action records.
    """

    schema_version: int
    status: Literal["running", "completed", "failed"]
    started_at: str
    ended_at: str | None
    elapsed_sec: float | None
    error_code: str | None
    drops: list[_DropRecord]
    snapshots: list[_SnapshotRecord]
    samples: list[_SampleRecord]
    skipped: list[_SkippedRecord]
    skipped_truncated: bool


@dataclass(frozen=True)
class Drop:
    """A delivered input with its planned and observed offsets in seconds."""

    planned_offset_sec: float
    actual_offset_sec: float
    target: str
    sha256: str


@dataclass(frozen=True)
class Snapshot:
    """A bounded stored view of task paths at one offset."""

    planned_offset_sec: float
    actual_offset_sec: float
    directory: str
    entries: int
    bytes: int
    truncated: bool


@dataclass(frozen=True)
class Sample:
    """One watched-path observation, including changed-copy references."""

    actual_offset_sec: float
    paths: dict[str, Observation]


@dataclass(frozen=True)
class Skipped:
    """A symlink or special file excluded from an observation."""

    path: str
    kind: Literal["symlink", "special"]


@dataclass(frozen=True)
class WindowFacts:
    """Validated evidence, including an explicit incomplete status."""

    status: Literal["not_started", "running", "completed", "failed"]
    started_at: str | None
    ended_at: str | None
    elapsed_sec: float | None
    drops: tuple[Drop, ...]
    snapshots: tuple[Snapshot, ...]
    samples: tuple[Sample, ...]
    skipped: tuple[Skipped, ...]
    skipped_truncated: bool
    error_code: str | None


@dataclass(frozen=True)
class _DropPlan:
    at_sec: float
    source: Path
    target: Path


@dataclass(frozen=True)
class _SnapshotPlan:
    at_sec: float
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class _Schedule:
    duration_sec: float
    tail_sec: float
    sample_interval_sec: float
    watch: tuple[Path, ...]
    drops: tuple[_DropPlan, ...]
    snapshots: tuple[_SnapshotPlan, ...]


@dataclass
class _CopyBudget:
    """Bound bytes, entries and child visits for one copy or observation pass."""

    bytes: int = 0
    entries: int = 0
    scanned: int = 0


class _EvidenceWriter:
    """Own one window's manifest and aggregate copy limits."""

    def __init__(self, root: Path, start: float, clock: Callable[[], float]) -> None:
        self.root = root
        self.start = start
        self.clock = clock
        self.storage = _CopyBudget()
        self.observed = _CopyBudget()
        self.manifest: _Manifest = {
            "schema_version": SCHEMA_VERSION,
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "ended_at": None,
            "elapsed_sec": None,
            "error_code": None,
            "drops": [],
            "snapshots": [],
            "samples": [],
            "skipped": [],
            "skipped_truncated": False,
        }
        if _has_symlink_component(root):
            raise DataError("unsafe_file", "evidence")
        root.mkdir(parents=True, exist_ok=True)
        if any(
            path.name != "manifest.json" or path.is_symlink() or not path.is_file()
            for path in root.iterdir()
        ):
            self.manifest["status"] = "failed"
            self.manifest["error_code"] = "unsafe_file"
            self.manifest["ended_at"] = datetime.now(UTC).isoformat()
            self.manifest["elapsed_sec"] = self.offset()
            self.save()
            raise DataError("unsafe_file", "evidence")
        self.save()

    def offset(self) -> float:
        """Return elapsed monotonic seconds."""
        return max(0.0, self.clock() - self.start)

    def save(self) -> None:
        """Replace the manifest atomically after a completed action."""
        content = (json.dumps(self.manifest, sort_keys=True) + "\n").encode()
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

    def copy_path(
        self, source: Path, destination: Path | None
    ) -> tuple[int, int, bool, str]:
        """Copy within aggregate storage while hashing within independent action bounds.

        Return stored file count, stored bytes, copy truncation, and observed content
        SHA-256. Observation reads at most 32 MiB and visits at most 4096 children
        per action, even when storage is exhausted. Incomplete observations return
        a status word instead of a digest; storage truncation alone does not change
        content identity. A null destination observes without storing.
        """
        if _has_symlink_component(source):
            self.record_skip(source, "symlink")
            return 0, 0, False, "symlink"
        try:
            mode = source.lstat().st_mode
        except FileNotFoundError:
            return 0, 0, False, "missing"
        if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
            self.record_skip(source, "special")
            return 0, 0, False, "special"
        if self.observed.entries >= MAX_ENTRIES:
            return 0, 0, True, "truncated"
        self.observed.entries += 1
        if self.storage.entries >= MAX_ENTRIES:
            destination = None
        if stat.S_ISREG(mode):
            if self.storage.bytes >= MAX_EVIDENCE_BYTES:
                destination = None
            if destination is not None:
                self.storage.entries += 1
                destination.parent.mkdir(parents=True, exist_ok=True)
            remaining = MAX_EVIDENCE_BYTES - self.observed.bytes
            observed = 0
            written = 0
            digest = hashlib.sha256()
            with (
                source.open("rb") as input_stream,
                destination.open("wb")
                if destination is not None
                else nullcontext() as output,
            ):
                while observed < remaining:
                    chunk = input_stream.read(min(CHUNK_BYTES, remaining - observed))
                    if not chunk:
                        break
                    digest.update(chunk)
                    observed += len(chunk)
                    if output is not None:
                        stored = chunk[: MAX_EVIDENCE_BYTES - self.storage.bytes]
                        output.write(stored)
                        written += len(stored)
                        self.storage.bytes += len(stored)
                incomplete = bool(input_stream.read(1))
            self.observed.bytes += observed
            return (
                int(destination is not None),
                written,
                incomplete or destination is None or written < observed,
                "truncated" if incomplete else digest.hexdigest(),
            )
        if destination is not None:
            self.storage.entries += 1
            destination.mkdir(parents=True, exist_ok=True)
        count = 0
        byte_count = 0
        truncated = destination is None
        incomplete = False
        fingerprints: list[str] = []
        remaining = MAX_ENTRIES - self.observed.scanned
        children = list(itertools.islice(source.iterdir(), remaining + 1))
        if len(children) > remaining:
            incomplete = True
            children.pop()
        for child in sorted(children):
            if (
                self.observed.scanned >= MAX_ENTRIES
                or self.observed.bytes >= MAX_EVIDENCE_BYTES
            ):
                incomplete = True
                break
            self.observed.scanned += 1
            child_count, child_bytes, child_truncated, child_digest = self.copy_path(
                child, destination / child.name if destination is not None else None
            )
            count += child_count
            byte_count += child_bytes
            truncated |= child_truncated
            incomplete |= child_digest == "truncated"
            fingerprints.append(f"{child.name}:{child_digest}")
        digest = hashlib.sha256("\n".join(fingerprints).encode()).hexdigest()
        return (
            count,
            byte_count,
            truncated or incomplete,
            "truncated" if incomplete else digest,
        )

    def record_skip(self, path: Path, kind: Literal["symlink", "special"]) -> None:
        """Keep bounded metadata for entries intentionally left uncopied."""
        skipped = self.manifest["skipped"]
        if len(skipped) >= MAX_SKIPPED or len(str(path)) > MAX_PATH_LENGTH:
            self.manifest["skipped_truncated"] = True
            return
        skipped.append({"path": str(path), "kind": kind})


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
    schedule = _read_schedule(schedule_path)
    start = clock()
    writer = _EvidenceWriter(evidence_dir, start, clock)
    previous_digests: dict[str, str] = {}
    events: list[tuple[float, int, str, object]] = []
    for index, snapshot in enumerate(schedule.snapshots):
        events.append((snapshot.at_sec, 0, "snapshot", (index, snapshot)))
    for index, drop in enumerate(schedule.drops):
        events.append((drop.at_sec, 1, "drop", (index, drop)))
    total = schedule.duration_sec + schedule.tail_sec
    sample_count = int(total // schedule.sample_interval_sec) + 1
    for index in range(sample_count):
        events.append((index * schedule.sample_interval_sec, 2, "sample", index))
    events.sort(key=lambda event: (event[0], event[1]))
    try:
        for offset, _, kind, plan in events:
            _wait_until(start + offset, clock, sleep)
            if kind == "drop":
                _execute_drop(writer, plan)
            elif kind == "snapshot":
                _execute_snapshot(writer, plan)
            else:
                _execute_sample(writer, schedule.watch, previous_digests, plan)
            writer.save()
        _wait_until(start + total, clock, sleep)
        writer.manifest["status"] = "completed"
    except Exception as error:
        writer.manifest["status"] = "failed"
        writer.manifest["error_code"] = (
            error.code if isinstance(error, DataError) else "window_action_failed"
        )
        LOGGER.error(
            "phase=window status=failed code=%s", writer.manifest["error_code"]
        )
        raise DataError(str(writer.manifest["error_code"]), "window") from None
    finally:
        writer.manifest["ended_at"] = datetime.now(UTC).isoformat()
        writer.manifest["elapsed_sec"] = writer.offset()
        writer.save()


def read_window(evidence_dir: Path) -> WindowFacts:
    """Read bounded window evidence; incomplete status remains visible to callers.

    Missing, unsafe or invalid evidence raises DataError with a safe code.
    """
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        raise DataError("unsafe_file", "evidence")
    total_bytes = 0
    entries = 0
    for path in evidence_dir.rglob("*"):
        if path.is_symlink():
            raise DataError("unsafe_file", path.relative_to(evidence_dir).as_posix())
        entries += 1
        if entries > MAX_ENTRIES + MAX_SAMPLES * MAX_WATCH + MAX_ACTIONS * MAX_WATCH:
            raise DataError("too_large", "evidence")
        if path.is_file():
            size = path.stat().st_size
            if size > MAX_EVIDENCE_BYTES:
                raise DataError("too_large", path.relative_to(evidence_dir).as_posix())
            total_bytes += size
            if total_bytes > MAX_EVIDENCE_BYTES + MAX_MANIFEST_BYTES:
                raise DataError("too_large", "evidence")
        elif not path.is_dir():
            raise DataError("unsafe_file", path.relative_to(evidence_dir).as_posix())
    try:
        manifest = decode_json(
            read_bytes(
                evidence_dir / "manifest.json",
                "manifest.json",
                limit=MAX_MANIFEST_BYTES,
            ),
            "manifest.json",
        )
    except FileNotFoundError:
        raise DataError("missing", "manifest.json") from None
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "status",
            "started_at",
            "ended_at",
            "elapsed_sec",
            "error_code",
            "drops",
            "snapshots",
            "samples",
            "skipped",
            "skipped_truncated",
        }
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != SCHEMA_VERSION
    ):
        raise DataError("invalid_schema", "manifest.json")
    status = manifest["status"]
    if status not in ("not_started", "running", "completed", "failed"):
        raise DataError("invalid_schema", "manifest.json")
    if not _optional_str(manifest["started_at"]) or not _optional_str(
        manifest["ended_at"]
    ):
        raise DataError("invalid_schema", "manifest.json")
    if not _utc_time(manifest["started_at"]) or not _utc_time(manifest["ended_at"]):
        raise DataError("invalid_schema", "manifest.json")
    elapsed = manifest["elapsed_sec"]
    if elapsed is not None and not _nonnegative_number(elapsed):
        raise DataError("invalid_schema", "manifest.json")
    if not _optional_str(manifest["error_code"]):
        raise DataError("invalid_schema", "manifest.json")
    if status == "not_started":
        if (
            any(
                manifest[key] is not None
                for key in ("started_at", "ended_at", "elapsed_sec", "error_code")
            )
            or any(
                manifest[key] for key in ("drops", "snapshots", "samples", "skipped")
            )
            or manifest["skipped_truncated"]
        ):
            raise DataError("invalid_schema", "manifest.json")
    else:
        if not manifest["started_at"]:
            raise DataError("invalid_schema", "manifest.json")
        if status == "running":
            if any(
                manifest[key] is not None
                for key in ("ended_at", "elapsed_sec", "error_code")
            ):
                raise DataError("invalid_schema", "manifest.json")
        elif not manifest["ended_at"] or manifest["elapsed_sec"] is None:
            raise DataError("invalid_schema", "manifest.json")
        elif (status == "completed" and manifest["error_code"] is not None) or (
            status == "failed" and not manifest["error_code"]
        ):
            raise DataError("invalid_schema", "manifest.json")
    drops = _read_records(
        manifest["drops"],
        {"planned_offset_sec", "actual_offset_sec", "target", "sha256"},
        MAX_ACTIONS,
    )
    snapshots = _read_records(
        manifest["snapshots"],
        {
            "planned_offset_sec",
            "actual_offset_sec",
            "directory",
            "entries",
            "bytes",
            "truncated",
        },
        MAX_ACTIONS,
    )
    samples = _read_records(
        manifest["samples"], {"actual_offset_sec", "paths"}, MAX_SAMPLES
    )
    skipped = _read_records(manifest["skipped"], {"path", "kind"}, MAX_SKIPPED)
    if not isinstance(manifest["skipped_truncated"], bool):
        raise DataError("invalid_schema", "manifest.json")
    typed_drops: list[Drop] = []
    for drop in drops:
        if not (
            _nonnegative_number(drop["planned_offset_sec"])
            and _nonnegative_number(drop["actual_offset_sec"])
            and _absolute_path(drop["target"])
            and _digest(drop["sha256"])
        ):
            raise DataError("invalid_schema", "manifest.json")
        typed_drops.append(
            Drop(
                drop["planned_offset_sec"],
                drop["actual_offset_sec"],
                drop["target"],
                drop["sha256"],
            )
        )
    typed_snapshots: list[Snapshot] = []
    for snapshot in snapshots:
        directory = snapshot["directory"]
        if not (
            _nonnegative_number(snapshot["planned_offset_sec"])
            and _nonnegative_number(snapshot["actual_offset_sec"])
            and _relative_path(directory)
            and Path(directory).parts[0] == "snapshots"
            and type(snapshot["entries"]) is int
            and 0 <= snapshot["entries"] <= MAX_ENTRIES
            and type(snapshot["bytes"]) is int
            and 0 <= snapshot["bytes"] <= MAX_EVIDENCE_BYTES
            and isinstance(snapshot["truncated"], bool)
            and (evidence_dir / directory).is_dir()
        ):
            raise DataError("invalid_schema", "manifest.json")
        stored = evidence_dir / directory
        stored_files = [path for path in stored.rglob("*") if path.is_file()]
        if (
            len(stored_files) != snapshot["entries"]
            or sum(path.stat().st_size for path in stored_files) != snapshot["bytes"]
        ):
            raise DataError("invalid_schema", "manifest.json")
        typed_snapshots.append(
            Snapshot(
                snapshot["planned_offset_sec"],
                snapshot["actual_offset_sec"],
                directory,
                snapshot["entries"],
                snapshot["bytes"],
                snapshot["truncated"],
            )
        )
    typed_samples: list[Sample] = []
    for sample in samples:
        paths = sample["paths"]
        if (
            not _nonnegative_number(sample["actual_offset_sec"])
            or not isinstance(paths, dict)
            or len(paths) > MAX_WATCH
        ):
            raise DataError("invalid_schema", "manifest.json")
        checked_paths: dict[str, Observation] = {}
        for watched, observation in paths.items():
            if (
                not _absolute_path(watched)
                or not isinstance(observation, dict)
                or set(observation) != {"state", "sha256", "copy"}
                or observation["state"]
                not in (
                    "regular",
                    "directory",
                    "missing",
                    "symlink",
                    "special",
                    "truncated",
                )
                or (
                    observation["sha256"] is not None
                    and not _digest(observation["sha256"])
                )
                or (
                    observation["copy"] is not None
                    and (
                        not _relative_path(observation["copy"])
                        or Path(observation["copy"]).parts[0] != "samples"
                        or not (evidence_dir / observation["copy"]).exists()
                    )
                )
            ):
                raise DataError("invalid_schema", "manifest.json")
            checked_paths[watched] = observation
        typed_samples.append(Sample(sample["actual_offset_sec"], checked_paths))
    typed_skipped: list[Skipped] = []
    for entry in skipped:
        if not _absolute_path(entry["path"]) or entry["kind"] not in (
            "symlink",
            "special",
        ):
            raise DataError("invalid_schema", "manifest.json")
        typed_skipped.append(Skipped(entry["path"], entry["kind"]))
    return WindowFacts(
        cast(Literal["not_started", "running", "completed", "failed"], status),
        cast(str | None, manifest["started_at"]),
        cast(str | None, manifest["ended_at"]),
        cast(float | None, elapsed),
        tuple(typed_drops),
        tuple(typed_snapshots),
        tuple(typed_samples),
        tuple(typed_skipped),
        manifest["skipped_truncated"],
        cast(str | None, manifest["error_code"]),
    )


def _read_schedule(path: Path) -> _Schedule:
    """Validate the complete schedule before the first window action."""
    try:
        schedule = decode_json(
            read_bytes(path, "schedule.json", limit=MAX_SCHEDULE_BYTES), "schedule.json"
        )
    except FileNotFoundError:
        raise DataError("missing", "schedule.json") from None
    if not isinstance(schedule, dict) or set(schedule) != {
        "duration_sec",
        "tail_sec",
        "sample_interval_sec",
        "watch",
        "drops",
        "snapshots",
    }:
        raise DataError("invalid_schema", "schedule.json")
    duration = schedule["duration_sec"]
    tail = schedule["tail_sec"]
    interval = schedule["sample_interval_sec"]
    if not (
        _nonnegative_number(duration)
        and 0 < cast(float, duration) <= MAX_DURATION_SEC
        and _nonnegative_number(tail)
        and cast(float, tail) <= MAX_TAIL_SEC
        and _nonnegative_number(interval)
        and cast(float, interval) >= 1
        and int((cast(float, duration) + cast(float, tail)) // cast(float, interval))
        + 1
        <= MAX_SAMPLES
    ):
        raise DataError("invalid_schedule", "schedule.json")
    watch = schedule["watch"]
    drops = schedule["drops"]
    snapshots = schedule["snapshots"]
    if (
        not isinstance(watch, list)
        or len(watch) > MAX_WATCH
        or not all(_absolute_path(p) for p in watch)
        or not isinstance(drops, list)
        or len(drops) > MAX_ACTIONS
        or not isinstance(snapshots, list)
        or len(snapshots) > MAX_ACTIONS
    ):
        raise DataError("invalid_schedule", "schedule.json")
    planned_drops: list[_DropPlan] = []
    for drop in drops:
        if (
            not isinstance(drop, dict)
            or set(drop) != {"at_sec", "source", "target"}
            or not _nonnegative_number(drop["at_sec"])
            or cast(float, drop["at_sec"]) > cast(float, duration)
            or not _absolute_path(drop["source"])
            or not _absolute_path(drop["target"])
        ):
            raise DataError("invalid_schedule", "schedule.json")
        planned_drops.append(
            _DropPlan(
                cast(float, drop["at_sec"]),
                Path(cast(str, drop["source"])),
                Path(cast(str, drop["target"])),
            )
        )
    planned_snapshots: list[_SnapshotPlan] = []
    for snapshot in snapshots:
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {"at_sec", "paths"}
            or not _nonnegative_number(snapshot["at_sec"])
            or cast(float, snapshot["at_sec"]) > cast(float, duration)
            or not isinstance(snapshot["paths"], list)
            or len(snapshot["paths"]) > MAX_WATCH
            or not all(_absolute_path(p) for p in snapshot["paths"])
        ):
            raise DataError("invalid_schedule", "schedule.json")
        planned_snapshots.append(
            _SnapshotPlan(
                cast(float, snapshot["at_sec"]),
                tuple(Path(cast(str, p)) for p in snapshot["paths"]),
            )
        )
    return _Schedule(
        cast(float, duration),
        cast(float, tail),
        cast(float, interval),
        tuple(Path(cast(str, p)) for p in watch),
        tuple(planned_drops),
        tuple(planned_snapshots),
    )


def _wait_until(
    deadline: float, clock: Callable[[], float], sleep: Callable[[float], None]
) -> None:
    """Sleep in short increments until an absolute monotonic deadline."""
    while clock() < deadline:
        sleep(min(0.1, deadline - clock()))


def _execute_drop(writer: _EvidenceWriter, item: object) -> None:
    _, plan = cast(tuple[int, _DropPlan], item)
    if (
        _has_symlink_component(plan.source)
        or not plan.source.is_file()
        or _has_symlink_component(plan.target)
    ):
        raise DataError("unsafe_file", "drop")
    content = read_bytes(plan.source, "drop", limit=MAX_EVIDENCE_BYTES)
    plan.target.parent.mkdir(parents=True, exist_ok=True)
    with plan.target.open("wb") as stream:
        stream.write(content)
    writer.manifest["drops"].append(
        {
            "planned_offset_sec": plan.at_sec,
            "actual_offset_sec": writer.offset(),
            "target": str(plan.target),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    )


def _execute_snapshot(writer: _EvidenceWriter, item: object) -> None:
    index, plan = cast(tuple[int, _SnapshotPlan], item)
    writer.observed = _CopyBudget()
    directory = f"snapshots/{index:03d}"
    destination = writer.root / directory
    destination.mkdir(parents=True)
    count = 0
    byte_count = 0
    truncated = False
    for path_index, path in enumerate(plan.paths):
        entries, size, cut, _ = writer.copy_path(
            path, destination / f"{path_index:02d}-{path.name}"
        )
        count += entries
        byte_count += size
        truncated |= cut
    writer.manifest["snapshots"].append(
        {
            "planned_offset_sec": plan.at_sec,
            "actual_offset_sec": writer.offset(),
            "directory": directory,
            "entries": count,
            "bytes": byte_count,
            "truncated": truncated,
        }
    )


def _execute_sample(
    writer: _EvidenceWriter,
    watch: tuple[Path, ...],
    previous: dict[str, str],
    index: object,
) -> None:
    index = cast(int, index)
    writer.observed = _CopyBudget()
    paths: dict[str, Observation] = {}
    for path_index, path in enumerate(watch):
        destination = writer.root / f"samples/{index:04d}/{path_index:02d}-{path.name}"
        if _has_symlink_component(path):
            writer.record_skip(path, "symlink")
            previous.pop(str(path), None)
            state, digest, copied = "symlink", None, None
        elif not path.exists():
            previous.pop(str(path), None)
            state, digest, copied = "missing", None, None
        else:
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
                writer.record_skip(path, "special")
                previous.pop(str(path), None)
                state, digest, copied = "special", None, None
            else:
                _, size, truncated, digest = writer.copy_path(path, destination)
                state = "directory" if stat.S_ISDIR(mode) else "regular"
                if previous.get(str(path)) == digest:
                    writer.storage.entries -= _remove_copy(destination)
                    writer.storage.bytes -= size
                    copied = None
                else:
                    if truncated:
                        state = "truncated"
                    copied = (
                        destination.relative_to(writer.root).as_posix()
                        if destination.exists()
                        else None
                    )
                if _digest(digest):
                    previous[str(path)] = digest
                else:
                    previous.pop(str(path), None)
                    digest = None
        paths[str(path)] = {"state": state, "sha256": digest, "copy": copied}
    writer.manifest["samples"].append(
        {"actual_offset_sec": writer.offset(), "paths": paths}
    )


def _remove_copy(path: Path) -> int:
    """Remove a temporary observation and return its stored file/directory count."""
    if path.is_file():
        path.unlink()
        return 1
    if path.is_dir():
        entries = 1
        for child in path.iterdir():
            entries += _remove_copy(child)
        path.rmdir()
        return entries
    return 0


def _read_records(value: object, keys: set[str], limit: int) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(item, dict) or set(item) != keys for item in value)
    ):
        raise DataError("invalid_schema", "manifest.json")
    return cast(list[dict[str, Any]], value)


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _absolute_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_PATH_LENGTH
        and value.startswith("/")
        and ".." not in Path(value).parts
        and "\x00" not in value
    )


def _has_symlink_component(path: Path) -> bool:
    """Reject links in the path itself or any existing parent."""
    return any(part.is_symlink() for part in (path, *path.parents))


def _relative_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and bool(Path(value).parts)
        and not Path(value).is_absolute()
        and ".." not in Path(value).parts
    )


def _optional_str(value: object) -> bool:
    return value is None or isinstance(value, str)


def _utc_time(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        return False
    offset = observed.utcoffset()
    return offset is not None and offset.total_seconds() == 0


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


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
    except DataError as error:
        sys.stderr.write(f"window: {error.code}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
