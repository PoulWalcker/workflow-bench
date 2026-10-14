"""Offline report of Trial outcomes per task and configuration from Harbor job dirs."""

import logging
import math
import statistics
import time
import tomllib
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Literal, TypedDict, cast

from harbor.models.agent.context import AgentContext
from harbor.models.job.config import JobConfig
from harbor.models.task.config import VerifierEnvironmentMode
from harbor.models.trial.artifact_manifest import ArtifactManifest
from harbor.models.trial.result import TimingInfo, TrialResult
from harbor.publisher.packager import Packager

from workflow_bench.contracts import Evaluation
from workflow_bench.data import DataError, read_bytes, read_json, validate_contract
from workflow_bench.transcript import read_sessions

LOGGER = logging.getLogger(__name__)

type Outcome = Literal["pass", "fail", "unknown", "infra_error"]
# Sortable identity; an optional part is (known, value) so unknown sorts first.
type _Key = tuple[str | tuple[bool, str], ...]


class Configuration(TypedDict):
    """What a Trial measured besides the task.

    Attributes:
        model: ``provider/name`` as Harbor recorded it, or None without a model.
        reasoning: Reasoning effort from the agent's native options, or None
            when the job did not record one.
        reasoning_summary: Requested setting from inline config or native option;
            None when unrecorded.
        web_search: Inline native setting, or None when unrecorded.
    """

    harness: str
    harness_version: str
    model: str | None
    reasoning: str | None
    reasoning_summary: str | None
    web_search: str | None


class TrialOutcome(TypedDict):
    """The one outcome class of one Trial.

    Attributes:
        reason: Safe code for an ``infra_error``; None for a verdict.
        exception: Harbor's recorded exception type, kept as a fact even when
            the outcome is a verdict (an agent timeout is judged by its state).
    """

    job: str
    trial: str
    outcome: Outcome
    reason: str | None
    exception: str | None


# Functional form: ``pass`` is a Python keyword.
OutcomeCounts = TypedDict(
    "OutcomeCounts",
    {"trials": int, "pass": int, "fail": int, "unknown": int, "infra_error": int},
)


class Median(TypedDict):
    """Median over the Trials where the metric is known.

    Attributes:
        median: None when no Trial of the pair recorded the metric.
        known: Number of Trials whose value entered the median.
    """

    median: float | None
    known: int


class PairReport(TypedDict):
    """Metrics of one (task, configuration) pair.

    Attributes:
        counts: Number of Trials, in total and per outcome class.
        pass_rate: ``pass / (pass + fail)``; None without a known outcome.
        unknown_rate: ``unknown / trials``.
        infra_error_rate: ``infra_error / trials``.
        agent_sec: Duration of the agent's execution phase, over every Trial
            of the pair, whatever its outcome.
        input_tokens: Input tokens including cached ones, as Harbor records.
        session_count: Original Harbor Sapiens metadata median, retained for v0.
        sessions: Median from readable Codex sessions, falling back to validated
            Harbor session metadata when sessions are unavailable.
        session_efforts: Number of sessions observing each effort value; a
            session may contribute to more than one value if effort changed.
        session_evidence_missing_trials: Trials whose session files could not
            be read; their effort and summary presence are not inferred as zero.
    """

    task: str
    task_checksum: str
    configuration: Configuration
    counts: OutcomeCounts
    pass_rate: float | None
    unknown_rate: float
    infra_error_rate: float
    agent_sec: Median
    input_tokens: Median
    cached_tokens: Median
    output_tokens: Median
    session_count: Median
    sessions: Median
    trials: list[TrialOutcome]
    valid: int
    pass_hat_k: float | None
    failed_criteria: dict[str, dict[str, int]]
    session_efforts: dict[str, int]
    xhigh_sessions: int
    unknown_effort_sessions: int
    sessions_with_summary: int
    session_evidence_missing_trials: int
    level: str


class IncompleteTrial(TypedDict):
    """A Trial directory without a readable Harbor result: running or killed."""

    job: str
    trial: str
    reason: str


class TaskComparison(TypedDict):
    """A task's equal-condition decision across configurations."""

    task: str
    status: Literal["comparable", "incomparable"]
    reasons: list[str]


class LevelReport(TypedDict):
    """Coverage and outcomes for one configuration at one verified level."""

    configuration: Configuration
    level: str
    tasks: int
    covered_tasks: int
    mean_pass_rate: float | None
    unknown: int
    infra_error: int
    failed_criteria: dict[str, dict[str, int]]


class ComparisonReport(TypedDict):
    """Per-pair metrics, condition decisions and level summaries from saved jobs."""

    pairs: list[PairReport]
    incomplete_trials: list[IncompleteTrial]
    pass_hat_k: int
    comparisons: list[TaskComparison]
    levels: list[LevelReport]


