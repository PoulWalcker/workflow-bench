"""The `wb` command line: Workflow Bench checks around native Harbor runs."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from workflow_bench.readiness import check_task


def main(argv: Sequence[str] | None = None) -> int:
    """Run one `wb` command; return the process exit status.

    `check-task` prints its JSON report on stdout and returns 0 only when the
    task is ready, 1 otherwise.
    """
    arguments = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s %(message)s",
    )
    report = check_task(
        arguments.task_dir.resolve(),
        jobs_dir=arguments.jobs_dir.resolve(),
        run_timeout_sec=arguments.run_timeout_sec,
        cleanup_timeout_sec=arguments.cleanup_timeout_sec,
    )
    sys.stdout.write(
        json.dumps(
            {
                "task": report.task,
                "ready": report.is_ready,
                "reasons": report.reasons,
                "runs": [asdict(run) for run in report.runs],
            }
        )
        + "\n"
    )
    return 0 if report.is_ready else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wb")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check-task",
        help="Check a task's authoring structure and oracle/no-op readiness.",
    )
    check.add_argument("task_dir", type=Path, help="Native Harbor task directory.")
    check.add_argument(
        "--jobs-dir",
        type=Path,
        required=True,
        help="Directory receiving the Harbor jobs of the control runs.",
    )
    check.add_argument(
        "--run-timeout-sec",
        type=_positive_seconds,
        default=900.0,
        help="Deadline for each control's `harbor run` (default: 900).",
    )
    check.add_argument(
        "--cleanup-timeout-sec",
        type=_positive_seconds,
        default=60.0,
        help="Deadline for environment teardown and interruption (default: 60).",
    )
    return parser


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if not 0 < seconds < float("inf"):
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return seconds


if __name__ == "__main__":
    sys.exit(main())
