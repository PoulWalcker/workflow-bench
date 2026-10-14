"""Formatting of safe diagnostic phase lines."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from workflow_bench.observability import (
    format_phase_line,
    format_sapiens_cli_line,
    format_verifier_summary,
)


def test_phase_line_uses_utc_iso_time_and_duration_seconds() -> None:
    observed_at = datetime(2026, 1, 1, 4, 30, tzinfo=UTC)

    line = format_phase_line(
        "environment_start", "completed", 1.25, observed_at, trial="basket__abc"
    )

    assert line == (
        "at=2026-01-01T04:30:00Z phase=environment_start result=completed "
        "duration=1.250s trial=basket__abc"
    )


def test_verifier_summary_reports_validated_result(tmp_path: Path) -> None:
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(
        '{"verdict":"pass","completeness":"complete","criteria":'
        '[{"criterion_id":"answer","status":"pass","reason_code":"pass"}],'
        '"errors":[]}'
    )

    line = format_verifier_summary(evaluation, datetime(2026, 1, 1, tzinfo=UTC))

    assert line == (
        "at=2026-01-01T00:00:00Z phase=verifier result=pass criteria=1 failed=none"
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (
            (
                '{"verdict":"fail","completeness":"complete","criteria":'
                '[{"criterion_id":"answer","status":"fail","reason_code":"wrong"},'
                '{"criterion_id":"shape","status":"pass","reason_code":"pass"}],'
                '"errors":[]}'
            ),
            "result=fail criteria=2 failed=answer",
        ),
        (None, "result=unavailable criteria=unknown failed=unknown"),
        ('{"verdict":"pass"}', "result=unavailable criteria=unknown failed=unknown"),
    ],
)
def test_verifier_summary_handles_failure_and_unavailable_files(
    tmp_path: Path, content: str | None, expected: str
) -> None:
    evaluation = tmp_path / "evaluation.json"
    if content is not None:
        evaluation.write_text(content)

    line = format_verifier_summary(evaluation, datetime(2026, 1, 1, tzinfo=UTC))

    assert expected in line


def test_sapiens_cli_line_masks_instruction_and_secret() -> None:
    instruction = "Write fixture answer\nin /work/output/answer.json"
    secret = "sk-fixture-secret-123456"
    output = (
        instruction
        + "\n"
        + json.dumps({"echo": instruction})
        + "\nOPENAI_API_KEY="
        + secret
        + "\n"
        + "x" * 300
    )

    line = format_sapiens_cli_line(
        "chat",
        0,
        1.25,
        output,
        datetime(2026, 1, 1, tzinfo=UTC),
        trial="basket__abc",
        instruction=instruction,
    )

    assert "at=2026-01-01T00:00:00Z phase=sapiens-cli" in line
    assert "trial=basket__abc subcommand=chat exit=0 duration=1.250s" in line
    assert "excerpt=" in line
    assert instruction not in line
    assert secret not in line
    excerpt = json.loads(line.split("excerpt=", 1)[1])
    assert json.dumps(instruction)[1:-1] not in excerpt
    assert len(excerpt) <= 200