class PhaseSummary(TypedDict):
    """A native phase's UTC start, elapsed seconds and observed timing state."""

    started_at: str | None
    duration_seconds: float | None
    status: Literal["not_started", "started", "finished"]


class ManifestEntrySummary(TypedDict):
    """One collected destination and Harbor's recorded collection status."""

    destination: str
    status: str


class ManifestSummary(TypedDict):
    """Manifest validity and collection states without artifact contents."""

    status: Literal["missing", "invalid", "failed", "ok"]
    entries: list[ManifestEntrySummary]


class TrialPhases(TypedDict):
    """The timing state of each native Harbor Trial phase."""

    environment_setup: PhaseSummary
    agent_setup: PhaseSummary
    agent_execution: PhaseSummary
    verifier: PhaseSummary


class TrialTokens(TypedDict):
    """Native agent token counts, or None when unrecorded."""

    input: int | None
    cached: int | None
    output: int | None
    sessions: int | None


class TrialPaths(TypedDict):
    """Locations of the native files and directories used to diagnose a Trial."""

    result: str
    evaluation: str
    reward: str
    artifact_manifest: str
    trial_log: str
    verifier_stdout: str
    agent_logs: str


class TrialSummary(TypedDict):
    """Diagnostic facts with the report outcome and safe error codes/types.

    Native exception messages remain in ``result.json`` because they can
    contain private data.
    """

    job: str
    trial: str
    outcome: Outcome
    reason: str | None
    exception: str | None
    phases: TrialPhases
    evaluation: Evaluation | None
    errors: list[str]
    tokens: TrialTokens
    artifact_manifest: ManifestSummary
    paths: TrialPaths


class SummaryReport(TypedDict):
    """Per-Trial diagnostics and incomplete Trials from the same comparison."""

    trials: list[TrialSummary]
    incomplete_trials: list[IncompleteTrial]


@dataclass(frozen=True)
class _Trial:
    task: str
    task_checksum: str
    configuration: Configuration
    outcome: TrialOutcome
    agent_sec: float | None
    input_tokens: int | None
    cached_tokens: int | None
    output_tokens: int | None
    session_count: int | None
    effective_session_count: int | None
    failed_criteria: dict[str, dict[str, int]]
    session_efforts: dict[str, int]
    unknown_effort_sessions: int
    sessions_with_summary: int
    has_session_evidence: bool
    level: str
    task_digest: str | None
    agent_timeout_sec: float | None
    agent_network: tuple[str, ...] | None


@dataclass(frozen=True)
class _SessionObservations:
    """Counts from bounded saved sessions, with None count when unreadable."""

    count: int | None
    efforts: dict[str, int]
    unknown_effort: int
    with_summary: int
    has_evidence: bool


@dataclass(frozen=True)
class _RecordedConditions:
    """Selected native Trial-lock facts before task-directory verification."""

    task_digest: str | None
    task_path: Path | None
    override_timeout_sec: float | None
    extra_allowed_hosts: tuple[str, ...] | None


@dataclass(frozen=True)
class _EffectiveConditions:
    """Comparable conditions and level after the task digest check."""

    level: str
    task_digest: str | None
    agent_timeout_sec: float | None
    agent_network: tuple[str, ...] | None


def compare(job_dirs: Sequence[Path]) -> ComparisonReport:
    """Return the report of every Trial in the given Harbor job directories.

    Reads only native files; the same files give the same report. Every
    subdirectory of a job directory is a Trial, as Harbor lays them out; one
    without a readable ``result.json`` is listed as incomplete, outside the
    pairs.

    Raises:
        DataError: A directory is not a Harbor job directory
            (``not_a_harbor_job``).
    """
    LOGGER.info("phase=compare jobs=%d status=started", len(job_dirs))
    started = time.monotonic()
    trials: list[_Trial] = []
    incomplete: list[IncompleteTrial] = []
    for job_dir in job_dirs:
        _check_job_dir(job_dir)
        for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
            try:
                result = _read_result(trial_dir)
            except DataError as error:
                LOGGER.warning(
                    "phase=compare job=%s trial=%s status=incomplete reason=%s",
                    job_dir.name,
                    trial_dir.name,
                    error.code,
                )
                incomplete.append(
                    {"job": job_dir.name, "trial": trial_dir.name, "reason": error.code}
                )
                continue
            trials.append(_measure_trial(job_dir.name, trial_dir, result))
    groups: dict[_Key, list[_Trial]] = {}
    for trial in trials:
        groups.setdefault(_pair_key(trial), []).append(trial)
    pairs = [_pair_report(groups[key]) for key in sorted(groups)]
    LOGGER.info(
        "phase=compare jobs=%d trials=%d incomplete=%d status=finished "
        "duration_sec=%.1f",
        len(job_dirs),
        len(trials),
        len(incomplete),
        time.monotonic() - started,
    )
    return {
        "pairs": pairs,
        "incomplete_trials": incomplete,
        "pass_hat_k": 3,
        "comparisons": _comparison_reports(trials),
        "levels": _level_reports(trials),
    }


