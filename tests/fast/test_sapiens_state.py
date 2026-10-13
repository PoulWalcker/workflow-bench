"""Sapiens state selection at the data-directory export boundary."""

import json
import sqlite3
from pathlib import Path

import pytest

from workflow_bench_integrations.sapiens_state import write_state_snapshot


def test_state_snapshot_keeps_chronology_without_credentials_or_sqlite_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home))
    source = tmp_path / "data"
    source.mkdir()
    database = source / "corpora.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            "CREATE TABLE agents (id TEXT, name TEXT, role TEXT, "
            "created TEXT, secret TEXT);"
            "CREATE TABLE turns (id TEXT, agent TEXT, input TEXT, output TEXT, "
            "status TEXT, created TEXT, secret TEXT);"
            "CREATE TABLE workloads (id TEXT, value TEXT);"
        )
        connection.execute(
            "INSERT INTO agents VALUES (?,?,?,?,?)",
            (
                "chief",
                "Chief",
                "admin",
                "2026-01-01T00:00:00Z",
                "credential-only-column",
            ),
        )
        connection.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?,?)",
            (
                "turn1",
                "chief",
                (
                    "Compute total OPENAI_API_KEY=sk-secret123456; "
                    "Authorization: Basic dXNlcjpwYXNz; "
                    "AWS_ACCESS_KEY_ID=AKIAEXAMPLE00000000; "
                    'account ID is 123456789; password: "a secret phrase"; '
                    "password: another secret phrase; "
                    "api_token=DEMO_API_TOKEN_123; token=DEMO_TOKEN_123; "
                    "Authorization: token DEMO_AUTH_TOKEN_123; "
                    "account identifier is 987654321"
                ),
                "Done",
                "done",
                "2026-01-01T00:00:00Z",
                "turn-credential",
            ),
        )
        connection.execute(
            "INSERT INTO workloads VALUES (?,?)",
            (
                "work1",
                json.dumps(
                    {
                        "calls": [
                            {
                                "callId": "turn1",
                                "addressedTo": "chief",
                                "state": "Delegated",
                            },
                            {
                                "callId": "turn2",
                                "addressedTo": "sapi_x",
                                "causedBy": "turn1",
                                "request": "Calculate total",
                                "state": "Completed",
                            },
                        ],
                        "decisions": [
                            {
                                "agent": "chief",
                                "node": "Delegation",
                                "response": {
                                    "event": "HandoffPrepared",
                                    "reason": "Specialist needed",
                                },
                                "transition": {
                                    "before": "Delegation",
                                    "after": "Assessing",
                                },
                            }
                        ],
                        "rawResponse": "do-not-copy",
                    }
                ),
            ),
        )
    (source / "auth.json").write_text("auth-file-secret")
    (source / "corpora.sqlite3-wal").write_text("wal-secret")
    output = tmp_path / "agent" / "sapiens-state.json"
    output.parent.mkdir()
    write_state_snapshot(source, output)
    snapshot = json.loads(output.read_text())
    content = output.read_text()
    assert snapshot["agents"] == [{"id": "chief", "name": "Chief", "role": "admin"}]
    assert snapshot["turns"][0]["input"].count("[REDACTED]") == 10
    assert snapshot["workloads"][0]["calls"][1]["addressedTo"] == "sapi_x"
    assert snapshot["workloads"][0]["decisions"][0]["transition"] == {
        "before": "Delegation",
        "after": "Assessing",
    }
    assert all(
        secret not in content
        for secret in (
            "sk-secret123456",
            "credential-only-column",
            "turn-credential",
            "do-not-copy",
            "auth-file-secret",
            "wal-secret",
            "dXNlcjpwYXNz",
            "AKIAEXAMPLE00000000",
            "123456789",
            "a secret phrase",
            "another secret phrase",
            "secret phrase",
            "DEMO_API_TOKEN_123",
            "DEMO_TOKEN_123",
            "DEMO_AUTH_TOKEN_123",
            "987654321",
        )
    )
    assert not output.with_name("corpora.sqlite3").exists()


def test_state_snapshot_marks_capped_decisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home))
    source = tmp_path / "data"
    source.mkdir()
    with sqlite3.connect(source / "corpora.sqlite3") as connection:
        connection.executescript(
            "CREATE TABLE agents (id TEXT, name TEXT, role TEXT, created TEXT);"
            "CREATE TABLE turns (id TEXT, agent TEXT, input TEXT, output TEXT, "
            "status TEXT, created TEXT);"
            "CREATE TABLE workloads (value TEXT);"
        )
        connection.execute(
            "INSERT INTO workloads VALUES (?)",
            (json.dumps({"calls": [], "decisions": [{"node": "Execution"}] * 65}),),
        )
    destination = tmp_path / "sapiens-state.json"
    write_state_snapshot(source, destination)
    snapshot = json.loads(destination.read_text())
    assert len(snapshot["workloads"][0]["decisions"]) == 64
    assert snapshot["truncated"]["decisions"] is True


def test_state_snapshot_masks_injected_values_in_selected_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "data"
    source.mkdir()
    home = tmp_path / "codex"
    home.mkdir()
    auth_value = "DUMMY_UNLABELLED_AUTH_VALUE_123456"
    nested_value = "DUMMY_NESTED_AUTH_VALUE_123456"
    api_key = "DUMMY_ENV_API_VALUE_123456"
    (home / "auth.json").write_text(
        json.dumps({"auth": {"access": auth_value, "nested": [nested_value]}})
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", api_key)
    with sqlite3.connect(source / "corpora.sqlite3") as connection:
        connection.executescript(
            "CREATE TABLE agents (id TEXT, name TEXT, role TEXT, created TEXT);"
            "CREATE TABLE turns (id TEXT, agent TEXT, input TEXT, output TEXT, "
            "status TEXT, created TEXT);"
            "CREATE TABLE workloads (value TEXT);"
        )
        connection.execute(
            "INSERT INTO turns VALUES (?,?,?,?,?,?)",
            (
                "turn1",
                "chief",
                f"bare {auth_value}; URL https://example.test/{nested_value}",
                f'JSON {{"value":"{api_key}"}}',
                "done",
                "2026-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO workloads VALUES (?)",
            (
                json.dumps(
                    {
                        "calls": [{"request": auth_value, "output": nested_value}],
                        "decisions": [
                            {"response": {"reason": api_key, "reply": nested_value}}
                        ],
                    }
                ),
            ),
        )
    destination = tmp_path / "sapiens-state.json"
    write_state_snapshot(source, destination)
    output = destination.read_text()
    assert all(value not in output for value in (auth_value, nested_value, api_key))
    assert "[REDACTED]" in output


def test_state_snapshot_requires_readable_injected_auth_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    destination = tmp_path / "sapiens-state.json"
    with pytest.raises(ValueError, match="auth_source_unavailable"):
        write_state_snapshot(tmp_path, destination)
    assert not destination.exists()
