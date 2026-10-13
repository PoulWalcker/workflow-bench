"""Formatting of safe diagnostic phase lines."""

from datetime import UTC, datetime

from workflow_bench.observability import format_phase_line


def test_phase_line_uses_utc_iso_time_and_duration_seconds() -> None:
    observed_at = datetime(2026, 1, 1, 4, 30, tzinfo=UTC)

    line = format_phase_line(
        "environment_start", "completed", 1.25, observed_at, trial="basket__abc"
    )

    assert line == (
        "at=2026-01-01T04:30:00Z phase=environment_start result=completed "
        "duration=1.250s trial=basket__abc"
    )
