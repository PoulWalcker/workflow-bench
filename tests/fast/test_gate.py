"""Exercise pytest's public invocation with harmless file-based probes."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]


@pytest.fixture
def gated_project(pytester: pytest.Pytester) -> pytest.Pytester:
    root = Path(__file__).resolve().parents[2]
    pytester.makefile(".toml", pyproject=(root / "pyproject.toml").read_text())
    integration = pytester.path / "tests" / "integration"
    integration.mkdir(parents=True)
    (pytester.path / "tests" / "conftest.py").write_text(
        (root / "tests" / "conftest.py").read_text()
    )
    (integration / "test_probe.py").write_text(
        "from pathlib import Path\n"
        "import pytest\n"
        'Path("collected").touch()\n'
        "@pytest.fixture\n"
        "def resource():\n"
        '    Path("resource-setup").touch()\n'
        '    return Path("resource-setup")\n'
        "def test_resource_setup(resource):\n"
        "    assert resource.exists()\n"
    )

    return pytester


@pytest.mark.parametrize("suite", ["integration", "model"])
@pytest.mark.parametrize("flags", [(), ("--collect-only",)])
def test_default_ignores_gated_directories_before_import(
    gated_project: pytest.Pytester, suite: str, flags: tuple[str, ...]
) -> None:
    if suite == "model":
        integration = gated_project.path / "tests" / "integration"
        integration.rename(integration.with_name("model"))
    result = gated_project.runpytest_subprocess(*flags, timeout=10)

    assert result.ret == pytest.ExitCode.NO_TESTS_COLLECTED
    assert not (gated_project.path / "collected").exists()
    assert not (gated_project.path / "resource-setup").exists()


@pytest.mark.parametrize(
    "path",
    [
        "tests/integration",
        "tests/integration/test_probe.py",
        "tests/integration/test_probe.py::test_resource_setup",
    ],
)
@pytest.mark.parametrize("flags", [(), ("--collect-only",)])
def test_explicit_integration_path_rejected_before_setup(
    gated_project: pytest.Pytester, path: str, flags: tuple[str, ...]
) -> None:
    result = gated_project.runpytest_subprocess(path, *flags, timeout=10)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*requires --run-integration*"])
    assert not (gated_project.path / "resource-setup").exists()


def test_integration_opt_in_allows_synthetic_fixture(
    gated_project: pytest.Pytester,
) -> None:
    result = gated_project.runpytest_subprocess(
        "tests/integration", "--run-integration", timeout=10
    )

    result.assert_outcomes(passed=1)
    assert (gated_project.path / "resource-setup").exists()


def test_collect_only_with_integration_opt_in_does_not_set_up_fixture(
    gated_project: pytest.Pytester,
) -> None:
    result = gated_project.runpytest_subprocess(
        "tests/integration", "--run-integration", "--collect-only", timeout=10
    )

    assert result.ret == pytest.ExitCode.OK
    result.stdout.fnmatch_lines(["*1 test collected*"])
    assert not (gated_project.path / "resource-setup").exists()


def test_integration_opt_in_does_not_authorize_model_marker(
    gated_project: pytest.Pytester,
) -> None:
    probe = gated_project.path / "tests" / "integration" / "test_probe.py"
    with probe.open("a") as stream:
        stream.write("\npytestmark = pytest.mark.model\n")

    result = gated_project.runpytest_subprocess(
        "tests/integration", "--run-integration", timeout=10
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert not (gated_project.path / "resource-setup").exists()


def test_model_path_rejected_even_with_integration_opt_in(
    gated_project: pytest.Pytester,
) -> None:
    integration = gated_project.path / "tests" / "integration"
    integration.rename(integration.with_name("model"))

    result = gated_project.runpytest_subprocess(
        "tests/model/test_probe.py", "--run-integration", timeout=10
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert not (gated_project.path / "resource-setup").exists()


@pytest.mark.parametrize("flags", [(), ("--collect-only",), ("--run-integration",)])
def test_model_mode_rejected_before_collection(
    gated_project: pytest.Pytester, flags: tuple[str, ...]
) -> None:
    result = gated_project.runpytest_subprocess("--run-model", *flags, timeout=10)

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*model mode is not implemented*"])
    assert not (gated_project.path / "collected").exists()
    assert not (gated_project.path / "resource-setup").exists()


@pytest.mark.parametrize("selection", ["integration", "not integration"])
def test_integration_marker_cannot_bypass_gate_with_marker_selection(
    gated_project: pytest.Pytester, selection: str
) -> None:
    integration = gated_project.path / "tests" / "integration"
    fast = integration.with_name("fast")
    integration.rename(fast)
    with (fast / "test_probe.py").open("a") as stream:
        stream.write("\npytestmark = pytest.mark.integration\n")

    result = gated_project.runpytest_subprocess(
        "tests/fast", "-m", selection, timeout=10
    )

    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert not (gated_project.path / "resource-setup").exists()


@pytest.mark.parametrize("suite", ["integration", "model"])
@pytest.mark.parametrize("flags", [(), ("--run-integration",)])
def test_fast_cannot_request_gated_fixture(
    gated_project: pytest.Pytester, suite: str, flags: tuple[str, ...]
) -> None:
    tests = gated_project.path / "tests"
    (tests / "__init__.py").touch()
    integration = tests / "integration"
    (integration / "__init__.py").touch()
    (integration / "test_probe.py").rename(integration / "resource_plugin.py")
    if suite == "model":
        integration.rename(integration.with_name("model"))
    fast = tests / "fast"
    fast.mkdir()
    (fast / "test_request.py").write_text(
        f'pytest_plugins = ["tests.{suite}.resource_plugin"]\n'
        "def test_resource(resource):\n"
        "    assert resource.exists()\n"
    )

    result = gated_project.runpytest_subprocess("tests/fast", *flags, timeout=10)

    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(
        ["*fixtures*" if suite == "model" else "*integration fixtures*"]
    )
    assert not (gated_project.path / "resource-setup").exists()
