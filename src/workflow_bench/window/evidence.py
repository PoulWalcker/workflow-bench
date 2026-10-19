"""Window evidence records and validation of candidate-reachable copies."""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from workflow_bench.data import DataError, decode_json, read_bytes
from workflow_bench.window.common import (
    MAX_ACTIONS,
    MAX_ENTRIES,
    MAX_EVIDENCE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_SAMPLES,
    MAX_SKIPPED,
    MAX_WATCH,
    SCHEMA_VERSION,
    _absolute_path,
    _digest,
    _nonnegative_number,
    _optional_str,
    _relative_path,
    _utc_time,
)


class Observation(TypedDict):
    """Validated state, digest, and optional stored copy of one watched path."""

    state: str
    sha256: str | None
    copy: str | None


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
        != {"schema_version", *(field.name for field in fields(WindowFacts))}
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != SCHEMA_VERSION
    ):
        raise DataError("invalid_schema", "manifest.json")
    status = manifest["status"]
    if status not in ("not_started", "running", "completed", "failed"):
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
    drops = _read_records(manifest["drops"], Drop, MAX_ACTIONS)
    snapshots = _read_records(manifest["snapshots"], Snapshot, MAX_ACTIONS)
    samples = _read_records(manifest["samples"], Sample, MAX_SAMPLES)
    skipped = _read_records(manifest["skipped"], Skipped, MAX_SKIPPED)
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
        typed_drops.append(Drop(**drop))
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
        typed_snapshots.append(Snapshot(**snapshot))
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
        typed_samples.append(
            Sample(actual_offset_sec=sample["actual_offset_sec"], paths=checked_paths)
        )
    typed_skipped: list[Skipped] = []
    for entry in skipped:
        if not _absolute_path(entry["path"]) or entry["kind"] not in (
            "symlink",
            "special",
        ):
            raise DataError("invalid_schema", "manifest.json")
        typed_skipped.append(Skipped(**entry))
    checked: dict[str, Any] = dict(manifest)
    del checked["schema_version"]
    checked.update(
        drops=tuple(typed_drops),
        snapshots=tuple(typed_snapshots),
        samples=tuple(typed_samples),
        skipped=tuple(typed_skipped),
    )
    return WindowFacts(**checked)


def _read_records(
    value: object, record: type[Drop | Snapshot | Sample | Skipped], limit: int
) -> list[dict[str, Any]]:
    keys = {field.name for field in fields(record)}
    if (
        not isinstance(value, list)
        or len(value) > limit
        or any(not isinstance(item, dict) or set(item) != keys for item in value)
    ):
        raise DataError("invalid_schema", "manifest.json")
    return cast(list[dict[str, Any]], value)
