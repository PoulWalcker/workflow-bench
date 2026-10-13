"""Sapiens state selection at the data-directory export boundary."""

import json
import sqlite3
from pathlib import Path

from workflow_bench_integrations.sapiens_state import write_state_snapshot


def test_state_snapshot_keeps_chronology_without_credentials_or_sqlite_files(
    tmp_path: Path,
) -> None:
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
                "Compute total OPENAI_API_KEY=sk-secret123456",
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
    assert snapshot["turns"][0]["input"] == "Compute total [REDACTED]"
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
        )
    )
    assert not output.with_name("corpora.sqlite3").exists()
