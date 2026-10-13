"""Keep resource tests out of the default local test run."""

from inspect import getfile
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration", action="store_true", help="Enable integration tests."
    )
    parser.addoption(
        "--run-model",
        action="store_true",
        help="Reserved; model mode is not implemented.",
    )


def pytest_configure(config: pytest.Config) -> None:
    if config.getoption("--run-model"):
        raise pytest.UsageError("model mode is not implemented")
    execute = pytest.FixtureDef.execute

    def gated_execute(
        fixturedef: pytest.FixtureDef, request: pytest.FixtureRequest
    ) -> object:
        _check_fixture_request(fixturedef, request)
        return execute(fixturedef, request=request)

    # Setup hooks use scope-local conftests and are skipped for cached fixtures.
    patch = pytest.MonkeyPatch()
    patch.setattr(pytest.FixtureDef, "execute", gated_execute)
    config.add_cleanup(patch.undo)


def _suite(path: Path, config: pytest.Config) -> str | None:
    for suite in ("model", "integration"):
        if path.resolve().is_relative_to((config.rootpath / "tests" / suite).resolve()):
            return suite
    return None


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    suite = _suite(collection_path, config)
    if suite == "model":
        return True
    if suite == "integration" and not config.getoption("--run-integration"):
        return True
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for argument in config.args:
        path = config.invocation_params.dir / argument.split("::", 1)[0]
        suite = _suite(path, config)
        if suite == "model":
            raise pytest.UsageError(f"{argument}: model tests are not implemented")
        if suite == "integration" and not config.getoption("--run-integration"):
            raise pytest.UsageError(f"{argument} requires --run-integration")
    for item in items:
        suite = _suite(item.path, config)
        if suite == "model" or item.get_closest_marker("model"):
            raise pytest.UsageError(f"{item.nodeid}: model tests are not implemented")
        if (
            suite == "integration" or item.get_closest_marker("integration")
        ) and not config.getoption("--run-integration"):
            raise pytest.UsageError(f"{item.nodeid} requires --run-integration")


def _check_fixture_request(
    fixturedef: pytest.FixtureDef, request: pytest.FixtureRequest
) -> None:
    suite = _suite(Path(getfile(fixturedef.func)), request.config)
    if suite == "model":
        pytest.fail("model fixtures are not implemented")
    if suite == "integration":
        if not request.config.getoption("--run-integration"):
            pytest.fail("integration fixtures require --run-integration")
        # pytest retains the consuming item here regardless of fixture scope.
        item = request._pyfuncitem
        if item.path.is_relative_to(
            request.config.rootpath / "tests" / "fast"
        ) and not item.get_closest_marker("integration"):
            pytest.fail("fast tests cannot request integration fixtures")
