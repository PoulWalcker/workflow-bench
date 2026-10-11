"""Exercise pytest's public invocation with harmless file-based probes."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]
FIXTURE_SCOPES = ("function", "module", "package", "session")


@pytest.fixture
def gated_project(
    pytester: pytest.Pytester, request: pytest.FixtureRequest
) -> pytest.Pytester:
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
        f'@pytest.fixture(scope="{getattr(request, "param", "function")}")\n'
        "def resource():\n"
        '    Path("resource-setup").touch()\n'
        '    return Path("resource-setup")\n'
        "def test_resource_setup(resource):\n"
        "    assert resource.exists()\n"
    )

    return pytester


def _resource_project(project: pytest.Pytester, suite: str) -> Path:
    tests = project.path / "tests"
    (tests / "__init__.py").touch()
    integration = tests / "integration"
    (integration / "__init__.py").touch()
    (integration / "test_probe.py").rename(integration / "resource_plugin.py")
    if suite == "model":
        integration.rename(integration.with_name("model"))
    fast = tests / "fast"
    fast.mkdir()
    return fast


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


@pytest.mark.parametrize("gated_project", FIXTURE_SCOPES, indirect=True)
def test_integration_opt_in_allows_synthetic_fixture(
    gated_project: pytest.Pytester,
) -> None:
    result = gated_project.runpytest_subprocess(
        "tests/integration", "--run-integration", timeout=10
    )

    result.assert_outcomes(passed=1)
    assert (gated_project.path / "resource-setup").exists()


@pytest.mark.parametrize("gated_project", FIXTURE_SCOPES, indirect=True)
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
@pytest.mark.parametrize("invocation", [(), ("tests/fast",)])
@pytest.mark.parametrize(
    "flags",
    [
        (),
        ("--run-integration",),
        ("--collect-only",),
        ("--run-integration", "--collect-only"),
    ],
)
@pytest.mark.parametrize("gated_project", FIXTURE_SCOPES, indirect=True)
def test_fast_cannot_request_gated_fixture(
    gated_project: pytest.Pytester,
    suite: str,
    invocation: tuple[str, ...],
    flags: tuple[str, ...],
) -> None:
    fast = _resource_project(gated_project, suite)
    (fast / "test_request.py").write_text(
        f'pytest_plugins = ["tests.{suite}.resource_plugin"]\n'
        "def test_resource(resource):\n"
        "    assert resource.exists()\n"
    )

    result = gated_project.runpytest_subprocess(*invocation, *flags, timeout=10)

    if "--collect-only" in flags:
        assert result.ret == pytest.ExitCode.OK
        result.stdout.fnmatch_lines(["*1 test collected*"])
    else:
        result.assert_outcomes(errors=1)
        result.stdout.fnmatch_lines(
            ["*fixtures*" if suite == "model" else "*integration fixtures*"]
        )
    assert not (gated_project.path / "resource-setup").exists()


@pytest.mark.parametrize("gated_project", FIXTURE_SCOPES, indirect=True)
@pytest.mark.parametrize("access", ["argument", "dynamic", "dependency"])
def test_fast_cannot_reuse_integration_fixture(
    gated_project: pytest.Pytester, access: str
) -> None:
    fast = _resource_project(gated_project, "integration")
    # Importing into conftest gives package scope a real Package node.
    with (fast.parent / "conftest.py").open("a") as stream:
        stream.write("\nfrom tests.integration.resource_plugin import resource\n")
    consumer = "def test_resource(resource):\n"
    if access == "dynamic":
        consumer = (
            'def test_resource(request):\n    request.getfixturevalue("resource")\n'
        )
    elif access == "dependency":
        consumer = "def test_resource(local_resource):\n"
    (fast / "test_request.py").write_text(
        "from pathlib import Path\n"
        "import pytest\n"
        "@pytest.mark.integration\n"
        "def test_warmup(resource):\n"
        "    assert resource.exists()\n"
        "@pytest.fixture\n"
        "def local_resource(request):\n"
        '    return request.getfixturevalue("resource")\n'
        + consumer
        + '    Path("fast-consumed").touch()\n'
    )

    result = gated_project.runpytest_subprocess(
        "tests/fast", "--run-integration", timeout=10
    )

    assert (gated_project.path / "resource-setup").exists()
    assert not (gated_project.path / "fast-consumed").exists()
    if access == "dynamic":
        result.assert_outcomes(passed=1, failed=1)
    else:
        result.assert_outcomes(passed=1, errors=1)