def summarize(job_dirs: Sequence[Path], report: ComparisonReport) -> SummaryReport:
    """Return native Trial diagnostics using classifications from ``report``.

    The caller supplies the report from ``compare`` over the same saved jobs.
    This mode reads files but never writes or evaluates a Trial.
    """
    outcomes: dict[tuple[_Key, str, str], deque[TrialOutcome]] = {}
    for pair in report["pairs"]:
        pair_key = (
            pair["task"],
            pair["task_checksum"],
            *_configuration_key(pair["configuration"]),
        )
        for trial in pair["trials"]:
            key = (pair_key, trial["job"], trial["trial"])
            outcomes.setdefault(key, deque()).append(trial)
    summaries = []
    for job_dir in job_dirs:
        for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
            try:
                result = _read_result(trial_dir)
            except DataError:
                continue
            pair_key = (
                result.task_name,
                result.task_checksum,
                *_configuration_key(_configuration(result)),
            )
            matching_outcomes = outcomes.get((pair_key, job_dir.name, trial_dir.name))
            if not matching_outcomes:
                continue
            outcome = matching_outcomes.popleft()
            summaries.append(_summarize_trial(trial_dir, outcome, result))
    return {"trials": summaries, "incomplete_trials": report["incomplete_trials"]}


def render_markdown(report: ComparisonReport) -> str:
    """Return the report as Markdown: one task table per configuration.

    Per-Trial outcomes stay in the JSON report; unknown metrics print as
    ``unknown``.
    """
    sections: dict[_Key, list[PairReport]] = {}
    for pair in report["pairs"]:
        sections.setdefault(_configuration_key(pair["configuration"]), []).append(pair)
    lines = [
        "# Workflow Bench report",
        "",
        "Pass^3 (k=3) = C(pass, 3) / C(valid, 3); unknown when valid < 3.",
    ]
    for key in sorted(sections):
        pairs = sections[key]
        lines += ["", f"## {_configuration_title(pairs[0]['configuration'])}", ""]
        headers = [
            "Task",
            "Checksum",
            "Trials",
            "Pass/valid",
            "Fail",
            "Unknown",
            "Infra error",
            "Pass rate",
            "Pass^3 (k=3)",
            "Failed criteria",
            "Median agent s",
            "Median tokens in / cached / out",
            "Median sessions",
            "Base effort",
            "xhigh sessions",
            "Sessions with summary",
        ]
        lines += [
            f"| {' | '.join(headers)} |",
            f"| {' | '.join('---' for _ in headers)} |",
        ]
        lines += [_markdown_row(pair) for pair in pairs]
    if report["comparisons"]:
        lines += [
            "",
            "## Comparison",
            "",
            "| Task | Status | Reasons |",
            "|---|---|---|",
        ]
        for comparison in report["comparisons"]:
            reasons = comparison["reasons"]
            reason_text = ", ".join(reasons) if reasons else "—"
            lines.append(
                f"| {comparison['task']} | {comparison['status']} | {reason_text} |"
            )
    lines += [
        "",
        "## Per-level summary",
        "",
        (
            "| Configuration | Level | Tasks | Covered tasks | Mean pass rate | "
            "Unknown | Infra error | Failed criteria |"
        ),
        "|---|---|---|---|---|---|---|---|",
    ]
    for level in report["levels"]:
        rate = level["mean_pass_rate"]
        rate_text = "unknown" if rate is None else f"{rate:.2f}"
        lines.append(
            f"| {_configuration_title(level['configuration'])} | {level['level']} "
            f"| {level['tasks']} | {level['covered_tasks']} | {rate_text} "
            f"| {level['unknown']} | {level['infra_error']} "
            f"| {_format_failed_criteria(level['failed_criteria'])} |"
        )
    if report["incomplete_trials"]:
        lines += ["", "## Incomplete trials", "", "| Job | Trial | Reason |"]
        lines.append("|---|---|---|")
        lines += [
            f"| {trial['job']} | {trial['trial']} | {trial['reason']} |"
            for trial in report["incomplete_trials"]
        ]
    return "\n".join(lines) + "\n"


def read_evaluation(path: Path) -> Evaluation:
    """Return the verifier's ``evaluation.json`` after contract validation.

    Raises:
        OSError: The file is missing or unreadable.
        DataError: It is unsafe, too large or violates the contract.
    """
    document = read_json(path, "evaluation")
    validate_contract("evaluation", document)
    return cast(Evaluation, document)


