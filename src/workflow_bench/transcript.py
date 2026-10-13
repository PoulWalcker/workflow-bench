"""Readable, bounded Trial chronology from saved Harbor agent evidence."""

import json
import os
import re
import stat
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from workflow_bench.comparison import SummaryReport, TrialSummary
from workflow_bench.data import DataError, decode_json, read_json

_MAX_SESSION_BYTES = 4 * 1024 * 1024
_MAX_SESSION_COUNT = 256
_MAX_SESSION_ENTRIES = 256
_MAX_SESSION_DEPTH = 8
_MAX_ALL_SESSIONS_BYTES = 32 * 1024 * 1024
_MAX_STATE_BYTES = 4 * 1024 * 1024
_SENSITIVE_VALUE = r"""(?:"[^"]*"|'[^']*'|[^\s,;"'}]+)"""
_SECRET = re.compile(
    r"\b(?:password|secret)\b\s*[\"']?\s*[:=]\s*"
    r"(?:\"[^\"]*(?:\"|$)|'[^']*(?:'|$)|[^\n;]+)"
    r"|(?:\b(?:OPENAI_API_KEY|AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|api[_ -]?key|"
    r"access[_ -]?token|account[_ -]?(?:id|number)|creator_account_id|"
    r"secret|password)\b\s*[\"']?\s*[:=]\s*|"
    r"\baccount[ _-]*(?:id|number)\b\s+is\s+)"
    + _SENSITIVE_VALUE
    + r"|\bAuthorization\s*:\s*Basic\s+[A-Za-z0-9+/=]+"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]+|\bsk-[A-Za-z0-9_-]+"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\b(?:acct|org|usr|user|acc)_[A-Za-z0-9_-]+"
    r"|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)
_NODE = re.compile(r"decision at node ([A-Za-z][A-Za-z0-9_]*)")


class SapiensState(TypedDict):
    """Selected Sapiens chronology; older exports omit truncation metadata."""

    agents: list[dict[str, object]]
    turns: list[dict[str, object]]
    workloads: list[dict[str, object]]
    truncated: NotRequired[dict[str, bool]]


def render_transcripts(summary: SummaryReport, *, full_prompts: bool = False) -> str:
    """Render each completed Trial from saved files without changing its result."""
    sections = [
        render_trial_transcript(
            Path(trial["paths"]["result"]).parent, trial, full_prompts=full_prompts
        )
        for trial in summary["trials"]
    ]
    return "\n\n".join(sections) + ("\n" if sections else "")


def render_trial_transcript(
    trial_dir: Path, summary: TrialSummary, *, full_prompts: bool = False
) -> str:
    """Show one Trial's conversation and independently recorded verifier result."""
    agent_dir = trial_dir / "agent"
    state, state_marker = _read_state(agent_dir / "sapiens-state.json")
    sessions, session_marker = _read_sessions(agent_dir / "sessions")
    is_sapiens = (
        _harness_name(trial_dir) == "sapiens"
        or state is not None
        or bool(sessions and _node_prompt(sessions[0]) is not None)
    )
    names = _agent_names(state)
    lines = [f"# Trial {_safe(summary['trial'])}", ""]
    admin = _admin_task(state, sessions, is_sapiens=is_sapiens)
    lines += [f"Admin task: {_safe(admin) if admin else '[missing: admin task]'}", ""]
    if is_sapiens:
        if state_marker:
            lines.append(f"[missing: Sapiens state ({state_marker})]")
        if state is not None:
            truncated = state.get("truncated", {})
            omitted = sorted(
                key for key, was_truncated in truncated.items() if was_truncated
            )
            if omitted:
                lines.append(
                    "[missing: Sapiens state truncated (" + ", ".join(omitted) + ")]"
                )
        lines += _sapiens_steps(sessions, state, names, full_prompts=full_prompts)
    else:
        lines += _codex_steps(sessions)
    if session_marker:
        lines.append(f"[missing: Codex sessions ({session_marker})]")
    evaluation = summary["evaluation"]
    lines += ["", "## Verifier"]
    if evaluation is None:
        lines.append("Verdict: [missing: evaluation]")
    else:
        lines.append(f"Verdict: {_safe(evaluation['verdict'])}")
        for criterion in evaluation["criteria"]:
            lines.append(
                f"- {_safe(criterion['criterion_id'])}: {_safe(criterion['status'])}"
                f" ({_safe(criterion['reason_code'])})"
            )
    tokens = summary["tokens"]
    session_count = tokens["sessions"]
    if session_count is None:
        session_count = len(sessions) if sessions else None
    lines += [
        "Tokens: "
        + ", ".join(
            f"{tokens[key] if tokens[key] is not None else 'unknown'} {label}"
            for key, label in (
                ("input", "input"),
                ("cached", "cached"),
                ("output", "output"),
            )
        ),
        f"Sessions: {session_count if session_count is not None else 'unknown'}",
    ]
    return "\n".join(lines)


