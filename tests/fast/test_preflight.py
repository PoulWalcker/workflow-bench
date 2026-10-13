"""Subscription admission through the CLI and a fixture native account server."""

import json
import os
from pathlib import Path

import pytest

from workflow_bench.cli import main


def test_preflight_reports_available_subscription(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    auth = _account_server(
        tmp_path,
        monkeypatch,
        {
            "ordinaryUsageAllowed": True,
            "rateLimits": {
                "primary": {"usedPercent": 25},
                "secondary": None,
                "accountId": "secret-fixture",
            },
        },
    )
    assert main(["preflight", "--auth-path", str(auth)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert "secret-fixture" not in json.dumps(report)
    assert report["allowed"] is True
    assert report["rateLimits"]["primary"]["usedPercent"] == 25


@pytest.mark.parametrize(
    "response,reason",
    [
        (
            {
                "ordinaryUsageAllowed": True,
                "rateLimits": {"primary": {"usedPercent": 100}},
            },
            "subscription_exhausted",
        ),
        ({"ordinaryUsageAllowed": False}, "subscription_exhausted"),
        (
            {"ordinaryUsageAllowed": True, "rateLimitsByLimitId": ["invalid"]},
            "subscription_status_unavailable",
        ),
        (
            {
                "ordinaryUsageAllowed": True,
                "rateLimits": {
                    "primary": {"usedPercent": 25},
                    "secondary": "secret-fixture",
                },
            },
            "subscription_status_unavailable",
        ),
        ([], "subscription_status_unavailable"),
        (
            {
                "ordinaryUsageAllowed": True,
                "rateLimits": {"primary": {"usedPercent": True}},
            },
            "subscription_status_unavailable",
        ),
    ],
)
def test_preflight_denies_exhausted_or_malformed_allowance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    response: object,
    reason: str,
) -> None:
    auth = _account_server(tmp_path, monkeypatch, response)
    assert main(["preflight", "--auth-path", str(auth)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"allowed": False, "reason": reason}
    assert "secret-fixture" not in captured.out + captured.err


@pytest.mark.parametrize("wire", ["not JSON", "[]", '{"id": 2, "result": NaN}'])
def test_preflight_malformed_protocol_is_a_safe_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    wire: str,
) -> None:
    auth = _account_server(tmp_path, monkeypatch, {})
    (tmp_path / "codex").write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "sys.stdin.readline()\n"
        f"print({wire!r}, flush=True)\n"
    )
    assert main(["preflight", "--auth-path", str(auth)]) == 1
    assert (
        json.loads(capsys.readouterr().out)["reason"]
        == "subscription_status_unavailable"
    )


@pytest.mark.parametrize("spend_control", [True, "true", 1, [], {"reached": True}])
def test_preflight_respects_native_spend_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    spend_control: object,
) -> None:
    auth = _account_server(
        tmp_path,
        monkeypatch,
        {
            "ordinaryUsageAllowed": True,
            "rateLimits": {
                "primary": {"usedPercent": 25},
                "spendControlReached": spend_control,
            },
        },
    )
    assert main(["preflight", "--auth-path", str(auth)]) == 1
    reason = (
        "subscription_exhausted"
        if spend_control is True
        else "subscription_status_unavailable"
    )
    assert json.loads(capsys.readouterr().out) == {"allowed": False, "reason": reason}


def _account_server(
    directory: Path, monkeypatch: pytest.MonkeyPatch, response: object
) -> Path:
    auth = directory / "auth.json"
    auth.write_text(
        json.dumps(
            {"auth_mode": "chatgpt", "tokens": {"access_token": "secret-fixture"}}
        )
    )
    executable = directory / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        "for line in sys.stdin:\n"
        " request = json.loads(line)\n"
        " if 'id' not in request: continue\n"
        f" response = {response!r} if request['id'] == 2 else {{}}\n"
        " print(json.dumps({'id': request['id'], 'result': response}), flush=True)\n"
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + os.environ["PATH"])
    return auth
