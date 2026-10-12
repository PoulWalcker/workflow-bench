"""Freeze an operator-supplied final set in a private native Task copy."""

import argparse
import shutil
from pathlib import Path

from workflow_bench.data import DataError, read_bytes
from workflow_bench.definition import load_cases, load_task


def prepare(task: Path, final: Path, destination: Path, tools: Path) -> None:
    """Create an absent, owner-only destination; never generate holdout values."""
    if destination.exists() or destination.is_relative_to(task):
        raise DataError("unsafe_path", "destination")
    content = read_bytes(final, "final")
    destination.mkdir(mode=0o700)
    try:
        for name in ("instruction.md", "task.json", "task.toml", "tests", "solution"):
            source = task / name
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination / name,
                    ignore=shutil.ignore_patterns("__pycache__", "test_*.py"),
                )
            else:
                shutil.copyfile(source, destination / name)
        private = destination / "private"
        private.mkdir(mode=0o700)
        final_copy = private / "final.json"
        final_copy.write_bytes(content)
        final_copy.chmod(0o600)
        config = destination / "task.toml"
        config.write_text(
            config.read_text().replace(
                "[metadata]", '[metadata]\nwb_final_cases = "private/final.json"'
            )
        )
        load_cases(load_task(destination, tool_contract=tools), purpose="final")
    except BaseException:
        # This destination was created exclusively by this call.
        shutil.rmtree(destination)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--tools", type=Path, required=True)
    args = parser.parse_args()
    prepare(
        Path(__file__).resolve().parent,
        args.final.resolve(),
        args.destination.resolve(),
        args.tools.resolve(),
    )
