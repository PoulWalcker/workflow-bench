"""The `wb` command line: Workflow Bench checks around native Harbor runs."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from workflow_bench.comparison import compare, render_markdown
from workflow_bench.data import DataError
from workflow_bench.readiness import check_task


def main(argv: Sequence[str] | None = None) -> int:
    """Run one `wb` command; return the process exit status.

    `check-task` prints its JSON report on stdout and returns 0 only when the
    task is ready, 1 otherwise. `compare` prints its JSON or Markdown report
    on stdout and returns 0, or 2 when an argument is not a Harbor job
    directory or is repeated.
    """
    parser = _parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s %(message)s",
    )
    if arguments.command == "compare":
        return _compare(parser, arguments)
    return _check_task(arguments)


def _check_task(arguments: argparse.Namespace) -> int:
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


def _compare(parser: argparse.ArgumentParser, arguments: argparse.Namespace) -> int:
    job_dirs = [path.resolve() for path in arguments.job_dirs]
    if len(set(job_dirs)) != len(job_dirs):
        parser.error("a job directory is given more than once")
    try:
        report = compare(job_dirs)
    except DataError as error:
        parser.error(f"not a Harbor job directory: {error.relative_path}")
    if arguments.format == "markdown":
        sys.stdout.write(render_markdown(report))
    else:
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


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
    report = commands.add_parser(
        "compare",
        help="Report Trial outcomes per task and configuration from Harbor jobs.",
    )
    report.add_argument(
        "job_dirs",
        type=Path,
        nargs="+",
        metavar="job_dir",
        help="Harbor job directory (<jobs-dir>/<job-name>).",
    )
    report.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="Report format on stdout (default: json).",
    )
    return parser


def _positive_seconds(value: str) -> float:
    seconds = float(value)
    if not 0 < seconds < float("inf"):
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return seconds


if __name__ == "__main__":
    sys.exit(main())
