"""Diagnostic observation-window metrics from saved Trial evidence."""

import math
import re
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypedDict, cast

from workflow_bench.data import DataError, decode_json, read_json
from workflow_bench.pricing import PriceEntry, estimate_cost_usd
from workflow_bench.transcript import SapiensState, read_sapiens_state, read_sessions
from workflow_bench.window import WindowFacts, read_window

if TYPE_CHECKING:
    from workflow_bench.comparison import PairReport

_MAX_COMMANDS = 4096
_MAX_COMMAND_CHARS = 8192
_COMMAND_START = r"(?:^|[;|&\n]\s*|\bsudo\s+)(?:[\w./-]*/)?"
_CRON = re.compile(_COMMAND_START + r"(?:crontab|cron|crond)(?:\s|$)")
_BACKGROUND = re.compile(
    _COMMAND_START + r"(?:nohup|setsid|sleep|python[0-9.]*|bash|sh|while|for)\b"
)
_BACKGROUND_AMPERSAND = re.compile(r"(?<![&>])&(?![&>0-9])")


class WindowMetrics(TypedDict):
    """Driver status and counts; the plan requires a digest-verified Task."""

    status: str
    planned_duration_sec: float | None
    tail_sec: float | None
    actual_duration_sec: float | None
    drops_done: int | None
    drops_planned: int | None
    snapshots_done: int | None
    snapshots_planned: int | None


class ReactionLatency(TypedDict):
    """Seconds from each actual drop until a changed sample, before the next drop."""

    per_drop: list[float | None] | None
    median: float | None


class Mechanism(TypedDict):
    """Observed strategy; counts and minutes apply only to routines."""

    kind: str
    count: int | None
    minutes: list[int] | None


class WindowTokens(TypedDict):
    """Last cumulative usage per post-phase session, including cached input."""

    input: float
    cached: float
    output: float


class RepeatedMetrics(TypedDict):
    """Candidate-reachable diagnostics; null values never imply a measured zero."""

    window: WindowMetrics
    observed_updates: int | None
    reaction_latency_sec: ReactionLatency
    mechanism: Mechanism
    llm_firings: int | None
    window_tokens: WindowTokens | None
    tokens_per_firing: WindowTokens | None
    window_cost_usd: float | None
    cost_per_firing_usd: float | None


class NumericSummary(TypedDict):
    """Median of known Trial values, with unknown Trials counted separately."""

    median: float | None
    known: int
    unknown: int


class PairWindow(TypedDict):
    """Window completion counts and medians for all numeric window fields."""

    completed: int
    statuses: dict[str, int]
    known: int
    unknown: int
    metrics: dict[str, NumericSummary]


class MechanismCounts(TypedDict):
    """Observed strategies among known Trials; absence of evidence is unknown."""

    counts: dict[str, int]
    known: int
    unknown: int


class PairTokens(TypedDict):
    """Per-component medians of validated usage or usage per firing."""

    input: NumericSummary
    cached: NumericSummary
    output: NumericSummary


class PairRepeated(TypedDict):
    """Pair diagnostics over every Trial, including those lacking window evidence."""

    trials: int
    window: PairWindow
    observed_updates: NumericSummary
    reaction_latency_sec: NumericSummary
    mechanism: MechanismCounts
    llm_firings: NumericSummary
    window_tokens: PairTokens
    tokens_per_firing: PairTokens
    window_cost_usd: NumericSummary
    cost_per_firing_usd: NumericSummary


class _Plan(TypedDict):
    duration_sec: float
    tail_sec: float
    drops: int
    snapshots: int


