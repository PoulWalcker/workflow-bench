"""Preflight for Docker-backed controls: missing resources fail, never skip."""

import subprocess
from pathlib import Path

import pytest

TRIVIAL_TASK = Path(__file__).resolve().parents[2] / "tasks" / "l1-basket-total"


def _base_image(task_dir: Path) -> str:
    dockerfile = (task_dir / "environment" / "Dockerfile").read_text()
    return next(
        line.split()[1] for line in dockerfile.splitlines() if line.startswith("FROM ")
    )


@pytest.fixture(scope="session")
def trivial_task() -> Path:
    """The trivial task, after confirming Docker and its local base image exist."""
    image = _base_image(TRIVIAL_TASK)
    try:
        subprocess.run(
            ["docker", "image", "inspect", image],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pytest.fail(f"Docker with the local image {image} is required; see README")
    return TRIVIAL_TASK
