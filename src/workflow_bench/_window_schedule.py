"""Validate task-owned observation schedules before any action."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from workflow_bench._window_common import (
    MAX_ACTIONS,
    MAX_DURATION_SEC,
    MAX_SAMPLES,
    MAX_SCHEDULE_BYTES,
    MAX_TAIL_SEC,
    MAX_WATCH,
    _absolute_path,
    _nonnegative_number,
)
from workflow_bench.data import DataError, decode_json, read_bytes


@dataclass(frozen=True)
class DropPlan:
    """One bounded input delivery at a planned offset in seconds."""

    at_sec: float
    source: Path
    target: Path


@dataclass(frozen=True)
class SnapshotPlan:
    """Paths to snapshot at one planned offset in seconds."""

    at_sec: float
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class Schedule:
    """Validated plan with ordered sample offsets through duration plus tail."""

    duration_sec: float
    tail_sec: float
    sample_offsets_sec: tuple[float, ...]
    watch: tuple[Path, ...]
    drops: tuple[DropPlan, ...]
    snapshots: tuple[SnapshotPlan, ...]


def read_schedule(path: Path) -> Schedule:
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
    ):
        raise DataError("invalid_schedule", "schedule.json")
    sample_offsets: list[float] = []
    for index in range(MAX_SAMPLES + 1):
        offset = index * cast(float, interval)
        if offset > cast(float, duration) + cast(float, tail):
            break
        sample_offsets.append(offset)
    if len(sample_offsets) > MAX_SAMPLES:
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
    planned_drops: list[DropPlan] = []
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
            DropPlan(
                cast(float, drop["at_sec"]),
                Path(cast(str, drop["source"])),
                Path(cast(str, drop["target"])),
            )
        )
    planned_snapshots: list[SnapshotPlan] = []
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
            SnapshotPlan(
                cast(float, snapshot["at_sec"]),
                tuple(Path(cast(str, p)) for p in snapshot["paths"]),
            )
        )
    return Schedule(
        cast(float, duration),
        cast(float, tail),
        tuple(sample_offsets),
        tuple(dict.fromkeys(Path(cast(str, p)) for p in watch)),
        tuple(planned_drops),
        tuple(planned_snapshots),
    )
