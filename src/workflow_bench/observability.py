"""Safe, consistently timed diagnostic lines for owned run phases."""

from datetime import UTC, datetime


def format_phase_line(
    phase: str,
    result: str,
    duration_seconds: float,
    observed_at: datetime,
    *,
    trial: str | None = None,
) -> str:
    """Return a UTC phase line with duration in seconds and optional Trial name."""
    timestamp = observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    line = (
        f"at={timestamp} phase={phase} result={result} duration={duration_seconds:.3f}s"
    )
    if trial is not None:
        line += f" trial={trial}"
    return line