def _summarize_trial(
    trial_dir: Path, outcome: TrialOutcome, result: TrialResult
) -> TrialSummary:
    evaluation_path = trial_dir / "verifier" / "evaluation.json"
    try:
        evaluation = read_evaluation(evaluation_path)
    except (OSError, DataError):
        evaluation = None
    usage = result.agent_result
    paths: TrialPaths = {
        "result": str(trial_dir / "result.json"),
        "evaluation": str(evaluation_path),
        "reward": str(trial_dir / "verifier" / "reward.json"),
        "artifact_manifest": str(trial_dir / "artifacts" / "manifest.json"),
        "trial_log": str(trial_dir / "trial.log"),
        "verifier_stdout": str(trial_dir / "verifier" / "test-stdout.txt"),
        "agent_logs": str(trial_dir / "agent"),
    }
    return {
        **outcome,
        "phases": {
            "environment_setup": _phase_summary(result.environment_setup),
            "agent_setup": _phase_summary(result.agent_setup),
            "agent_execution": _phase_summary(result.agent_execution),
            "verifier": _phase_summary(result.verifier),
        },
        "evaluation": evaluation,
        "errors": ([outcome["reason"]] if outcome["reason"] is not None else [])
        + ([outcome["exception"]] if outcome["exception"] is not None else [])
        + ([] if evaluation is None else evaluation["errors"]),
        "tokens": {
            "input": None if usage is None else usage.n_input_tokens,
            "cached": None if usage is None else usage.n_cache_tokens,
            "output": None if usage is None else usage.n_output_tokens,
            "sessions": _reported_session_count(usage),
        },
        "artifact_manifest": _manifest_summary(trial_dir),
        "paths": paths,
    }


def _phase_summary(timing: TimingInfo | None) -> PhaseSummary:
    """Describe recorded timing; ``finished`` does not imply phase success."""
    if timing is None or timing.started_at is None:
        return {"started_at": None, "duration_seconds": None, "status": "not_started"}
    started = timing.started_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if timing.finished_at is None:
        return {"started_at": started, "duration_seconds": None, "status": "started"}
    duration = (timing.finished_at - timing.started_at).total_seconds()
    return {"started_at": started, "duration_seconds": duration, "status": "finished"}


def _manifest_summary(trial_dir: Path) -> ManifestSummary:
    """Report validity and native entry statuses without changing classification."""
    path = trial_dir / "artifacts" / "manifest.json"
    if not path.exists():
        return {"status": "missing", "entries": []}
    try:
        manifest = ArtifactManifest.model_validate(
            {"entries": read_json(path, "manifest")}
        )
    except (OSError, ValueError):
        return {"status": "invalid", "entries": []}
    entries: list[ManifestEntrySummary] = [
        {"destination": entry.destination, "status": entry.status}
        for entry in manifest.entries
    ]
    status = (
        "failed"
        if any(entry.status == "failed" for entry in manifest.entries)
        else "ok"
    )
    return {"status": status, "entries": entries}


def _check_job_dir(job_dir: Path) -> None:
    """Accept only a directory Harbor created for the job its config names."""
    try:
        config = JobConfig.model_validate_json(
            read_bytes(job_dir / "config.json", "config")
        )
    except (OSError, ValueError):
        raise DataError("not_a_harbor_job", job_dir.name) from None
    if config.job_name != job_dir.name:
        raise DataError("not_a_harbor_job", job_dir.name)


def _read_result(trial_dir: Path) -> TrialResult:
    """Return the Trial's Harbor result.

    Raises:
        DataError: ``result_missing`` or ``result_invalid``.
    """
    path = trial_dir / "result.json"
    if not path.exists():
        raise DataError("result_missing", trial_dir.name)
    try:
        return TrialResult.model_validate_json(read_bytes(path, "result"))
    # Harbor's model validation errors, like DataError, are ValueErrors.
    except (OSError, ValueError):
        raise DataError("result_invalid", trial_dir.name) from None


def _measure_trial(job: str, trial_dir: Path, result: TrialResult) -> _Trial:
    outcome, reason = _classify(trial_dir, result)
    exception = result.exception_info
    execution = result.agent_execution
    agent_sec = None
    if (
        execution is not None
        and execution.started_at is not None
        and execution.finished_at is not None
    ):
        agent_sec = (execution.finished_at - execution.started_at).total_seconds()
    usage = result.agent_result
    failed_criteria = _failed_criteria(trial_dir)
    session_observations = _observe_sessions(trial_dir)
    conditions = _effective_conditions(trial_dir)
    recorded_session_count = _reported_session_count(usage)
    return _Trial(
        task=result.task_name,
        task_checksum=result.task_checksum,
        configuration=_configuration(result),
        outcome={
            "job": job,
            "trial": trial_dir.name,
            "outcome": outcome,
            "reason": reason,
            "exception": None if exception is None else exception.exception_type,
        },
        agent_sec=agent_sec,
        input_tokens=None if usage is None else usage.n_input_tokens,
        cached_tokens=None if usage is None else usage.n_cache_tokens,
        output_tokens=None if usage is None else usage.n_output_tokens,
        session_count=recorded_session_count,
        effective_session_count=(
            session_observations.count
            if session_observations.count is not None
            else recorded_session_count
        ),
        failed_criteria=failed_criteria,
        session_efforts=session_observations.efforts,
        unknown_effort_sessions=session_observations.unknown_effort,
        sessions_with_summary=session_observations.with_summary,
        has_session_evidence=session_observations.has_evidence,
        level=conditions.level,
        task_digest=conditions.task_digest,
        agent_timeout_sec=conditions.agent_timeout_sec,
        agent_network=conditions.agent_network,
    )


