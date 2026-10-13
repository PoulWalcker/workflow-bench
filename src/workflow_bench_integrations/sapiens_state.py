"""Bounded Sapiens chronology export with exact injected-secret masking.

Pattern masking is best-effort; inspect transcripts before sharing them.
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

_MAX_AGENTS = 64
_MAX_TURNS = 256
_MAX_WORKLOADS = 128
_MAX_CALLS = 64
_MAX_DECISIONS = 64
_MAX_TEXT = 16_000
_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_SENSITIVE_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s,;"'}]+)"""
_SECRET = re.compile(
    r"\b(?:password|secret)\b\s*[\"']?\s*[:=]\s*"
    r"(?:\"[^\"]*(?:\"|$)|'[^']*(?:'|$)|[^\n;]+)"
    r"|(?:\b(?:OPENAI_API_KEY|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|api[_ -]?key|"
    r"(?:api|access|auth|refresh|id)[_ -]?token|token|"
    r"account[_ -]?(?:id|number|identifier)|creator_account_id|"
    r"secret|password)\b\s*[\"']?\s*[:=]\s*|"
    r"\baccount[ _-]*(?:id|number|identifier)\b\s+is\s+)"
    + _SENSITIVE_VALUE
    + r"|\bAuthorization\s*:\s*(?:Basic|Bearer|Token)\s+[^\s,;]+"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]+|\bsk-[A-Za-z0-9_-]+"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\b(?:acct|org|usr|user|acc)_[A-Za-z0-9_-]+"
    r"|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)


def write_state_snapshot(source: Path, destination: Path) -> None:
    """Export selected conversation facts, excluding database and auth material.

    The pinned Sapiens revision stores agents, turns and full workload decisions
    in SQLite. This exports only the fields needed for an offline transcript.
    It never copies the database, WAL, workspaces, notes or credential files.
    """
    secrets = _secret_values()
    database = source / "corpora.sqlite3"
    if database.is_symlink() or not database.is_file():
        raise ValueError("sapiens_state_unavailable")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        truncated = {
            key: False for key in ("agents", "turns", "workloads", "calls", "decisions")
        }
        agent_rows = connection.execute(
            "SELECT id, name, role FROM agents ORDER BY created, id LIMIT ?",
            (_MAX_AGENTS + 1,),
        ).fetchall()
        truncated["agents"] = len(agent_rows) > _MAX_AGENTS
        agents = [
            {key: _text(row[key], secrets) for key in ("id", "name", "role")}
            for row in agent_rows[:_MAX_AGENTS]
        ]
        turn_rows = connection.execute(
            "SELECT id, agent, input, output, status, created "
            "FROM turns ORDER BY created, id LIMIT ?",
            (_MAX_TURNS + 1,),
        ).fetchall()
        truncated["turns"] = len(turn_rows) > _MAX_TURNS
        turns = [
            {
                key: _text(row[key], secrets)
                for key in ("id", "agent", "input", "output", "status", "created")
            }
            for row in turn_rows[:_MAX_TURNS]
        ]
        workloads = []
        workload_rows = connection.execute(
            "SELECT value FROM workloads ORDER BY rowid LIMIT ?", (_MAX_WORKLOADS + 1,)
        ).fetchall()
        truncated["workloads"] = len(workload_rows) > _MAX_WORKLOADS
        for row in workload_rows[:_MAX_WORKLOADS]:
            work = json.loads(row["value"])
            if not isinstance(work, dict):
                truncated["workloads"] = True
                continue
            calls = work.get("calls")
            decisions = work.get("decisions")
            if isinstance(calls, list) and len(calls) > _MAX_CALLS:
                truncated["calls"] = True
            if isinstance(decisions, list) and len(decisions) > _MAX_DECISIONS:
                truncated["decisions"] = True
            workloads.append(
                {
                    "calls": [
                        _select(
                            call,
                            (
                                "callId",
                                "addressedTo",
                                "causedBy",
                                "activation",
                                "node",
                                "state",
                                "request",
                                "output",
                            ),
                            secrets,
                        )
                        for call in calls[:_MAX_CALLS]
                        if isinstance(call, dict)
                    ]
                    if isinstance(calls, list)
                    else [],
                    "decisions": [
                        _decision(decision, secrets)
                        for decision in decisions[:_MAX_DECISIONS]
                        if isinstance(decision, dict)
                    ]
                    if isinstance(decisions, list)
                    else [],
                }
            )
    snapshot = {
        "agents": agents,
        "turns": turns,
        "workloads": workloads,
        "truncated": truncated,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > _MAX_OUTPUT_BYTES:
        raise ValueError("sapiens_state_too_large")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(encoded)


def _select(
    source: dict[str, object], keys: tuple[str, ...], secrets: tuple[str, ...]
) -> dict[str, object]:
    return {key: _text(source[key], secrets) for key in keys if key in source}


def _decision(source: dict[str, object], secrets: tuple[str, ...]) -> dict[str, object]:
    selected = _select(
        source, ("agent", "node", "callId", "created", "accepted"), secrets
    )
    response = source.get("response")
    if isinstance(response, dict):
        selected["response"] = _select(
            response,
            (
                "event",
                "reason",
                "evidence",
                "reply",
                "question",
                "name",
                "role",
                "request",
            ),
            secrets,
        )
    transition = source.get("transition")
    if isinstance(transition, dict):
        selected["transition"] = _select(
            transition, ("before", "event", "after", "nextNode"), secrets
        )
    return selected


def _text(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return _SECRET.sub("[REDACTED]", value[:_MAX_TEXT])
    if isinstance(value, list):
        return [_text(item, secrets) for item in value[:32] if isinstance(item, str)]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported]"


def _secret_values() -> tuple[str, ...]:
    """Read injected values from the run's private Codex auth source."""
    values = set()
    home = os.environ.get("CODEX_HOME")
    if not home:
        raise ValueError("auth_source_unavailable")
    try:
        with (Path(home) / "auth.json").open("rb") as stream:
            content = stream.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError("auth_source_unavailable")
        pending = [json.loads(content)]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, str) and len(item) >= 16:
                values.add(item)
    except (OSError, ValueError, RecursionError):
        raise ValueError("auth_source_unavailable") from None
    api_key = os.environ.get("OPENAI_API_KEY")
    if api_key:
        values.add(api_key)
    return tuple(sorted(values, key=len, reverse=True))


if __name__ == "__main__":
    write_state_snapshot(Path(sys.argv[1]), Path(sys.argv[2]))
