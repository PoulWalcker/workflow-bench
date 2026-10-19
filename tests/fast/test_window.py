"""Observation-window timing and evidence through the public driver and reader."""

import json
import math
import os
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import workflow_bench._window_copy as window_copy
from workflow_bench.data import DataError
from workflow_bench.window import read_window, run_window


class FakeClock:
    """Advance monotonic time when the driver sleeps."""

    def __init__(self) -> None:
        self.elapsed = 0.0

    def now(self) -> float:
        """Return elapsed test seconds."""
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        """Advance by the requested interval."""
        self.elapsed += seconds


def test_snapshot_precedes_drop_and_finishes_after_tail(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("new")
    schedule = tmp_path / "schedule.json"
    schedule.write_text(
        json.dumps(
            {
                "duration_sec": 2,
                "tail_sec": 1,
                "sample_interval_sec": 1,
                "watch": [str(inbox)],
                "drops": [
                    {"at_sec": 1, "source": str(source), "target": str(inbox / "x.txt")}
                ],
                "snapshots": [{"at_sec": 1, "paths": [str(inbox)]}],
            }
        )
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"

    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)

    assert facts.status == "completed"
    assert clock.elapsed == 3
    assert len(facts.snapshots) == 1
    assert facts.snapshots[0].actual_offset_sec == 1
    assert facts.drops[0].actual_offset_sec == 1
    assert (inbox / "x.txt").read_text() == "new"
    assert not list((evidence / facts.snapshots[0].directory).rglob("x.txt"))


def _schedule(path: Path, **updates: object) -> Path:
    schedule: dict[str, object] = {
        "duration_sec": 2,
        "tail_sec": 1,
        "sample_interval_sec": 1,
        "watch": [],
        "drops": [],
        "snapshots": [],
    }
    schedule.update(updates)
    path.write_text(json.dumps(schedule))
    return path


def test_changed_watch_is_copied_once_per_change(tmp_path: Path) -> None:
    watched = tmp_path / "status.log"
    watched.write_text("first\n")
    schedule = _schedule(tmp_path / "schedule.json", watch=[str(watched)])
    clock = FakeClock()

    def advance(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.elapsed >= 1 and watched.read_text() == "first\n":
            watched.write_text("first\nsecond\n")

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    samples = read_window(evidence).samples
    observations = [sample.paths[str(watched)] for sample in samples]
    assert [item["copy"] is not None for item in observations] == [
        True,
        True,
        False,
        False,
    ]
    assert (evidence / str(observations[1]["copy"])).read_text() == "first\nsecond\n"


def test_fractional_endpoint_records_change_after_snapshot_and_drop(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "watched"
    watched.write_text("old")
    source = tmp_path / "source"
    source.write_text("new")
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=11,
        tail_sec=0,
        sample_interval_sec=1.1,
        watch=[str(watched)],
        drops=[{"at_sec": 11, "source": str(source), "target": str(watched)}],
        snapshots=[{"at_sec": 11, "paths": [str(watched)]}],
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert facts.status == "completed"
    assert facts.elapsed_sec == clock.elapsed == 11
    assert len(facts.samples) == 11
    assert facts.samples[-1].actual_offset_sec == 11
    assert (
        facts.drops[0].actual_offset_sec == facts.snapshots[0].actual_offset_sec == 11
    )
    assert (evidence / facts.snapshots[0].directory / "00-watched").read_text() == "old"
    observations = [sample.paths[str(watched)] for sample in facts.samples]
    assert [item["copy"] is not None for item in observations] == [
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
    ]
    assert observations[0]["sha256"] != observations[-1]["sha256"]
    stored = observations[-1]["copy"]
    assert stored is not None
    assert (evidence / stored).read_text() == "new"


@pytest.mark.parametrize(
    ("interval", "endpoint"), [(1.1, 11.0), (1.3, 13.0), (2.2, 22.0), (1.25, 12.5)]
)
@pytest.mark.parametrize("boundary", ["before", "exact", "after"])
@pytest.mark.parametrize("tail", [0.0, 1.0])
def test_fractional_samples_respect_horizon_and_tail(
    tmp_path: Path, interval: float, endpoint: float, boundary: str, tail: float
) -> None:
    horizon = endpoint
    if boundary == "before":
        horizon = math.nextafter(endpoint, -math.inf)
    elif boundary == "after":
        horizon = math.nextafter(endpoint, math.inf)
    watched = tmp_path / "watched"
    watched.write_text("old")
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=horizon - tail,
        tail_sec=tail,
        sample_interval_sec=interval,
        watch=[str(watched)],
    )
    clock = FakeClock()

    def advance(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.elapsed >= endpoint:
            watched.write_text("new")

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    facts = read_window(evidence)
    assert facts.status == "completed"
    assert facts.elapsed_sec == clock.elapsed == horizon
    assert len(facts.samples) == (10 if boundary == "before" else 11)
    assert all(sample.actual_offset_sec <= horizon for sample in facts.samples)
    observations = [sample.paths[str(watched)] for sample in facts.samples]
    assert sum(item["copy"] is not None for item in observations) == (
        1 if boundary == "before" else 2
    )
    if boundary != "before":
        assert facts.samples[-1].actual_offset_sec == endpoint
        stored = observations[-1]["copy"]
        assert stored is not None
        assert (evidence / stored).read_text() == "new"


@pytest.mark.parametrize("interval", [1.0, 1.1, 1.3, 2.2])
@pytest.mark.parametrize("boundary", ["before", "exact", "after"])
@pytest.mark.parametrize("tail", [0.0, 1.0])
def test_sample_limit_uses_the_executed_fractional_offsets(
    tmp_path: Path, interval: float, boundary: str, tail: float
) -> None:
    horizon = 128 * interval
    if boundary == "before":
        horizon = math.nextafter(horizon, -math.inf)
    elif boundary == "after":
        horizon = math.nextafter(horizon, math.inf)
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=horizon - tail,
        tail_sec=tail,
        sample_interval_sec=interval,
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    if boundary != "before":
        with pytest.raises(DataError, match="invalid_schedule"):
            run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
        assert not evidence.exists()
        assert clock.elapsed == 0
        return
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert facts.status == "completed"
    assert len(facts.samples) == 128
    assert facts.samples[-1].actual_offset_sec == 127 * interval
    assert facts.elapsed_sec == clock.elapsed == horizon


@pytest.mark.parametrize("duplicate_count", [2, 32])
@pytest.mark.parametrize("dotted_path", [False, True])
def test_duplicate_watch_preserves_first_seen_copies(
    tmp_path: Path, duplicate_count: int, dotted_path: bool
) -> None:
    watched = tmp_path / "status.log"
    watched.write_text("first\n")
    repeated = f"{tmp_path}/./status.log" if dotted_path else str(watched)
    schedule = _schedule(
        tmp_path / "schedule.json",
        watch=[str(watched)] + [repeated] * (duplicate_count - 1),
    )
    clock = FakeClock()

    def advance(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.elapsed >= 1:
            watched.write_text("first\nsecond\n")

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    facts = read_window(evidence)
    assert facts.status == "completed"
    assert [sample.actual_offset_sec for sample in facts.samples] == [0, 1, 2, 3]
    assert all(list(sample.paths) == [str(watched)] for sample in facts.samples)
    observations = [sample.paths[str(watched)] for sample in facts.samples]
    assert [item["copy"] is not None for item in observations] == [
        True,
        True,
        False,
        False,
    ]
    assert observations[0]["sha256"] != observations[1]["sha256"]
    assert (
        observations[1]["sha256"]
        == observations[2]["sha256"]
        == observations[3]["sha256"]
    )
    for observation, content in zip(
        observations[:2], ["first\n", "first\nsecond\n"], strict=True
    ):
        assert observation["copy"] is not None
        assert (evidence / observation["copy"]).read_text() == content
    stored_files = [
        path for path in (evidence / "samples").rglob("*") if path.is_file()
    ]
    assert len(stored_files) == 2


def test_unchanged_large_watch_preserves_capacity_for_late_change(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "large.bin"
    watched.write_bytes(b"x" * (20 * 1024 * 1024))
    schedule = _schedule(
        tmp_path / "schedule.json", duration_sec=3, tail_sec=0, watch=[str(watched)]
    )
    clock = FakeClock()
    changed = False

    def advance(seconds: float) -> None:
        nonlocal changed
        clock.sleep(seconds)
        if clock.elapsed >= 2 and not changed:
            watched.write_bytes(b"late change\n")
            changed = True

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    facts = read_window(evidence)
    observations = [sample.paths[str(watched)] for sample in facts.samples]

    assert facts.status == "completed"
    assert [item["copy"] is not None for item in observations] == [
        True,
        False,
        True,
        False,
    ]
    assert [item["state"] for item in observations] == ["regular"] * 4
    assert observations[0]["sha256"] == observations[1]["sha256"]
    assert observations[2]["sha256"] == observations[3]["sha256"]
    assert facts.samples[2].actual_offset_sec == 2
    assert observations[0]["copy"] is not None
    assert (evidence / observations[0]["copy"]).read_bytes() == b"x" * (
        20 * 1024 * 1024
    )
    assert observations[2]["copy"] is not None
    assert (evidence / observations[2]["copy"]).read_bytes() == b"late change\n"
    assert (
        sum(
            path.stat().st_size
            for path in (evidence / "samples").rglob("*")
            if path.is_file()
        )
        == 20971532
    )


@pytest.mark.parametrize("entry_kind", ["file", "directory"])
def test_unchanged_directory_preserves_entries_for_late_change(
    tmp_path: Path, entry_kind: str
) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    for index in range(2050):
        child = watched / f"{index:04d}"
        if entry_kind == "directory":
            child.mkdir()
        else:
            child.touch()
    schedule = _schedule(
        tmp_path / "schedule.json", duration_sec=3, tail_sec=0, watch=[str(watched)]
    )
    clock = FakeClock()
    changed = False

    def advance(seconds: float) -> None:
        nonlocal changed
        clock.sleep(seconds)
        if clock.elapsed >= 2 and not changed:
            for child in watched.iterdir():
                if entry_kind == "directory":
                    child.rmdir()
                else:
                    child.unlink()
            (watched / "late.txt").write_text("late")
            changed = True

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    facts = read_window(evidence)
    observations = [sample.paths[str(watched)] for sample in facts.samples]

    assert facts.status == "completed"
    assert [item["copy"] is not None for item in observations] == [
        True,
        False,
        True,
        False,
    ]
    assert [item["state"] for item in observations] == ["directory"] * 4
    assert observations[0]["sha256"] == observations[1]["sha256"]
    assert observations[2]["sha256"] == observations[3]["sha256"]
    assert facts.samples[2].actual_offset_sec == 2
    assert observations[0]["copy"] is not None
    assert len(list((evidence / observations[0]["copy"]).iterdir())) == 2050
    assert observations[2]["copy"] is not None
    assert (evidence / observations[2]["copy"] / "late.txt").read_text() == "late"
    assert (
        sum(1 for sample in (evidence / "samples").iterdir() for _ in sample.rglob("*"))
        == 2053
    )


@pytest.mark.parametrize("initial_kind", ["file", "directory"])
@pytest.mark.parametrize("nested", [True, False], ids=["nested", "root"])
def test_entry_kind_change_is_copied_at_first_seen_sample(
    tmp_path: Path, initial_kind: str, nested: bool
) -> None:
    watched = tmp_path / "watched"
    if nested:
        watched.mkdir()
    entry = watched / "row" if nested else watched
    if initial_kind == "file":
        entry.touch()
    else:
        entry.mkdir()
    schedule = _schedule(
        tmp_path / "schedule.json", duration_sec=4, tail_sec=0, watch=[str(watched)]
    )
    clock = FakeClock()
    changed = False

    def advance(seconds: float) -> None:
        nonlocal changed
        clock.sleep(seconds)
        if clock.elapsed >= 2 and not changed:
            if initial_kind == "file":
                entry.unlink()
                entry.mkdir()
            else:
                entry.rmdir()
                entry.touch()
            changed = True

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    facts = read_window(evidence)
    observations = [sample.paths[str(watched)] for sample in facts.samples]

    assert facts.status == "completed"
    assert [sample.actual_offset_sec for sample in facts.samples] == [0, 1, 2, 3, 4]
    assert [item["copy"] is not None for item in observations] == [
        True,
        False,
        True,
        False,
        False,
    ]
    assert observations[0]["sha256"] == observations[1]["sha256"]
    assert (
        observations[2]["sha256"]
        == observations[3]["sha256"]
        == observations[4]["sha256"]
    )
    if nested:
        assert [item["state"] for item in observations] == ["directory"] * 5
        assert observations[0]["sha256"] != observations[2]["sha256"]
    else:
        initial_state = "regular" if initial_kind == "file" else "directory"
        changed_state = "directory" if initial_kind == "file" else "regular"
        assert [item["state"] for item in observations] == [initial_state] * 2 + [
            changed_state
        ] * 3
    for index in (0, 2):
        copy = observations[index]["copy"]
        assert copy is not None
        stored = evidence / copy
        if nested:
            stored /= "row"
        is_file = (initial_kind == "file") == (index == 0)
        assert stored.is_file() == is_file
        assert stored.is_dir() != is_file
        if is_file:
            assert stored.read_bytes() == b""
        else:
            assert list(stored.iterdir()) == []
    assert sum(
        1 for sample in (evidence / "samples").iterdir() for _ in sample.rglob("*")
    ) == (4 if nested else 2)


def test_reappearing_watch_is_copied_even_with_same_bytes(tmp_path: Path) -> None:
    watched = tmp_path / "status.log"
    watched.write_text("same\n")
    schedule = _schedule(tmp_path / "schedule.json", watch=[str(watched)])
    clock = FakeClock()
    stage = 0

    def advance(seconds: float) -> None:
        nonlocal stage
        clock.sleep(seconds)
        if clock.elapsed >= 1 and stage == 0:
            watched.unlink()
            stage = 1
        if clock.elapsed >= 2 and stage == 1:
            watched.write_text("same\n")
            stage = 2

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    observations = [
        sample.paths[str(watched)] for sample in read_window(evidence).samples
    ]
    assert [item["copy"] is not None for item in observations] == [
        True,
        False,
        True,
        False,
    ]


@pytest.mark.parametrize("change_at", [125, 127])
@pytest.mark.parametrize("tail_sec", [0, 2])
def test_late_change_in_unchanged_directory_is_copied(
    tmp_path: Path, change_at: int, tail_sec: int
) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    for index in range(33):
        (watched / f"{index:02d}.txt").write_text("original")
    changed = watched / "00.txt"
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=127 - tail_sec,
        tail_sec=tail_sec,
        sample_interval_sec=1,
        watch=[str(watched)],
    )
    clock = FakeClock()

    def advance(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.elapsed >= change_at and changed.read_text() == "original":
            changed.write_text("late change")

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    facts = read_window(evidence)
    late = facts.samples[change_at].paths[str(watched)]

    assert facts.status == "completed"
    assert len(facts.samples) == 128
    assert facts.samples[change_at].actual_offset_sec == change_at
    assert all(
        sample.paths[str(watched)]["copy"] is None
        for sample in facts.samples[1:change_at]
    )
    assert len(list((evidence / "samples").rglob("*.txt"))) == 66
    assert late["state"] == "directory"
    assert late["copy"] is not None
    assert (evidence / late["copy"] / changed.name).read_text() == "late change"


def test_late_snapshot_has_its_own_scan_budget(tmp_path: Path) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    for index in range(33):
        (watched / f"{index:02d}.txt").write_text("original")
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=127,
        tail_sec=0,
        sample_interval_sec=1,
        watch=[str(watched)],
        snapshots=[{"at_sec": 127, "paths": [str(watched)]}],
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"

    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)

    assert facts.status == "completed"
    assert facts.snapshots[0].entries == 33
    assert not facts.snapshots[0].truncated
    assert len(list((evidence / facts.snapshots[0].directory).rglob("*.txt"))) == 33


def test_changed_empty_directories_keep_aggregate_entry_bound(tmp_path: Path) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    for index in range(129):
        (watched / f"{index:03d}").mkdir()
    changing = watched / "000"
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=127,
        tail_sec=0,
        sample_interval_sec=1,
        watch=[str(watched)],
    )
    clock = FakeClock()
    generation = 0

    def advance(seconds: float) -> None:
        nonlocal generation, changing
        clock.sleep(seconds)
        if int(clock.elapsed) > generation:
            generation = int(clock.elapsed)
            replacement = watched / f"generation-{generation}"
            changing.rename(replacement)
            changing = replacement

    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    copies = evidence / "samples"
    stored = [path for sample in copies.iterdir() for path in sample.rglob("*")]

    assert len(stored) <= 4096
    facts = read_window(evidence)
    assert facts.status == "completed"
    assert any(
        sample.paths[str(watched)]["state"] == "truncated" for sample in facts.samples
    )


def test_oversized_snapshot_is_marked_truncated(tmp_path: Path) -> None:
    large = tmp_path / "large.bin"
    with large.open("wb") as stream:
        stream.truncate(33 * 1024 * 1024)
    schedule = _schedule(
        tmp_path / "schedule.json",
        snapshots=[{"at_sec": 1, "paths": [str(large)]}],
    )
    evidence = tmp_path / "evidence"
    clock = FakeClock()
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    snapshot = read_window(evidence).snapshots[0]
    assert snapshot.truncated is True
    assert snapshot.bytes == 32 * 1024 * 1024


def test_symlinked_watch_is_recorded_without_copy(tmp_path: Path) -> None:
    target = tmp_path / "secret"
    target.write_text("do not follow")
    watched = tmp_path / "watched"
    watched.symlink_to(target)
    schedule = _schedule(tmp_path / "schedule.json", watch=[str(watched)])
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert all(
        sample.paths[str(watched)] == {"state": "symlink", "sha256": None, "copy": None}
        for sample in facts.samples
    )
    assert all(
        item.path == str(watched) and item.kind == "symlink" for item in facts.skipped
    )


def test_snapshot_records_nested_symlink_without_copy(tmp_path: Path) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private")
    (watched / "link").symlink_to(outside)
    schedule = _schedule(
        tmp_path / "schedule.json",
        snapshots=[{"at_sec": 1, "paths": [str(watched)]}],
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert [(item.path, item.kind) for item in facts.skipped] == [
        (str(watched / "link"), "symlink")
    ]
    assert not list((evidence / facts.snapshots[0].directory).rglob("link"))


def test_watch_under_symlinked_parent_is_not_followed(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "value").write_text("private")
    linked = tmp_path / "linked"
    linked.symlink_to(actual)
    watched = linked / "value"
    schedule = _schedule(tmp_path / "schedule.json", watch=[str(watched)])
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    assert all(
        sample.paths[str(watched)]["state"] == "symlink"
        and sample.paths[str(watched)]["copy"] is None
        for sample in read_window(evidence).samples
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"drops": [{"at_sec": -1, "source": "/a", "target": "/b"}]},
        {"unknown": 1},
        {"watch": [f"/tmp/watch-{index}" for index in range(33)]},
        {"duration_sec": 10**1000},
        {"tail_sec": 10**1000},
        {"sample_interval_sec": 10**1000},
        {"drops": [{"at_sec": 10**1000, "source": "/a", "target": "/b"}]},
        {"snapshots": [{"at_sec": 10**1000, "paths": ["/a"]}]},
    ],
)
def test_invalid_schedule_has_no_effect(
    tmp_path: Path, updates: dict[str, object]
) -> None:
    schedule = _schedule(tmp_path / "schedule.json", **updates)
    evidence = tmp_path / "evidence"
    clock = FakeClock()
    with pytest.raises(DataError):
        run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    assert not evidence.exists()
    assert clock.elapsed == 0


def test_runtime_failure_keeps_earlier_actions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_text("first")
    schedule = _schedule(
        tmp_path / "schedule.json",
        drops=[
            {"at_sec": 1, "source": str(source), "target": str(tmp_path / "first")},
            {
                "at_sec": 2,
                "source": str(tmp_path / "missing"),
                "target": str(tmp_path / "second"),
            },
        ],
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    with pytest.raises(DataError):
        run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert facts.status == "failed"
    assert facts.error_code == "unsafe_file"
    assert [drop.target for drop in facts.drops] == [str(tmp_path / "first")]


def test_fifo_drop_fails_without_blocking_and_keeps_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_text("first")
    delivered = tmp_path / "delivered"
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    evidence = tmp_path / "evidence"
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=0.2,
        tail_sec=0,
        watch=[str(source)],
        drops=[
            {"at_sec": 0, "source": str(source), "target": str(delivered)},
            {"at_sec": 0.1, "source": str(source), "target": str(fifo)},
        ],
        snapshots=[{"at_sec": 0, "paths": [str(source)]}],
    )
    with subprocess.Popen(
        [sys.executable, "-m", "workflow_bench.window", str(schedule), str(evidence)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=3)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            assert process.poll() is not None
    assert process.returncode == 1
    assert stdout == b""
    assert b"unsafe_file" in stderr
    assert b"Traceback" not in stderr
    facts = read_window(evidence)
    assert facts.status == "failed"
    assert facts.error_code == "unsafe_file"
    assert [drop.target for drop in facts.drops] == [str(delivered)]
    assert delivered.read_text() == "first"
    assert len(facts.snapshots) == len(facts.samples) == 1
    snapshot = evidence / facts.snapshots[0].directory / "00-source"
    assert snapshot.read_text() == "first"
    stored = facts.samples[0].paths[str(source)]["copy"]
    assert stored is not None
    assert (evidence / stored).read_text() == "first"


@pytest.mark.parametrize("kind", ["directory", "socket", "character"])
def test_nonregular_drop_target_fails_safely(tmp_path: Path, kind: str) -> None:
    source = tmp_path / "source"
    source.write_text("input")
    evidence = tmp_path / "evidence"
    with tempfile.TemporaryDirectory(prefix="wb-target-", dir="/tmp") as directory:
        target = Path(directory).resolve() / "target"
        with socket.socket(socket.AF_UNIX) as listener:
            if kind == "directory":
                target.mkdir()
            elif kind == "socket":
                listener.bind(str(target))
            else:
                target = Path(os.devnull)
            schedule = _schedule(
                tmp_path / "schedule.json",
                drops=[{"at_sec": 1, "source": str(source), "target": str(target)}],
            )
            clock = FakeClock()
            with pytest.raises(DataError, match="unsafe_file"):
                run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
            facts = read_window(evidence)
            assert facts.status == "failed"
            assert facts.error_code == "unsafe_file"
            assert not facts.drops
            assert facts.elapsed_sec == 1
            assert target.exists()


def test_reader_rejects_missing_invalid_and_unsafe_manifest(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    with pytest.raises(DataError, match="missing"):
        read_window(evidence)
    manifest = evidence / "manifest.json"
    manifest.write_text("{invalid")
    with pytest.raises(DataError, match="invalid_schema"):
        read_window(evidence)
    manifest.unlink()
    manifest.symlink_to(tmp_path / "outside")
    with pytest.raises(DataError, match="unsafe_file"):
        read_window(evidence)


def test_reader_reports_incomplete_and_rejects_oversized_file(tmp_path: Path) -> None:
    schedule = _schedule(tmp_path / "schedule.json")
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    manifest = evidence / "manifest.json"
    record = json.loads(manifest.read_text())
    started_at = record["started_at"]
    for status in ("not_started", "running"):
        record["status"] = status
        record["started_at"] = None if status == "not_started" else started_at
        record["ended_at"] = None
        record["elapsed_sec"] = None
        if status == "not_started":
            record["samples"] = []
        manifest.write_text(json.dumps(record))
        assert read_window(evidence).status == status
    with (evidence / "huge").open("wb") as stream:
        stream.truncate(33 * 1024 * 1024)
    with pytest.raises(DataError, match="too_large"):
        read_window(evidence)


def test_reader_rejects_completed_manifest_without_completion_facts(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed",
                "started_at": None,
                "ended_at": None,
                "elapsed_sec": None,
                "error_code": None,
                "drops": [],
                "snapshots": [],
                "samples": [],
                "skipped": [],
                "skipped_truncated": False,
            }
        )
    )
    with pytest.raises(DataError, match="invalid_schema"):
        read_window(evidence)


def test_driver_does_not_follow_a_planted_manifest_temp_link(tmp_path: Path) -> None:
    schedule = _schedule(tmp_path / "schedule.json")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("protected")
    (evidence / "manifest.tmp").symlink_to(outside)
    clock = FakeClock()
    with pytest.raises(DataError, match="unsafe_file"):
        run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    assert outside.read_text() == "protected"


def test_reader_rejects_wrong_snapshot_size_and_non_utc_time(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_text("one")
    schedule = _schedule(
        tmp_path / "schedule.json",
        snapshots=[{"at_sec": 1, "paths": [str(source)]}],
    )
    evidence = tmp_path / "evidence"
    clock = FakeClock()
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    manifest = evidence / "manifest.json"
    record = json.loads(manifest.read_text())
    record["snapshots"][0]["bytes"] = 2
    manifest.write_text(json.dumps(record))
    with pytest.raises(DataError, match="invalid_schema"):
        read_window(evidence)
    record["snapshots"][0]["bytes"] = 3
    record["started_at"] = "2026-10-14T12:00:00+04:00"
    manifest.write_text(json.dumps(record))
    with pytest.raises(DataError, match="invalid_schema"):
        read_window(evidence)


@pytest.mark.parametrize(
    "number", [10**1000, -(10**1000)], ids=["positive", "negative"]
)
@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("", "elapsed_sec"),
        ("drops", "planned_offset_sec"),
        ("drops", "actual_offset_sec"),
        ("snapshots", "planned_offset_sec"),
        ("snapshots", "actual_offset_sec"),
        ("samples", "actual_offset_sec"),
    ],
)
def test_reader_rejects_unrepresentable_json_times(
    tmp_path: Path, section: str, field: str, number: int
) -> None:
    source = tmp_path / "source"
    source.write_text("input")
    schedule = _schedule(
        tmp_path / "schedule.json",
        drops=[
            {"at_sec": 0, "source": str(source), "target": str(tmp_path / "target")}
        ],
        snapshots=[{"at_sec": 0, "paths": [str(source)]}],
    )
    evidence = tmp_path / "evidence"
    clock = FakeClock()
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    assert read_window(evidence).status == "completed"
    manifest = evidence / "manifest.json"
    record = json.loads(manifest.read_text())
    if section:
        record[section][0][field] = number
    else:
        record[field] = number
    manifest.write_text(json.dumps(record))

    with pytest.raises(DataError, match="invalid_schema: manifest.json"):
        read_window(evidence)


@pytest.mark.parametrize("replacement", ["missing", "directory"])
def test_scan_race_keeps_only_content_actually_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    child = watched / "changing.txt"
    child.write_text("before")
    original_iterdir = Path.iterdir
    changed = False

    def list_then_change(path: Path) -> Iterator[Path]:
        nonlocal changed
        children = list(original_iterdir(path))
        if path == watched and not changed:
            changed = True
            child.unlink()
            if replacement == "directory":
                child.mkdir()
        return iter(children)

    monkeypatch.setattr(Path, "iterdir", list_then_change)
    schedule = _schedule(tmp_path / "schedule.json", watch=[str(watched)])
    evidence = tmp_path / "evidence"
    clock = FakeClock()
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert facts.status == "completed"
    first = facts.samples[0].paths[str(watched)]
    assert first["state"] == "directory"
    assert first["copy"] is not None
    stored_child = evidence / first["copy"] / child.name
    if replacement == "missing":
        assert not stored_child.exists()
    else:
        assert stored_child.is_dir()


@pytest.mark.parametrize("fail_write", [False, True])
def test_drop_publishes_complete_content_and_cleans_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_write: bool
) -> None:
    source = tmp_path / "source.csv"
    source.write_bytes(b"complete input\n")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    target = inbox / "orders.csv"
    original_open = Path.open
    original_temporary = tempfile.NamedTemporaryFile
    original_replace = os.replace
    publications: list[bytes] = []

    def guard_write(stream: Any) -> Any:
        original_write = stream.write

        def write(content: bytes) -> int:
            if fail_write:
                original_write(content[:3])
                raise OSError("injected write failure")
            assert not target.exists()
            return original_write(content)

        stream.write = write
        return stream

    def open_path(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        stream = original_open(path, mode, *args, **kwargs)
        return guard_write(stream) if path == target and mode == "wb" else stream

    def temporary(*args: Any, **kwargs: Any) -> Any:
        stream = original_temporary(*args, **kwargs)
        if Path(stream.name).parent == inbox:
            guard_write(stream)
        return stream

    def replace(source_path: str | Path, destination_path: str | Path) -> None:
        if Path(destination_path) == target:
            staged = Path(source_path)
            assert not target.exists()
            assert staged.parent == inbox
            assert staged.name.startswith(".")
            assert staged.suffix != target.suffix
            publications.append(staged.read_bytes())
        original_replace(source_path, destination_path)

    monkeypatch.setattr(Path, "open", open_path)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", temporary)
    monkeypatch.setattr(os, "replace", replace)
    schedule = _schedule(
        tmp_path / "schedule.json",
        drops=[{"at_sec": 0, "source": str(source), "target": str(target)}],
    )
    evidence = tmp_path / "evidence"
    clock = FakeClock()
    if fail_write:
        with pytest.raises(DataError, match="window_action_failed"):
            run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
        assert not target.exists()
        assert not publications
        assert read_window(evidence).status == "failed"
    else:
        run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
        assert publications == [b"complete input\n"]
        assert target.read_bytes() == b"complete input\n"
        assert read_window(evidence).status == "completed"
    assert list(inbox.iterdir()) == ([] if fail_write else [target])


def test_unchanged_watch_leaves_budget_for_later_changed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(window_copy, "MAX_EVIDENCE_BYTES", 12)
    stable = tmp_path / "stable"
    stable.write_bytes(b"123456")
    changing = tmp_path / "changing"
    changing.write_bytes(b"old")
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=1,
        tail_sec=0,
        watch=[str(stable), str(changing)],
    )
    clock = FakeClock()

    def advance(seconds: float) -> None:
        clock.sleep(seconds)
        changing.write_bytes(b"new")

    original_open = Path.open

    def open_without_redundant_copy(
        path: Path, mode: str = "r", *args: Any, **kwargs: Any
    ) -> Any:
        if mode == "wb" and path.name == "00-stable" and path.parent.name == "0001":
            raise OSError("no storage for redundant unchanged copy")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_without_redundant_copy)
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    monkeypatch.undo()
    facts = read_window(evidence)
    unchanged = facts.samples[1].paths[str(stable)]
    changed = facts.samples[1].paths[str(changing)]
    assert facts.status == "completed"
    assert unchanged["state"] == "regular"
    assert unchanged["copy"] is None
    assert changed["state"] == "regular"
    assert changed["copy"] is not None
    assert (evidence / changed["copy"]).read_bytes() == b"new"


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("schedule_read", "window_action_failed"),
        ("final_save", "window_action_failed"),
        ("final_dataerror", "too_large"),
        ("both", "unsafe_file"),
    ],
)
def test_cli_contains_filesystem_failures_and_preserves_original_code(
    tmp_path: Path, failure: str, expected: str
) -> None:
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=0.01,
        tail_sec=0,
        drops=[
            {
                "at_sec": 0,
                "source": str(tmp_path / "missing"),
                "target": str(tmp_path / "target"),
            }
        ]
        if failure == "both"
        else [],
    )
    injection = tmp_path / "injection"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\nfrom typing import IO, Any\n"
        "original_open = Path.open\noriginal_replace = os.replace\n"
        "def open_path(path: Path, *args: Any, **kwargs: Any) -> IO[Any]:\n"
        f"    if {failure == 'schedule_read'!r} and path == Path({str(schedule)!r}):\n"
        "        raise OSError('injected schedule read failure')\n"
        "    return original_open(path, *args, **kwargs)\n"
        "def replace(\n"
        "    source: str | os.PathLike[str], target: str | os.PathLike[str]\n"
        ") -> None:\n"
        "    if Path(target).name == 'manifest.json':\n"
        "        import json\n"
        "        if json.loads(Path(source).read_text())['ended_at'] is not None:\n"
        f"            if {failure == 'final_dataerror'!r}:\n"
        "                from workflow_bench.data import DataError\n"
        "                raise DataError('too_large', 'manifest.json')\n"
        "            raise OSError('injected final save failure')\n"
        "    return original_replace(source, target)\n"
        "Path.open = open_path\nos.replace = replace\n"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(injection), str(Path(__file__).parents[2] / "src")]
    )
    evidence = tmp_path / "evidence"
    completed = subprocess.run(
        [sys.executable, "-m", "workflow_bench.window", str(schedule), str(evidence)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=5,
    )
    assert completed.returncode == 1
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert [
        line for line in completed.stderr.splitlines() if line.startswith("window:")
    ] == [f"window: {expected}"]
    if failure == "schedule_read":
        assert not evidence.exists()
    else:
        assert read_window(evidence).status == "running"
        assert not list(evidence.glob(".manifest-*"))


@pytest.mark.parametrize("replacement", ["missing", "directory", "symlink", "fifo"])
def test_file_replaced_after_classification_is_not_misrecorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    watched = tmp_path / "watched"
    watched.write_text("original")
    outside = tmp_path / "outside"
    outside.write_text("private")
    schedule = _schedule(tmp_path / "schedule.json", watch=[str(watched)])
    original_lstat = Path.lstat
    calls = 0

    def classify_then_replace(path: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        nonlocal calls
        info = original_lstat(path, *args, **kwargs)
        if path == watched:
            calls += 1
            if calls == 2:
                watched.unlink()
                if replacement == "directory":
                    watched.mkdir()
                elif replacement == "symlink":
                    watched.symlink_to(outside)
                elif replacement == "fifo":
                    os.mkfifo(watched)
        return info

    monkeypatch.setattr(Path, "lstat", classify_then_replace)
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    first = facts.samples[0].paths[str(watched)]
    assert facts.status == "completed"
    assert first == {"state": "missing", "sha256": None, "copy": None}


def test_snapshot_directories_keep_schedule_indices_when_offsets_are_unsorted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.write_text("input")
    schedule = _schedule(
        tmp_path / "schedule.json",
        snapshots=[
            {"at_sec": 2, "paths": [str(source)]},
            {"at_sec": 0, "paths": [str(source)]},
        ],
    )
    clock = FakeClock()
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=clock.sleep)
    facts = read_window(evidence)
    assert [(item.planned_offset_sec, item.directory) for item in facts.snapshots] == [
        (0, "snapshots/001"),
        (2, "snapshots/000"),
    ]


@pytest.mark.parametrize("replace_children", [False, True])
def test_changed_watch_shares_traversal_limit_across_probe_and_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replace_children: bool
) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    for index in range(2100):
        (watched / f"a-{index:04}").write_bytes(b"old")
    schedule = _schedule(
        tmp_path / "schedule.json",
        duration_sec=2,
        tail_sec=0,
        watch=[str(watched)],
    )
    clock = FakeClock()
    reads: list[list[str]] = [[], [], []]
    original_open = os.open

    def open_then_replace_children(
        path: str | os.PathLike[str], flags: int, *args: Any, **kwargs: Any
    ) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        source = Path(path)
        if source.parent == watched:
            sample = int(clock.elapsed)
            reads[sample].append(source.name)
            if replace_children and sample == 1 and len(reads[sample]) == 2100:
                for child in watched.iterdir():
                    child.unlink()
                for index in range(2100):
                    (watched / f"b-{index:04}").write_bytes(b"new")
        return descriptor

    def advance(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.elapsed == 1:
            (watched / "a-0000").write_bytes(b"changed")

    monkeypatch.setattr(os, "open", open_then_replace_children)
    evidence = tmp_path / "evidence"
    run_window(schedule, evidence, clock=clock.now, sleep=advance)
    monkeypatch.undo()
    facts = read_window(evidence)
    assert facts.status == "completed"
    assert len(reads[0]) == 2100
    assert all(len(sample_reads) <= 4096 for sample_reads in reads)
    assert len(set(reads[1])) <= 4096
    assert reads[2]
    assert facts.samples[1].paths[str(watched)]["state"] == "truncated"
    if replace_children:
        assert any(name.startswith("b-") for name in reads[1])
        retained = facts.samples[1].paths[str(watched)]["copy"]
        assert retained is not None
        assert all(
            child.read_bytes() == b"new" for child in (evidence / retained).iterdir()
        )