def _failed_criteria(trial_dir: Path) -> dict[str, dict[str, int]]:
    """Count failure and unknown facts from a validated saved evaluation."""
    failed_criteria: dict[str, dict[str, int]] = {}
    try:
        evaluation = read_evaluation(trial_dir / "verifier" / "evaluation.json")
    except (OSError, DataError):
        evaluation = None
    if evaluation is not None:
        for criterion in evaluation["criteria"]:
            status = criterion["status"]
            if status in {"fail", "unknown"}:
                counts = failed_criteria.setdefault(
                    criterion["criterion_id"], {"fail": 0, "unknown": 0}
                )
                counts[status] += 1
    return failed_criteria


def _observe_sessions(trial_dir: Path) -> _SessionObservations:
    """Count each observed effort once per session and reasoning summary presence."""
    sessions, session_marker = read_sessions(trial_dir / "agent" / "sessions")
    session_efforts: dict[str, int] = {}
    unknown_effort_sessions = 0
    sessions_with_summary = 0
    for rows in sessions:
        observed_efforts: set[str] = set()
        has_summary = False
        for row in rows:
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            effort = payload.get("effort")
            if row.get("type") == "turn_context" and isinstance(effort, str):
                if effort in {"none", "minimal", "low", "medium", "high", "xhigh"}:
                    observed_efforts.add(effort)
            if (
                row.get("type") == "response_item"
                and payload.get("type") == "reasoning"
            ):
                fragments = payload.get("summary")
                if isinstance(fragments, list) and any(
                    isinstance(fragment, dict)
                    and isinstance(fragment.get("text"), str)
                    and bool(fragment["text"].strip())
                    for fragment in fragments
                ):
                    has_summary = True
        if not observed_efforts:
            unknown_effort_sessions += 1
        for effort in observed_efforts:
            session_efforts[effort] = session_efforts.get(effort, 0) + 1
        sessions_with_summary += has_summary
    return _SessionObservations(
        count=len(sessions) if session_marker is None else None,
        efforts=session_efforts,
        unknown_effort=unknown_effort_sessions,
        with_summary=sessions_with_summary,
        has_evidence=session_marker is None,
    )


def _effective_conditions(trial_dir: Path) -> _EffectiveConditions:
    """Combine saved lock and digest-checked task settings for comparison."""
    recorded = _trial_conditions(trial_dir)
    task_config = _verified_task_config(recorded.task_path, recorded.task_digest)
    metadata = task_config.get("metadata") if task_config is not None else None
    recorded_level = metadata.get("level") if isinstance(metadata, dict) else None
    level = (
        recorded_level
        if isinstance(recorded_level, str)
        and recorded_level in {"L1", "L2", "L3a", "L3b"}
        else "unknown"
    )
    agent_timeout_sec = recorded.override_timeout_sec
    if agent_timeout_sec is None and task_config is not None:
        task_agent = task_config.get("agent")
        task_timeout = (
            task_agent.get("timeout_sec") if isinstance(task_agent, dict) else None
        )
        if isinstance(task_timeout, (int, float)) and not isinstance(
            task_timeout, bool
        ):
            task_timeout_sec = float(task_timeout)
            if math.isfinite(task_timeout_sec) and task_timeout_sec > 0:
                agent_timeout_sec = task_timeout_sec
    task_environment = (
        task_config.get("environment") if task_config is not None else None
    )
    network_mode = (
        task_environment.get("network_mode")
        if isinstance(task_environment, dict)
        else None
    )
    agent_network: tuple[str, ...] | None = None
    if (
        recorded.extra_allowed_hosts is not None
        and isinstance(network_mode, str)
        and network_mode
        in {
            "no-network",
            "public",
            "allowlist",
        }
    ):
        agent_network = (network_mode, *recorded.extra_allowed_hosts)
    return _EffectiveConditions(
        level=level,
        task_digest=recorded.task_digest,
        agent_timeout_sec=agent_timeout_sec,
        agent_network=agent_network,
    )


def _reported_session_count(context: AgentContext | None) -> int | None:
    """Read the validated Sapiens session count from Harbor's agent result."""
    metadata = None if context is None else context.metadata
    count = metadata.get("sapiens_session_count") if metadata else None
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
        return count
    return None