def _read_state(path: Path) -> tuple[SapiensState | None, str | None]:
    if not path.is_file() or path.is_symlink():
        return None, "not collected"
    try:
        content = _bounded_file(path, _MAX_STATE_BYTES)
        if content is None:
            return None, "too large"
        state = decode_json(content, "sapiens-state.json")
    except (OSError, DataError):
        return None, "unreadable"
    if not isinstance(state, dict):
        return None, "invalid"
    for key in ("agents", "turns", "workloads"):
        records = state.get(key)
        if not isinstance(records, list) or not all(
            isinstance(item, dict) for item in records
        ):
            return None, "invalid"
    truncated = state.get("truncated")
    if truncated is not None and (
        not isinstance(truncated, dict)
        or not all(
            key in {"agents", "turns", "workloads", "calls", "decisions"}
            and type(value) is bool
            for key, value in truncated.items()
        )
    ):
        return None, "invalid"
    return cast(SapiensState, state), None


def _harness_name(trial_dir: Path) -> str | None:
    try:
        result = read_json(trial_dir / "result.json", "result")
    except (OSError, DataError):
        return None
    if not isinstance(result, dict):
        return None
    agent_info = result.get("agent_info")
    if not isinstance(agent_info, dict):
        return None
    name = agent_info.get("name")
    return name if isinstance(name, str) else None


def _read_sessions(directory: Path) -> tuple[list[list[dict[str, object]]], str | None]:
    if not directory.is_dir() or directory.is_symlink():
        return [], "not collected"
    try:
        paths, marker = _session_paths(directory)
    except OSError:
        return [], "unreadable"
    if marker:
        return [], marker
    if not paths:
        return [], "empty"
    if len(paths) > _MAX_SESSION_COUNT:
        return [], "too many"
    sessions = []
    total_bytes = 0
    try:
        for path in paths:
            content = _bounded_file(
                path, min(_MAX_SESSION_BYTES, _MAX_ALL_SESSIONS_BYTES - total_bytes)
            )
            if content is None:
                return [], "unsafe or too large"
            total_bytes += len(content)
            rows = [
                decode_json(line, "session")
                for line in content.splitlines()
                if line.strip()
            ]
            if not all(isinstance(row, dict) for row in rows):
                return [], "invalid"
            sessions.append(cast(list[dict[str, object]], rows))
    except (OSError, DataError):
        return [], "unreadable"
    return sorted(
        sessions, key=lambda rows: str(rows[0].get("timestamp", "")) if rows else ""
    ), None


