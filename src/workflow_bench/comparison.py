"""Offline report of Trial outcomes per task and configuration from Harbor job dirs."""

import logging
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Literal, TypedDict, cast

from harbor.models.job.config import JobConfig
from harbor.models.task.config import VerifierEnvironmentMode
from harbor.models.trial.artifact_manifest import ArtifactManifest
from harbor.models.trial.result import TimingInfo, TrialResult

from workflow_bench.contracts import Evaluation
from workflow_bench.data import DataError, read_bytes, read_json, validate_contract

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
    """

    harness: str
    harness_version: str
    model: str | None
    reasoning: str | None


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
    trials: list[TrialOutcome]


class IncompleteTrial(TypedDict):
    """A Trial directory without a readable Harbor result: running or killed."""

    job: str
    trial: str
    reason: str


class ComparisonReport(TypedDict):
    """Reported pairs and Trials without a readable Harbor result."""

    pairs: list[PairReport]
    incomplete_trials: list[IncompleteTrial]


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


class TrialSummary(TypedDict):
    """Diagnostic facts for one Trial, with its existing report outcome."""

    job: str
    trial: str
    outcome: Outcome
    reason: str | None
    exception: str | None
    phases: dict[str, PhaseSummary]
    evaluation: Evaluation | None
    errors: list[str]
    tokens: dict[str, int | None]
    artifact_manifest: ManifestSummary
    paths: dict[str, str]


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
    return {"pairs": pairs, "incomplete_trials": incomplete}


def summarize(job_dirs: Sequence[Path], report: ComparisonReport) -> SummaryReport:
    """Return native Trial diagnostics using classifications from ``report``.

    The caller supplies the report from ``compare`` over the same saved jobs.
    This mode reads files but never writes or evaluates a Trial.
    """
    outcomes = {
        (trial["job"], trial["trial"]): trial
        for pair in report["pairs"]
        for trial in pair["trials"]
    }
    summaries = []
    for job_dir in job_dirs:
        for trial_dir in sorted(path for path in job_dir.iterdir() if path.is_dir()):
            outcome = outcomes.get((job_dir.name, trial_dir.name))
            if outcome is None:
                continue
            result = _read_result(trial_dir)
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
    lines = ["# Workflow Bench report"]
    for key in sorted(sections):
        pairs = sections[key]
        lines += ["", f"## {_configuration_title(pairs[0]['configuration'])}", ""]
        lines += [
            (
                "| Task | Checksum | Trials | Pass | Fail | Unknown | Infra error "
                "| Pass rate | Median agent s | Median tokens in / cached / out |"
            ),
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        lines += [_markdown_row(pair) for pair in pairs]
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
    paths = {
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
        + ([] if evaluation is None else evaluation["errors"]),
        "tokens": {
            "input": None if usage is None else usage.n_input_tokens,
            "cached": None if usage is None else usage.n_cache_tokens,
            "output": None if usage is None else usage.n_output_tokens,
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
    )


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
    }


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
        "trials": outcomes,
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
        f"reasoning {_or_unknown(configuration['reasoning'])}"
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
        str(counts["pass"]),
        str(counts["fail"]),
        str(counts["unknown"]),
        str(counts["infra_error"]),
        "unknown" if pass_rate is None else f"{pass_rate:.2f}",
        "unknown" if agent_sec is None else f"{agent_sec:.1f}",
        tokens,
    ]
    return f"| {' | '.join(cells)} |"


def _format_count(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.0f}" if value.is_integer() else f"{value:.1f}"