def measure_repeated(
    trial_dir: Path,
    finished_at: datetime | None,
    schedule_path: Path | None,
    rates: PriceEntry | None = None,
) -> RepeatedMetrics | None:
    """Read collected window diagnostics, or None without window evidence.

    ``schedule_path`` must belong to the Task whose Harbor digest was verified
    by the caller. Absent or invalid plans leave plan-dependent metrics unknown.
    Native agent-phase measurements and verdicts are never changed.
    """
    evidence = trial_dir / "artifacts/window-evidence"
    if not evidence.exists() and not evidence.is_symlink():
        return None
    metrics: RepeatedMetrics = {
        "window": {
            "status": "invalid",
            "planned_duration_sec": None,
            "tail_sec": None,
            "actual_duration_sec": None,
            "drops_done": None,
            "drops_planned": None,
            "snapshots_done": None,
            "snapshots_planned": None,
        },
        "observed_updates": None,
        "reaction_latency_sec": {"per_drop": None, "median": None},
        "mechanism": {"kind": "unknown", "count": None, "minutes": None},
        "llm_firings": None,
        "window_tokens": None,
        "tokens_per_firing": None,
        "window_cost_usd": None,
        "cost_per_firing_usd": None,
    }
    try:
        facts = read_window(evidence)
    except DataError as error:
        metrics["window"]["status"] = (
            "too large" if error.code == "too_large" else "invalid"
        )
        return metrics
    except OSError:
        return metrics
    window = metrics["window"]
    window["status"] = facts.status
    if facts.status == "not_started":
        return metrics
    window["actual_duration_sec"] = facts.elapsed_sec
    window["drops_done"] = len(facts.drops)
    window["snapshots_done"] = len(facts.snapshots)
    plan = _read_plan(schedule_path)
    if plan is not None:
        window["planned_duration_sec"] = plan["duration_sec"]
        window["tail_sec"] = plan["tail_sec"]
        window["drops_planned"] = plan["drops"]
        window["snapshots_planned"] = plan["snapshots"]
        changes = _changed_offsets(facts, plan["duration_sec"] + plan["tail_sec"])
        if changes is not None:
            metrics["observed_updates"] = len(changes)
            metrics["reaction_latency_sec"] = _reaction_latency(
                facts, changes, plan["duration_sec"] + plan["tail_sec"]
            )
    _PostPhaseUsage(trial_dir, finished_at).add_to(metrics, rates)
    return metrics


def aggregate_repeated(values: Sequence[RepeatedMetrics | None]) -> PairRepeated | None:
    """Aggregate window diagnostics, or None if no Trial saved window evidence."""
    if not any(value is not None for value in values):
        return None
    statuses: dict[str, int] = {}
    mechanisms: dict[str, int] = {}
    for value in values:
        if value is None:
            continue
        status = value["window"]["status"]
        statuses[status] = statuses.get(status, 0) + 1
        kind = value["mechanism"]["kind"]
        if kind != "unknown":
            mechanisms[kind] = mechanisms.get(kind, 0) + 1
    window_fields = (
        "planned_duration_sec",
        "tail_sec",
        "actual_duration_sec",
        "drops_done",
        "drops_planned",
        "snapshots_done",
        "snapshots_planned",
    )
    window_metrics = {}
    for field in window_fields:
        window_metrics[field] = _numeric_summary(
            [None if value is None else value["window"][field] for value in values]
        )
    known_status = sum(
        count
        for status, count in statuses.items()
        if status not in {"invalid", "too large"}
    )
    return {
        "trials": len(values),
        "window": {
            "completed": statuses.get("completed", 0),
            "statuses": dict(sorted(statuses.items())),
            "known": known_status,
            "unknown": len(values) - known_status,
            "metrics": window_metrics,
        },
        "observed_updates": _numeric_summary(
            [None if v is None else v["observed_updates"] for v in values]
        ),
        "reaction_latency_sec": _numeric_summary(
            [None if v is None else v["reaction_latency_sec"]["median"] for v in values]
        ),
        "mechanism": {
            "counts": dict(sorted(mechanisms.items())),
            "known": sum(mechanisms.values()),
            "unknown": len(values) - sum(mechanisms.values()),
        },
        "llm_firings": _numeric_summary(
            [None if v is None else v["llm_firings"] for v in values]
        ),
        "window_tokens": _aggregate_tokens(values, "window_tokens"),
        "tokens_per_firing": _aggregate_tokens(values, "tokens_per_firing"),
        "window_cost_usd": _numeric_summary(
            [None if v is None else v["window_cost_usd"] for v in values]
        ),
        "cost_per_firing_usd": _numeric_summary(
            [None if v is None else v["cost_per_firing_usd"] for v in values]
        ),
    }