def _trial_conditions(trial_dir: Path) -> _RecordedConditions:
    """Read recorded task identity and agent conditions from a Trial lock."""
    try:
        lock = read_json(trial_dir / "lock.json", "lock")
    except (OSError, DataError):
        return _RecordedConditions(None, None, None, None)
    if not isinstance(lock, dict):
        return _RecordedConditions(None, None, None, None)
    task = lock.get("task")
    agent = lock.get("agent")
    if not isinstance(task, dict) or not isinstance(agent, dict):
        return _RecordedConditions(None, None, None, None)
    digest = task.get("digest")
    task_path = task.get("path")
    timeout = agent.get("override_timeout_sec")
    hosts = agent.get("extra_allowed_hosts")
    timeout_sec: float | None = None
    if isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
        try:
            converted = float(timeout)
        except OverflowError:
            pass
        else:
            if math.isfinite(converted) and converted > 0:
                timeout_sec = converted
    return _RecordedConditions(
        task_digest=digest if isinstance(digest, str) else None,
        task_path=Path(task_path) if isinstance(task_path, str) else None,
        override_timeout_sec=timeout_sec,
        extra_allowed_hosts=(
            tuple(sorted(cast(list[str], hosts)))
            if isinstance(hosts, list) and all(isinstance(host, str) for host in hosts)
            else None
        ),
    )


def _verified_task_config(
    task_path: Path | None, digest: str | None
) -> dict[str, object] | None:
    """Read task settings only when Harbor's directory digest still matches."""
    if task_path is None or digest is None:
        return None
    try:
        if not task_path.is_dir():
            return None
        actual_digest, _ = Packager.compute_content_hash(task_path)
        if digest != f"sha256:{actual_digest}":
            return None
        task_config = tomllib.loads(
            read_bytes(task_path / "task.toml", "task.toml").decode("utf-8")
        )
    except (OSError, ValueError, UnicodeError):
        return None
    return task_config


def _level_reports(trials: Sequence[_Trial]) -> list[LevelReport]:
    """Summarize each configuration and verified level without a total score."""
    groups: dict[tuple[_Key, str], list[_Trial]] = {}
    for trial in trials:
        groups.setdefault(
            (_configuration_key(trial.configuration), trial.level), []
        ).append(trial)
    reports: list[LevelReport] = []
    for key in sorted(groups):
        members = groups[key]
        task_groups: dict[tuple[str, str], list[_Trial]] = {}
        for trial in members:
            task_groups.setdefault((trial.task, trial.task_checksum), []).append(trial)
        task_reports = [_pair_report(group) for group in task_groups.values()]
        rates = [
            pair["pass_rate"] for pair in task_reports if pair["pass_rate"] is not None
        ]
        criteria: dict[str, dict[str, int]] = {}
        for pair in task_reports:
            for criterion_id, statuses in pair["failed_criteria"].items():
                totals = criteria.setdefault(criterion_id, {"fail": 0, "unknown": 0})
                for status, count in statuses.items():
                    totals[status] += count
        reports.append(
            {
                "configuration": members[0].configuration,
                "level": key[1],
                "tasks": len(task_reports),
                "covered_tasks": len(rates),
                "mean_pass_rate": statistics.mean(rates) if rates else None,
                "unknown": sum(pair["counts"]["unknown"] for pair in task_reports),
                "infra_error": sum(
                    pair["counts"]["infra_error"] for pair in task_reports
                ),
                "failed_criteria": {name: criteria[name] for name in sorted(criteria)},
            }
        )
    return reports


def _comparison_reports(trials: Sequence[_Trial]) -> list[TaskComparison]:
    """Compare only tasks measured by two or more configurations."""
    tasks: dict[str, dict[_Key, list[_Trial]]] = {}
    for trial in trials:
        configurations = tasks.setdefault(trial.task, {})
        configurations.setdefault(_configuration_key(trial.configuration), []).append(
            trial
        )
    comparisons: list[TaskComparison] = []
    for task in sorted(tasks):
        configurations = tasks[task]
        if len(configurations) < 2:
            continue
        groups = list(configurations.values())
        reasons = []
        digests = {trial.task_digest for group in groups for trial in group}
        if None in digests or len(digests) != 1:
            reasons.append("task_digest_differs")
        if any(
            sum(trial.outcome["outcome"] in {"pass", "fail"} for trial in group) < 2
            for group in groups
        ):
            reasons.append("insufficient_valid_trials")
        models = {group[0].configuration["model"] for group in groups}
        if None in models or len(models) != 1:
            reasons.append("model_differs")
        efforts = {group[0].configuration["reasoning"] for group in groups}
        if None in efforts or len(efforts) != 1:
            reasons.append("reasoning_effort_differs")
        timeouts = {trial.agent_timeout_sec for group in groups for trial in group}
        if None in timeouts or len(timeouts) != 1:
            reasons.append("agent_timeout_differs")
        networks = {trial.agent_network for group in groups for trial in group}
        if None in networks or len(networks) != 1:
            reasons.append("agent_network_differs")
        comparisons.append(
            {
                "task": task,
                "status": "incomparable" if reasons else "comparable",
                "reasons": reasons,
            }
        )
    return comparisons


