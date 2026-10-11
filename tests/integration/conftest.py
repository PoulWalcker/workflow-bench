from pathlib import Path

import pytest

from workflow_bench.cli import load_config


@pytest.fixture
def e1_config(request: pytest.FixtureRequest, tmp_path: Path):
    path = request.config.getoption("--e1-config")
    if not request.config.getoption("--run-integration") or not path:
        pytest.fail("prepare images and pass --run-integration --e1-config")
    return load_config(Path(path).resolve(), output=tmp_path / "run")
