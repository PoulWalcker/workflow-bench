"""Observation-window timing and evidence through the public driver and reader."""

import json
from pathlib import Path

import pytest

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
