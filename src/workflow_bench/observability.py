"""Safe, consistently timed diagnostic lines for owned run phases."""

import json
from datetime import UTC, datetime
from pathlib import Path

from workflow_bench.comparison import read_evaluation
from workflow_bench.data import DataError
from workflow_bench.transcript import mask_sensitive_text


def format_sapiens_cli_line(
    subcommand: str,
    exit_code: int | None,
    duration_seconds: float,
    output: str | None,
    observed_at: datetime,
    *,
    trial: str,
    instruction: str | None = None,
) -> str:
    """Return one CLI line with a masked excerpt of at most 200 characters.

    The submitted instruction is removed in raw and JSON-escaped forms.
    Pattern masking for other sensitive output remains best-effort.
    """
    timestamp = observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    safe_output = output or ""
    if instruction:
        safe_output = safe_output.replace(instruction, "[REDACTED]")
        safe_output = safe_output.replace(json.dumps(instruction)[1:-1], "[REDACTED]")
    excerpt = (
        mask_sensitive_text(safe_output).replace("\n", " ").replace("\r", " ")[:200]
    )
    return (
        f"at={timestamp} phase=sapiens-cli trial={trial} subcommand={subcommand} "
        f"exit={exit_code if exit_code is not None else 'unavailable'} "
        f"duration={duration_seconds:.3f}s excerpt={json.dumps(excerpt)}"
    )


def format_verifier_summary(evaluation_path: Path, observed_at: datetime) -> str:
    """Summarize a validated assessment; unreadable files report unavailable."""
    timestamp = observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        evaluation = read_evaluation(evaluation_path)
    except (OSError, DataError):
        return (
            f"at={timestamp} phase=verifier result=unavailable "
            "criteria=unknown failed=unknown"
        )
    failed = ",".join(
        criterion["criterion_id"]
        for criterion in evaluation["criteria"]
        if criterion["status"] == "fail"
    )
    return (
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"criteria={len(evaluation['criteria'])} failed={failed or 'none'}"
    )


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