def render_observation_window(pairs: Sequence["PairReport"]) -> list[str]:
    """Return conditional Markdown tables and evidence limitations for repeated jobs."""
    repeated_pairs = [pair for pair in pairs if pair["repeated"] is not None]
    if not repeated_pairs:
        return []
    lines = [
        "",
        "## Observation window",
        "",
        "Harbor's token and agent time columns cover the agent phase only.",
        (
            "Window evidence is produced inside the agent environment "
            "(candidate-reachable, diagnostic); it does not establish "
            "complete or untampered evidence."
        ),
        "Codex window LLM usage is not observable in its agent logs.",
        (
            "Plans come from the digest-verified Task environment/schedule.json; "
            "missing or changed Tasks leave plan-dependent metrics unknown."
        ),
        "Table medians exclude unknown values; unknown counts appear separately.",
        "",
        (
            "| Task | Configuration | Window completed | Median updates | "
            "Median latency s | Mechanism | Median firings | "
            "Median window tokens in / cached / out | Median tokens per firing | "
            "Median window cost USD | Median cost per firing USD |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    has_routine = False
    for pair in repeated_pairs:
        metrics = pair["repeated"]
        if metrics is None:
            continue
        mechanisms = metrics["mechanism"]
        descriptions = [
            f"{kind} {count} of {metrics['trials']}"
            for kind, count in mechanisms["counts"].items()
        ]
        if mechanisms["unknown"]:
            descriptions.append(f"unknown {mechanisms['unknown']}")
        has_routine |= "routine" in mechanisms["counts"]
        config = pair["configuration"]
        configuration = "; ".join(
            f"{key}={value if value is not None else 'unknown'}"
            for key, value in config.items()
        )
        cells = [
            f"{pair['task']} ({pair['task_checksum']})",
            configuration,
            f"{metrics['window']['completed']}/{metrics['trials']}",
            _summary_text(metrics["observed_updates"]),
            _summary_text(metrics["reaction_latency_sec"]),
            ", ".join(descriptions),
            _summary_text(metrics["llm_firings"]),
            _pair_tokens_text(metrics["window_tokens"]),
            _pair_tokens_text(metrics["tokens_per_firing"]),
            _summary_text(metrics["window_cost_usd"]),
            _summary_text(metrics["cost_per_firing_usd"]),
        ]
        lines.append(_table_row(cells))
    if has_routine:
        lines += [
            "",
            "in the current Sapiens, repetition is only via an LLM call per tick",
        ]
    lines += [
        "",
        "### Per Trial",
        "",
        (
            "| Job | Trial | Window status | Duration planned / actual s | "
            "Drops done / planned | Snapshots done / planned | Updates | "
            "Latency s per drop / median | Mechanism | LLM firings | "
            "Window tokens in / cached / out | Tokens per firing | "
            "Window cost USD | Cost per firing USD |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for pair in repeated_pairs:
        for trial in pair["trials"]:
            value = trial["repeated"]
            if value is None:
                lines.append(
                    _table_row(
                        [trial["job"], trial["trial"], "no evidence"] + ["unknown"] * 11
                    )
                )
                continue
            window = value["window"]
            latency = value["reaction_latency_sec"]
            per_drop = latency["per_drop"]
            latencies = (
                "unknown"
                if per_drop is None
                else ", ".join(_number_text(v) for v in per_drop)
            )
            mechanism = value["mechanism"]
            mechanism_text = mechanism["kind"]
            if mechanism["kind"] == "routine":
                mechanism_text += (
                    f" ({mechanism['count']}; minutes={mechanism['minutes']})"
                )
            cells = [
                trial["job"],
                trial["trial"],
                window["status"],
                (
                    f"{_number_text(window['planned_duration_sec'])} / "
                    f"{_number_text(window['actual_duration_sec'])}"
                ),
                (
                    f"{_number_text(window['drops_done'])} / "
                    f"{_number_text(window['drops_planned'])}"
                ),
                (
                    f"{_number_text(window['snapshots_done'])} / "
                    f"{_number_text(window['snapshots_planned'])}"
                ),
                _number_text(value["observed_updates"]),
                f"{latencies} / {_number_text(latency['median'])}",
                mechanism_text,
                _number_text(value["llm_firings"]),
                _tokens_text(value["window_tokens"]),
                _tokens_text(value["tokens_per_firing"]),
                _number_text(value["window_cost_usd"]),
                _number_text(value["cost_per_firing_usd"]),
            ]
            lines.append(_table_row(cells))
    return lines


def _number_text(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.6g}"


def _summary_text(value: NumericSummary) -> str:
    text = _number_text(value["median"])
    if value["unknown"]:
        text += f" (unknown {value['unknown']})"
    return text


def _tokens_text(tokens: WindowTokens | None) -> str:
    if tokens is None:
        return "unknown"
    return " / ".join(
        _number_text(tokens[key]) for key in ("input", "cached", "output")
    )


def _pair_tokens_text(tokens: PairTokens) -> str:
    return " / ".join(
        _summary_text(tokens[key]) for key in ("input", "cached", "output")
    )


def _table_row(cells: Sequence[str]) -> str:
    return (
        "| "
        + " | ".join(cell.replace("|", r"\|").replace("\n", " ") for cell in cells)
        + " |"
    )


def _numeric_summary(values: Sequence[float | None]) -> NumericSummary:
    known = [value for value in values if value is not None]
    return {
        "median": statistics.median(known) if known else None,
        "known": len(known),
        "unknown": len(values) - len(known),
    }


def _aggregate_tokens(
    values: Sequence[RepeatedMetrics | None],
    field: Literal["window_tokens", "tokens_per_firing"],
) -> PairTokens:
    tokens = [None if value is None else value[field] for value in values]
    return {
        "input": _numeric_summary(
            [None if token is None else token["input"] for token in tokens]
        ),
        "cached": _numeric_summary(
            [None if token is None else token["cached"] for token in tokens]
        ),
        "output": _numeric_summary(
            [None if token is None else token["output"] for token in tokens]
        ),
    }


class _PostPhaseUsage:
    """Own validated saved state and sessions for one post-phase measurement."""

    def __init__(self, trial_dir: Path, finished_at: datetime | None) -> None:
        state_path = trial_dir / "agent/sapiens-state.json"
        self.has_state_source = state_path.exists() or state_path.is_symlink()
        self.state, self.state_marker = read_sapiens_state(state_path)
        self.sessions, self.session_marker = read_sessions(trial_dir / "agent/sessions")
        self.finished_at = finished_at

    def add_to(self, metrics: RepeatedMetrics, rates: PriceEntry | None) -> None:
        """Attach independently observable mechanism, firings and window usage."""
        state = self.state
        if state is None:
            if self.state_marker == "not collected" and not self.has_state_source:
                metrics["mechanism"]["kind"] = self._command_mechanism()
            return
        if self.state_marker is not None or any(state.get("truncated", {}).values()):
            return
        routines = state.get("routines", [])
        if not isinstance(routines, list):
            return
        minutes = []
        for routine in routines:
            if (
                not isinstance(routine, dict)
                or not isinstance(routine.get("id"), str)
                or type(routine.get("minutes")) is not int
                or not 1 <= cast(int, routine["minutes"]) <= 525600
            ):
                return
            minutes.append(cast(int, routine["minutes"]))
        if routines:
            metrics["mechanism"] = {
                "kind": "routine",
                "count": len(routines),
                "minutes": sorted(minutes),
            }
        else:
            metrics["mechanism"]["kind"] = self._command_mechanism()
        if self.finished_at is None or self.finished_at.tzinfo is None:
            return
        metrics["llm_firings"] = self._firings(state)
        tokens = self._tokens()
        metrics["window_tokens"] = tokens
        firings = metrics["llm_firings"]
        if tokens is not None:
            if rates is not None:
                metrics["window_cost_usd"] = estimate_cost_usd(
                    int(tokens["input"]),
                    int(tokens["cached"]),
                    int(tokens["output"]),
                    rates,
                )
            if firings is not None and firings > 0:
                metrics["tokens_per_firing"] = {
                    "input": tokens["input"] / firings,
                    "cached": tokens["cached"] / firings,
                    "output": tokens["output"] / firings,
                }
                cost = metrics["window_cost_usd"]
                if cost is not None:
                    metrics["cost_per_firing_usd"] = cost / firings

    def _firings(self, state: SapiensState) -> int | None:
        # Turns retain creation timestamps; workloads in the export lack ids and
        # creation times. Prefer turns to avoid counting matching workloads twice.
        if self.finished_at is None:
            return None
        turns = [turn for turn in state["turns"] if _is_routine_origin(turn)]
        records = turns or [
            work for work in state["workloads"] if _is_routine_origin(work)
        ]
        started = []
        for record in records:
            timestamp = _timestamp(record.get("created"))
            if timestamp is None:
                return None
            started.append(timestamp)
        return sum(value > self.finished_at for value in started)

    def _tokens(self) -> WindowTokens | None:
        if self.session_marker is not None or self.finished_at is None:
            return None
        total: WindowTokens = {"input": 0, "cached": 0, "output": 0}
        for rows in self.sessions:
            if not rows:
                return None
            first = _timestamp(rows[0].get("timestamp"))
            if first is None:
                return None
            if first <= self.finished_at:
                continue
            cumulative = None
            for row in rows:
                payload = row.get("payload")
                if (
                    not isinstance(payload, dict)
                    or payload.get("type") != "token_count"
                ):
                    continue
                info = payload.get("info")
                counts = (
                    info.get("total_token_usage") if isinstance(info, dict) else None
                )
                if not isinstance(counts, dict):
                    return None
                values = [
                    counts.get(key)
                    for key in ("input_tokens", "cached_input_tokens", "output_tokens")
                ]
                if any(
                    type(value) is not int or not 0 <= value <= 2**63 - 1
                    for value in values
                ):
                    return None
                if values[1] > values[0]:
                    return None
                cumulative = cast(tuple[int, int, int], tuple(values))
            if cumulative is None:
                return None
            total["input"] += cumulative[0]
            total["cached"] += cumulative[1]
            total["output"] += cumulative[2]
        return total

    def _command_mechanism(self) -> str:
        if self.session_marker is not None:
            return "unknown"
        count = 0
        has_background = False
        has_cron = False
        for rows in self.sessions:
            if not rows:
                return "unknown"
            for row in rows:
                payload = row.get("payload")
                if (
                    not isinstance(payload, dict)
                    or payload.get("type") != "function_call"
                ):
                    continue
                name = payload.get("name")
                if not isinstance(name, str) or name.split(".")[-1] not in {
                    "exec_command",
                    "shell",
                    "shell_command",
                }:
                    continue
                arguments = payload.get("arguments")
                if (
                    not isinstance(arguments, str)
                    or len(arguments) > _MAX_COMMAND_CHARS
                ):
                    return "unknown"
                try:
                    parsed = decode_json(arguments.encode("utf-8"), "command")
                except (DataError, UnicodeError):
                    return "unknown"
                if not isinstance(parsed, dict):
                    return "unknown"
                command = parsed.get("cmd", parsed.get("command"))
                if isinstance(command, list) and all(
                    isinstance(part, str) for part in command
                ):
                    command = " ".join(cast(list[str], command))
                if not isinstance(command, str) or len(command) > _MAX_COMMAND_CHARS:
                    return "unknown"
                count += 1
                if count > _MAX_COMMANDS:
                    return "unknown"
                has_cron |= _CRON.search(command) is not None
                has_background |= (
                    _BACKGROUND.search(command) is not None
                    and _BACKGROUND_AMPERSAND.search(command) is not None
                )
        if has_cron:
            return "cron"
        return "background_process" if has_background else "none_observed"


def _is_routine_origin(record: Mapping[str, object]) -> bool:
    origin = record.get("origin")
    return (
        isinstance(origin, dict)
        and isinstance(origin.get("routine"), str)
        and bool(origin["routine"])
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _read_plan(path: Path | None) -> _Plan | None:
    if path is None:
        return None
    try:
        plan = read_json(path, "schedule")
    except (OSError, DataError):
        return None
    if not isinstance(plan, dict):
        return None
    duration = plan.get("duration_sec")
    tail = plan.get("tail_sec")
    if not _bounded_number(duration, 3600) or not _bounded_number(tail, 600):
        return None
    duration = cast(float, duration)
    tail = cast(float, tail)
    drops = plan.get("drops")
    snapshots = plan.get("snapshots")
    if not isinstance(drops, list) or not isinstance(snapshots, list):
        return None
    if len(drops) > 128 or len(snapshots) > 128:
        return None
    for action in drops + snapshots:
        if not isinstance(action, dict) or not _bounded_number(
            action.get("at_sec"), duration
        ):
            return None
    return {
        "duration_sec": float(duration),
        "tail_sec": float(tail),
        "drops": len(drops),
        "snapshots": len(snapshots),
    }


def _bounded_number(value: object, maximum: float) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(cast(float, value))
        and 0 <= cast(float, value) <= maximum
    )


def _changed_offsets(facts: WindowFacts, end_sec: float) -> list[float] | None:
    previous: dict[str, str | None] | None = None
    changes = []
    for sample in sorted(facts.samples, key=lambda item: item.actual_offset_sec):
        if sample.actual_offset_sec > end_sec:
            continue
        digests = {}
        for path, observation in sample.paths.items():
            if observation["state"] not in {"regular", "directory", "missing"}:
                return None
            if observation["state"] != "missing" and observation["sha256"] is None:
                return None
            digests[path] = observation["sha256"]
        if previous is not None:
            if set(previous) != set(digests):
                return None
            if digests != previous:
                changes.append(sample.actual_offset_sec)
        previous = digests
    return changes if previous is not None else None


def _reaction_latency(
    facts: WindowFacts, changes: Sequence[float], end_sec: float
) -> ReactionLatency:
    drops = sorted(facts.drops, key=lambda item: item.actual_offset_sec)
    latencies = []
    for index, drop in enumerate(drops):
        next_drop = (
            drops[index + 1].actual_offset_sec if index + 1 < len(drops) else None
        )
        changed = next(
            (
                offset
                for offset in changes
                if drop.actual_offset_sec <= offset <= end_sec
                and (next_drop is None or offset < next_drop)
            ),
            None,
        )
        latencies.append(None if changed is None else changed - drop.actual_offset_sec)
    known = [value for value in latencies if value is not None]
    return {
        "per_drop": latencies,
        "median": statistics.median(known) if known else None,
    }