def _bounded_file(path: Path, limit: int) -> bytes | None:
    """Read at most one byte beyond the cap from a regular, singly linked file."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DataError("unsafe_file", path.name)
        content = stream.read(limit + 1)
    return content if len(content) <= limit else None


def _session_paths(directory: Path) -> tuple[list[Path], str | None]:
    """Enumerate a finite session tree, including entries that are not JSONL."""
    paths = []
    stack = [(directory, 0)]
    entries = 0
    while stack:
        parent, depth = stack.pop()
        with os.scandir(parent) as children:
            for child in children:
                entries += 1
                if entries > _MAX_SESSION_ENTRIES:
                    return [], "too many entries"
                if child.is_symlink():
                    return [], "unsafe entry"
                if child.is_dir(follow_symlinks=False):
                    if depth >= _MAX_SESSION_DEPTH:
                        return [], "too deep"
                    stack.append((Path(child.path), depth + 1))
                elif child.name.endswith(".jsonl"):
                    if not child.is_file(follow_symlinks=False):
                        return [], "unsafe entry"
                    paths.append(Path(child.path))
    return sorted(paths), None


def _agent_names(state: SapiensState | None) -> dict[str, str]:
    names: dict[str, str] = {}
    agents = state.get("agents") if state else None
    if isinstance(agents, list):
        for index, agent in enumerate(agents):
            agent_id = agent.get("id")
            name = agent.get("name")
            if isinstance(agent_id, str) and isinstance(name, str):
                names[agent_id] = "Chief" if index == 0 else name
    return names


def _admin_task(
    state: SapiensState | None,
    sessions: list[list[dict[str, object]]],
    *,
    is_sapiens: bool,
) -> str | None:
    if state is not None:
        turns = state.get("turns")
        if isinstance(turns, list):
            for turn in turns:
                admin_input = turn.get("input")
                if isinstance(admin_input, str):
                    return admin_input
    if is_sapiens and sessions:
        prompt = _node_prompt(sessions[0])
        if prompt:
            context = _node_context(prompt)
            intent = context.get("originalIntent")
            if isinstance(intent, str):
                return intent
    if sessions:
        for text in _messages(sessions[0], "user"):
            if (
                not text.startswith("<environment_context>")
                and "decision at node" not in text
            ):
                return text
    return None


def _sapiens_steps(
    sessions: list[list[dict[str, object]]],
    state: SapiensState | None,
    names: dict[str, str],
    *,
    full_prompts: bool,
) -> list[str]:
    lines = ["## Sapiens steps"]
    decisions = _state_decisions(state)
    aligned, unmatched_count = _aligned_decisions(sessions, decisions)
    if not sessions:
        for index, decision in enumerate(decisions, 1):
            agent_id = decision.get("agent")
            speaker = (
                names.get(agent_id, "Unknown Sapi")
                if isinstance(agent_id, str)
                else "Unknown Sapi"
            )
            node = _safe(str(decision.get("node", "unknown node")))
            at = _safe(str(decision.get("created", "[missing: time]")))
            lines += [
                "",
                f"### {index}. {_safe(speaker)} — {node}",
                f"Time: {at}; Tokens: [missing: token count]",
                "[missing: node prompt and Codex session]",
            ]
            response = decision.get("response")
            if isinstance(response, dict):
                lines += _decision_lines(response)
            else:
                lines.append("[missing: assistant decision]")
            transition = decision.get("transition")
            if isinstance(transition, dict):
                lines.append(
                    "Transition: "
                    + _safe(str(transition.get("before", "?")))
                    + " → "
                    + _safe(str(transition.get("after", "?")))
                )
    for index, rows in enumerate(sessions, 1):
        prompt = _node_prompt(rows)
        context = _node_context(prompt or "")
        agent_id = context.get("selfId")
        chief_id = context.get("chiefId")
        speaker = (
            names.get(agent_id, "Chief" if agent_id == chief_id else "Specialist")
            if isinstance(agent_id, str)
            else "Unknown Sapi"
        )
        node = _NODE.search(prompt or "")
        label = node.group(1) if node else "unknown node"
        lines += [
            "",
            f"### {index}. {_safe(speaker)} — {_safe(label)}",
            f"Time: {_time(rows)}; Tokens: {_tokens(rows)}",
        ]
        if prompt:
            if full_prompts:
                lines.append(f"Node prompt ({len(prompt)} chars): {_safe(prompt)}")
            else:
                lines.append(
                    f"Node prompt ({len(prompt)} chars): {_safe(prompt[:160])}…"
                )
        else:
            lines.append("[missing: node prompt]")
        responses = _messages(rows, "assistant")
        response = _decision_response(responses)
        if response:
            lines += _decision_lines(response)
        elif responses:
            lines.append(f"Said: {_safe(responses[-1])}")
        else:
            lines.append("[missing: assistant decision]")
        lines += _tools(rows)
        decision = aligned[index - 1]
        if decision is not None:
            transition = decision.get("transition")
            if isinstance(transition, dict):
                lines.append(
                    "Transition: "
                    + _safe(str(transition.get("before", "?")))
                    + " → "
                    + _safe(str(transition.get("after", "?")))
                )
    if sessions and unmatched_count:
        lines.append(
            f"[missing: Codex session for {unmatched_count} Sapiens decision(s)]"
        )
    if state is not None:
        lines += _delegations(state, names)
        reply = _final_turn_reply(state)
        if reply:
            lines += ["", f"Final reply: {_safe(reply)}"]
        else:
            lines += ["", "Final reply: [missing: turn output]"]
    elif sessions:
        last_response = _decision_response(_messages(sessions[-1], "assistant"))
        reply = last_response.get("reply") if last_response else None
        if isinstance(reply, str) and reply:
            lines += ["", f"Final reply: {_safe(reply)}"]
        else:
            lines += ["", "Final reply: [missing: turn output]"]
        lines.append("[missing: Sapiens delegation and transitions from state]")
    return lines


def _decision_lines(response: dict[str, object]) -> list[str]:
    lines = []
    for key, label in (
        ("event", "Decision"),
        ("reason", "Why"),
        ("evidence", "Evidence"),
        ("reply", "Said"),
        ("question", "Question to Admin"),
        ("name", "Specialist created/selected"),
        ("role", "Specialist role"),
        ("request", "Delegation request"),
    ):
        value = response.get(key)
        if value is not None:
            lines.append(f"{label}: {_safe(_display(value))}")
    return lines


def _codex_steps(sessions: list[list[dict[str, object]]]) -> list[str]:
    lines = ["## Codex conversation"]
    has_final_reply = False
    for index, rows in enumerate(sessions, 1):
        lines += [
            "",
            f"### Session {index}",
            f"Time: {_time(rows)}; Tokens: {_tokens(rows)}",
        ]
        for row in rows:
            payload = row.get("payload")
            if not isinstance(payload, dict) or row.get("type") != "response_item":
                continue
            if payload.get("type") == "message":
                role = payload.get("role")
                if role not in {"user", "assistant"}:
                    continue
                text = _message_text(payload)
                if role == "user" and text.startswith("<environment_context>"):
                    continue
                if payload.get("phase") == "final_answer":
                    title = "Final reply"
                elif role == "user":
                    title = "User"
                else:
                    title = "Assistant"
                has_final_reply = has_final_reply or title == "Final reply"
                at = _safe(str(row.get("timestamp", "unknown time")))
                lines.append(f"- {at} {title}: {_safe(text)}")
            elif payload.get("type") in {"custom_tool_call", "function_call"}:
                at = _safe(str(row.get("timestamp", "unknown time")))
                name = _safe(str(payload.get("name", "?")))
                input_text = _safe(_display(payload.get("input")))[:500]
                lines.append(f"- {at} Tool {name}: {input_text}")
            elif payload.get("type") in {
                "custom_tool_call_output",
                "function_call_output",
            }:
                at = _safe(str(row.get("timestamp", "unknown time")))
                output_text = _safe(_display(payload.get("output")))[:500]
                lines.append(f"- {at} Tool result: {output_text}")
    if not has_final_reply:
        lines.append("Final reply: [missing: final message]")
    return lines


def _node_prompt(rows: list[dict[str, object]]) -> str | None:
    for text in _messages(rows, "user"):
        if _NODE.search(text):
            return text
    return None


def _node_context(prompt: str) -> dict[str, object]:
    _, separator, encoded = prompt.rpartition("\nContext:\n")
    if not separator:
        return {}
    try:
        value = json.loads(encoded)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _messages(rows: list[dict[str, object]], role: str) -> list[str]:
    messages = []
    for row in rows:
        payload = row.get("payload")
        if (
            row.get("type") != "response_item"
            or not isinstance(payload, dict)
            or payload.get("type") != "message"
            or payload.get("role") != role
        ):
            continue
        message = _message_text(payload)
        if message:
            messages.append(message)
    return messages


def _message_text(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item["text"]
        for item in content
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    )


def _decision_response(messages: list[str]) -> dict[str, object] | None:
    for message in reversed(messages):
        try:
            value = json.loads(message)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("event"), str):
            return value
    return None


def _state_decisions(state: SapiensState | None) -> list[dict[str, object]]:
    if state is None or not isinstance(state.get("workloads"), list):
        return []
    workloads = cast(list[object], state["workloads"])
    decisions = []
    for work in workloads:
        if not isinstance(work, dict) or not isinstance(work.get("decisions"), list):
            continue
        decisions.extend(
            decision for decision in work["decisions"] if isinstance(decision, dict)
        )
    return decisions


def _aligned_decisions(
    sessions: list[list[dict[str, object]]], decisions: list[dict[str, object]]
) -> tuple[list[dict[str, object] | None], int]:
    """Attach transitions only where agent/node occurrence counts agree."""
    keys = []
    for rows in sessions:
        prompt = _node_prompt(rows)
        node = _NODE.search(prompt or "")
        agent = _node_context(prompt or "").get("selfId")
        keys.append(
            (agent if isinstance(agent, str) else None, node.group(1) if node else None)
        )
    counts = Counter(keys)
    seen: Counter[tuple[str | None, str | None]] = Counter()
    aligned: list[dict[str, object] | None] = []
    used = set()
    for agent, node in keys:
        key = (agent, node)
        is_only_agent_for_node = (
            sum(1 for _, other_node in keys if other_node == node) == counts[key]
        )
        candidates = [
            index
            for index, decision in enumerate(decisions)
            if node is not None
            and agent is not None
            and decision.get("node") == node
            and (
                decision.get("agent") == agent
                or (decision.get("agent") is None and is_only_agent_for_node)
            )
        ]
        if len(candidates) == counts[key]:
            match = candidates[seen[key]]
            used.add(match)
            aligned.append(decisions[match])
        else:
            aligned.append(None)
        seen[key] += 1
    return aligned, len(decisions) - len(used)


def _delegations(state: SapiensState, names: dict[str, str]) -> list[str]:
    lines = []
    workloads = state.get("workloads")
    if not isinstance(workloads, list):
        return lines
    for work in workloads:
        calls = work.get("calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict) or not call.get("causedBy"):
                continue
            agent_id = call.get("addressedTo")
            speaker = (
                names.get(agent_id, "Specialist")
                if isinstance(agent_id, str)
                else "Specialist"
            )
            request = _safe(str(call.get("request", "[missing: request]")))
            action = (
                "Admin clarification"
                if call.get("activation") == "RequestClarified"
                else f"Delegation to {_safe(speaker)}"
            )
            lines += ["", f"{action}: {request}"]
    is_waiting = False
    for work in workloads:
        calls = work.get("calls")
        if isinstance(calls, list) and any(
            isinstance(call, dict) and call.get("state") == "WaitingForAdmin"
            for call in calls
        ):
            is_waiting = True
            break
    if is_waiting:
        lines.append("WaitingForAdmin: awaiting Admin clarification")
    return lines


def _final_turn_reply(state: SapiensState) -> str | None:
    turns = state.get("turns")
    if not isinstance(turns, list):
        return None
    outputs = []
    for turn in turns:
        output = turn.get("output")
        if isinstance(output, str) and output:
            outputs.append(output)
    return outputs[-1] if outputs else None


def _tools(rows: list[dict[str, object]]) -> list[str]:
    lines = []
    for row in rows:
        payload = row.get("payload")
        if row.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        if payload.get("type") in {"custom_tool_call", "function_call"}:
            name = _safe(str(payload.get("name", "?")))
            input_text = _safe(_display(payload.get("input")))[:500]
            lines.append(f"Tool {name}: {input_text}")
        elif payload.get("type") in {"custom_tool_call_output", "function_call_output"}:
            lines.append(f"Tool result: {_safe(_display(payload.get('output')))[:500]}")
    return lines


def _tokens(rows: list[dict[str, object]]) -> str:
    last = None
    for row in rows:
        payload = row.get("payload")
        if (
            row.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "token_count"
        ):
            info = payload.get("info")
            if isinstance(info, dict) and isinstance(
                info.get("total_token_usage"), dict
            ):
                last = info["total_token_usage"]
    if last is None:
        return "[missing: token count]"
    values = []
    for key, label in (
        ("input_tokens", "input"),
        ("cached_input_tokens", "cached"),
        ("output_tokens", "output"),
    ):
        count = last.get(key)
        values.append(
            f"{count if type(count) is int and count >= 0 else 'unknown'} {label}"
        )
    return ", ".join(values)


def _time(rows: list[dict[str, object]]) -> str:
    timestamps = [
        str(row["timestamp"]) for row in rows if isinstance(row.get("timestamp"), str)
    ]
    if not timestamps:
        return "[missing: time]"
    try:
        start = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        finish = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
        duration = max(0, int((finish - start).total_seconds()))
    except (TypeError, ValueError):
        return "[missing: time]"
    return f"{_safe(timestamps[0])} ({duration}s)"


def _display(value: object, depth: int = 0) -> str:
    if depth >= 8:
        return "[nested data omitted]"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(_display(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return "; ".join(
            f"{key}: {_display(item, depth + 1)}" for key, item in value.items()
        )
    return json.dumps(value, ensure_ascii=False)


def _safe(value: str) -> str:
    return (
        _SECRET.sub("[REDACTED]", value)
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("|", "\\|")
    )