def _classify(trial_dir: Path, result: TrialResult) -> tuple[Outcome, str | None]:
    """Return the Trial's outcome class and, for ``infra_error``, its reason.

    A pass or complete evaluation requires Harbor's verifier result because
    the candidate can write that directory until a separate verifier starts.
    Agent timeout or non-zero exit does not override a trustworthy verdict.
    """
    if result.agent_execution is None:
        return "infra_error", "setup_failed"
    if not _has_collected_artifacts(trial_dir):
        return "infra_error", "artifacts_failed"
    if result.verifier is None:
        return "infra_error", "verifier_skipped"
    if result.verifier_environment_mode != VerifierEnvironmentMode.SEPARATE:
        return "infra_error", "verifier_not_separate"
    try:
        evaluation = read_evaluation(trial_dir / "verifier" / "evaluation.json")
    except FileNotFoundError:
        return "infra_error", "evaluation_missing"
    except (OSError, DataError):
        return "infra_error", "evaluation_invalid"
    if result.verifier_result is None and (
        evaluation["verdict"] == "pass" or evaluation["completeness"] == "complete"
    ):
        return "infra_error", "verifier_result_missing"
    return evaluation["verdict"], None


def _has_collected_artifacts(trial_dir: Path) -> bool:
    """Return False when Harbor's manifest is unreadable or records a failed entry.

    Collection is best-effort in Harbor: a failed download leaves the
    verifier an empty directory, so its verdict would not be about the
    candidate's work. Without a manifest Harbor recorded no failed entry.
    """
    path = trial_dir / "artifacts" / "manifest.json"
    if not path.exists():
        return True
    try:
        manifest = ArtifactManifest.model_validate(
            {"entries": read_json(path, "manifest")}
        )
    except (OSError, ValueError):
        return False
    return all(entry.status != "failed" for entry in manifest.entries)


def _configuration(result: TrialResult) -> Configuration:
    model_info = result.agent_info.model_info
    if model_info is None:
        model = None
    elif model_info.provider is None:
        model = model_info.name
    else:
        model = f"{model_info.provider}/{model_info.name}"
    return {
        "harness": result.agent_info.name,
        "harness_version": result.agent_info.version,
        "model": model,
        "reasoning": _reasoning(result.config.agent.kwargs),
        "reasoning_summary": _reasoning_summary(result.config.agent.kwargs),
        "web_search": _web_search(result.config.agent.kwargs),
    }


def _reasoning_summary(kwargs: Mapping[str, object]) -> str | None:
    """Return the requested summary setting from saved effective options."""
    config = kwargs.get("config")
    setting = (
        config.get("model_reasoning_summary") if isinstance(config, Mapping) else None
    )
    if isinstance(setting, str) and setting in {"auto", "concise", "detailed", "none"}:
        return setting
    setting = kwargs.get("reasoning_summary")
    return (
        setting
        if isinstance(setting, str)
        and setting in {"auto", "concise", "detailed", "none"}
        else None
    )


def _web_search(kwargs: Mapping[str, object]) -> str | None:
    """Return the saved native web search setting, if explicitly recorded."""
    config = kwargs.get("config")
    setting = config.get("web_search") if isinstance(config, Mapping) else None
    return (
        setting
        if isinstance(setting, str) and setting in {"disabled", "cached", "live"}
        else None
    )


def _reasoning(kwargs: Mapping[str, object]) -> str | None:
    """Return the reasoning effort from native agent options, if recorded.

    Harbor's Codex option ``reasoning_effort`` and the inline native Codex
    config key ``model_reasoning_effort`` are both read; a config given as a
    file path is not, so its effort stays unknown.
    """
    effort = kwargs.get("reasoning_effort")
    config = kwargs.get("config")
    if effort is None and isinstance(config, Mapping):
        effort = config.get("model_reasoning_effort")
    return effort if isinstance(effort, str) else None


def _pair_key(trial: _Trial) -> _Key:
    return (
        trial.task,
        trial.task_checksum,
        *_configuration_key(trial.configuration),
    )


def _configuration_key(configuration: Configuration) -> _Key:
    return (
        configuration["harness"],
        configuration["harness_version"],
        _unknown_first(configuration["model"]),
        _unknown_first(configuration["reasoning"]),
        _unknown_first(configuration["reasoning_summary"]),
        _unknown_first(configuration["web_search"]),
    )


def _unknown_first(value: str | None) -> tuple[bool, str]:
    return (False, "") if value is None else (True, value)


