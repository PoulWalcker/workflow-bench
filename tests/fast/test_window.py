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
    ],
)
def test_invalid_schedule_has_no_effect(tmp_path: Path, updates: dict) -> None:
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
