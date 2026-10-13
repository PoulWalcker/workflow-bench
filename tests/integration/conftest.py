"""Preflight for Docker-backed controls: missing resources fail, never skip."""

from pathlib import Path

import pytest

from workflow_bench.readiness import helper_reasons

TRIVIAL_TASK = Path(__file__).resolve().parents[2] / "tasks" / "l1-basket-total"


@pytest.fixture(scope="session")
def trivial_task() -> Path:
    """The trivial task, after confirming its local base image carries this helper."""
    reasons = helper_reasons(TRIVIAL_TASK)
    if reasons:
        pytest.fail(
            f"{', '.join(reasons)}: Docker with a current local agents image is "
            "required; rebuild it, see README"
        )
    return TRIVIAL_TASK