def _pair_report(trials: Sequence[_Trial]) -> PairReport:
    outcomes = sorted(
        (trial.outcome for trial in trials),
        key=lambda outcome: (outcome["job"], outcome["trial"]),
    )
    counts: OutcomeCounts = {
        "trials": len(outcomes),
        "pass": _count(outcomes, "pass"),
        "fail": _count(outcomes, "fail"),
        "unknown": _count(outcomes, "unknown"),
        "infra_error": _count(outcomes, "infra_error"),
    }
    known = counts["pass"] + counts["fail"]
    failed_criteria: dict[str, dict[str, int]] = {}
    session_efforts: dict[str, int] = {}
    for trial in trials:
        for criterion_id, statuses in trial.failed_criteria.items():
            totals = failed_criteria.setdefault(criterion_id, {"fail": 0, "unknown": 0})
            for status, count in statuses.items():
                totals[status] += count
        for effort, count in trial.session_efforts.items():
            session_efforts[effort] = session_efforts.get(effort, 0) + count
    first = trials[0]
    return {
        "task": first.task,
        "task_checksum": first.task_checksum,
        "configuration": first.configuration,
        "counts": counts,
        "pass_rate": counts["pass"] / known if known else None,
        "unknown_rate": counts["unknown"] / len(outcomes),
        "infra_error_rate": counts["infra_error"] / len(outcomes),
        "agent_sec": _median([trial.agent_sec for trial in trials]),
        "input_tokens": _median([trial.input_tokens for trial in trials]),
        "cached_tokens": _median([trial.cached_tokens for trial in trials]),
        "output_tokens": _median([trial.output_tokens for trial in trials]),
        "session_count": _median([trial.session_count for trial in trials]),
        "sessions": _median([trial.effective_session_count for trial in trials]),
        "trials": outcomes,
        "valid": known,
        "pass_hat_k": (
            math.comb(counts["pass"], 3) / math.comb(known, 3) if known >= 3 else None
        ),
        "failed_criteria": {
            key: failed_criteria[key] for key in sorted(failed_criteria)
        },
        "session_efforts": {
            key: session_efforts[key] for key in sorted(session_efforts)
        },
        "xhigh_sessions": session_efforts.get("xhigh", 0),
        "unknown_effort_sessions": sum(
            trial.unknown_effort_sessions for trial in trials
        ),
        "sessions_with_summary": sum(trial.sessions_with_summary for trial in trials),
        "session_evidence_missing_trials": sum(
            not trial.has_session_evidence for trial in trials
        ),
        "level": first.level
        if all(trial.level == first.level for trial in trials)
        else "unknown",
    }


def _count(outcomes: Sequence[TrialOutcome], outcome: Outcome) -> int:
    return sum(trial["outcome"] == outcome for trial in outcomes)


def _median(values: Sequence[float | None]) -> Median:
    known = [value for value in values if value is not None]
    return {
        "median": float(statistics.median(known)) if known else None,
        "known": len(known),
    }


def _configuration_title(configuration: Configuration) -> str:
    return (
        f"{configuration['harness']} {configuration['harness_version']}, "
        f"model {_or_unknown(configuration['model'])}, "
        f"reasoning {_or_unknown(configuration['reasoning'])}, "
        f"reasoning summary {_or_unknown(configuration['reasoning_summary'])}, "
        f"web search {_or_unknown(configuration['web_search'])}"
    )


def _or_unknown(value: str | None) -> str:
    return "unknown" if value is None else value


def _markdown_row(pair: PairReport) -> str:
    counts = pair["counts"]
    pass_rate = pair["pass_rate"]
    agent_sec = pair["agent_sec"]["median"]
    tokens = " / ".join(
        _format_count(pair[metric]["median"])
        for metric in ("input_tokens", "cached_tokens", "output_tokens")
    )
    cells = [
        pair["task"],
        pair["task_checksum"][:12],
        str(counts["trials"]),
        f"{counts['pass']}/{pair['valid']}",
        str(counts["fail"]),
        str(counts["unknown"]),
        str(counts["infra_error"]),
        "unknown" if pass_rate is None else f"{pass_rate:.2f}",
        "unknown" if pair["pass_hat_k"] is None else f"{pair['pass_hat_k']:.2f}",
        _format_failed_criteria(pair["failed_criteria"]),
        "unknown" if agent_sec is None else f"{agent_sec:.1f}",
        tokens,
        _format_count(pair["sessions"]["median"]),
        _or_unknown(pair["configuration"]["reasoning"]),
        str(pair["xhigh_sessions"]),
        str(pair["sessions_with_summary"]),
    ]
    return f"| {' | '.join(cells)} |"


def _format_failed_criteria(criteria: dict[str, dict[str, int]]) -> str:
    """Render the validated failure and unknown counts by criterion ID."""
    if not criteria:
        return "—"
    return ", ".join(
        f"{criterion_id} fail:{counts['fail']} unknown:{counts['unknown']}"
        for criterion_id, counts in sorted(criteria.items())
    )


def _format_count(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
