"""Codex composition at Harbor's installed-agent seam; no agent loop."""

import asyncio
import io
import json
import math
import os
import selectors
import shutil
import stat
import subprocess
import tarfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypedDict, override

from harbor.agents.installed.codex import Codex
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Trajectory

from workflow_bench.contracts import JsonValue
from workflow_bench.data import (
    MAX_EVIDENCE_BYTES,
    DataError,
    decode_json,
    read_json,
)
from workflow_bench.harbor import DeadlineDockerEnvironment
from workflow_bench.observability import format_phase_line

MAX_SESSION_ENTRIES = 256
MAX_SESSION_DEPTH = 8
MAX_SESSION_ARCHIVE_BYTES = MAX_EVIDENCE_BYTES + 1024 * 1024


class _AccountRequest(TypedDict):
    """Native app-server request with a response correlation id."""

    id: int
    method: str
    params: dict[str, JsonValue]


class AllowanceWindow(TypedDict):
    """Native usage window; absent duration/reset facts stay unknown.

    resetsAt is seconds since the Unix epoch; windowDurationMins is minutes.
    """

    usedPercent: float
    windowDurationMins: int | None
    resetsAt: int | None


class AllowanceWindows(TypedDict):
    """Validated primary and optional secondary subscription windows."""

    primary: AllowanceWindow
    secondary: AllowanceWindow | None


class CodexAllowance(TypedDict):
    """Available included usage observed at Unix seconds, without account identity."""

    rateLimits: AllowanceWindows
    observed_at_unix: float


class SapiensUsage(TypedDict):
    """Totals over every validated native Codex session of one Sapiens Trial.

    ``session_count`` is unknown when logs are missing or invalid, and counts
    validated sessions even when their token totals cannot be measured.
    Missing or invalid token measurements are unknown, never zero.
    """

    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    session_count: int | None


def read_codex_limits(auth_path: Path, *, timeout_sec: float) -> CodexAllowance:
    """Read available subscription allowance in a clean host-only native session.

    Reads the explicit ChatGPT credential file and queries account status only.
    Raises DataError for unavailable, malformed or exhausted allowance; it does
    not authorize or launch a model Trial. The query deadline is in seconds.
    """
    auth = read_json(auth_path, "codex_auth")
    if not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt":
        raise DataError("chatgpt_auth_required", "codex_auth")
    with TemporaryDirectory(prefix="wb-account-") as directory:
        home = Path(directory)
        copied = home / "auth.json"
        copied.write_text(json.dumps(auth))
        copied.chmod(0o600)
        environment = dict(os.environ, CODEX_HOME=str(home))
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("OPENAI_BASE_URL", None)
        process = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        stdin, stdout = process.stdin, process.stdout
        # Both streams exist because Popen received PIPE for them.
        assert stdin is not None and stdout is not None
        deadline = time.monotonic() + timeout_sec
        buffer = b""
        with selectors.DefaultSelector() as selector:
            selector.register(stdout, selectors.EVENT_READ)

            def _request(message: _AccountRequest) -> JsonValue:
                nonlocal buffer
                stdin.write((json.dumps(message) + "\n").encode())
                stdin.flush()
                while time.monotonic() < deadline:
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        try:
                            response = decode_json(line, "codex_account")
                        except DataError as error:
                            raise DataError(
                                "subscription_status_unavailable", "codex_account"
                            ) from error
                        if not isinstance(response, dict):
                            raise DataError(
                                "subscription_status_unavailable", "codex_account"
                            )
                        if response.get("id") == message["id"]:
                            if "error" in response:
                                raise DataError(
                                    "subscription_status_unavailable", "codex_account"
                                )
                            return response.get("result")
                    if not selector.select(min(1, max(0, deadline - time.monotonic()))):
                        continue
                    chunk = os.read(stdout.fileno(), 65536)
                    if not chunk or len(buffer) + len(chunk) > MAX_EVIDENCE_BYTES:
                        raise DataError(
                            "subscription_status_unavailable", "codex_account"
                        )
                    buffer += chunk
                raise DataError("subscription_status_timeout", "codex_account")

            try:
                _request(
                    {
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {"name": "workflow_bench", "version": "0.1.0"}
                        },
                    }
                )
                stdin.write(b'{"method":"initialized"}\n')
                stdin.flush()
                allowance_response = _request(
                    {"id": 2, "method": "account/rateLimits/read", "params": {}}
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                stdin.close()
                stdout.close()
    return _allowance_report(allowance_response)


class SessionSafeCodex(Codex):
    """Keep the stock agent loop; bound its candidate-controlled log ingestion."""

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        """Run native Codex, recovering bounded session logs after container stop."""
        started = time.monotonic()
        phase_result = "failed"
        try:
            await super().run(instruction, environment, context)
            phase_result = "completed"
        except asyncio.CancelledError:
            phase_result = "cancelled"
            # Native Codex's finally uses exec, unavailable after confirmed stop.
            # Bound the stopped container's archive before materializing any files.
            try:
                async with asyncio.timeout(10):
                    if not isinstance(environment, DeadlineDockerEnvironment):
                        raise RuntimeError("bounded_archive_unavailable")
                    archive = await environment.read_file_archive(
                        str(self._REMOTE_CODEX_HOME / "sessions"),
                        max_bytes=MAX_SESSION_ARCHIVE_BYTES,
                    )
                    snapshots = _session_archive_snapshot(archive)
                    if snapshots:
                        sessions = self.logs_dir / "sessions"
                        if sessions.is_symlink() or sessions.is_file():
                            sessions.unlink()
                        elif sessions.exists():
                            _, _, has_invalid_entry = _session_snapshot(self.logs_dir)
                            if has_invalid_entry:
                                raise DataError("unsafe_session", "sessions")
                            shutil.rmtree(sessions)
                        _write_session_snapshot(self.logs_dir, snapshots)
            except (OSError, RuntimeError, TimeoutError, DataError, tarfile.TarError):
                self.logger.warning("phase=agent session_recovery=unavailable")
            raise
        finally:
            self.logger.info(
                format_phase_line(
                    "agent_run",
                    phase_result,
                    time.monotonic() - started,
                    datetime.now(UTC),
                    trial=self.logs_dir.parent.name,
                )
            )

    @override
    def convert_trajectory(self, logs_dir: Path) -> Trajectory | None:
        """Parse validated sessions, returning None for invalid or absent logs."""
        _, snapshots, has_invalid_entry = _session_snapshot(logs_dir)
        if has_invalid_entry or not snapshots:
            return None
        with TemporaryDirectory(prefix="wb-session-") as directory:
            safe_logs = Path(directory)
            _write_session_snapshot(safe_logs, snapshots)
            return super().convert_trajectory(safe_logs)

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        """Populate context from valid sessions and disable unsafe usage fallback.

        Invalid or absent sessions leave native fields unchanged. Missing model usage
        becomes an empty mapping so Harbor cannot read candidate trajectory.json;
        missing token and cost measurements remain unknown.
        """
        original = self.logs_dir
        _, snapshots, has_invalid_entry = _session_snapshot(original)
        if not has_invalid_entry and snapshots:
            with TemporaryDirectory(prefix="wb-session-") as directory:
                self.logs_dir = Path(directory)
                try:
                    _write_session_snapshot(self.logs_dir, snapshots)
                    super().populate_context_post_run(context)
                finally:
                    self.logs_dir = original
        # Stop Trial's fallback from reading candidate trajectory.json. Empty means
        # no observed per-model records; missing token/cost fields remain unknown.
        if context.model_usage is None:
            context.model_usage = {}


def collect_codex_usage(
    logs: Path, *, prices: dict[str, float] | None = None
) -> dict[str, JsonValue]:
    """Keep raw refs; one session's last totals take precedence over turn events."""
    raw_refs, snapshots, has_invalid_session = _session_snapshot(logs)
    totals = None
    if len(snapshots) == 1 and not has_invalid_session:
        try:
            lines = snapshots[0][1].decode("utf-8").splitlines()
        except (OSError, UnicodeError, DataError):
            lines = []
            has_invalid_session = True
        for line in lines:
            try:
                event = json.loads(line)
                payload = event.get("payload", {})
                if (
                    event.get("type") == "event_msg"
                    and payload.get("type") == "token_count"
                ):
                    info = payload.get("info")
                    if isinstance(info, dict) and isinstance(
                        info.get("total_token_usage"), dict
                    ):
                        totals = info["total_token_usage"]
            except (ValueError, AttributeError, TypeError):
                has_invalid_session = True
    if has_invalid_session:
        totals = None
    usage = {
        "source": "native_session_last_cumulative",
        "raw_refs": raw_refs,
        "model_calls": None,
        "usd": None,
        "prices": prices,
    }
    for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
        value = totals.get(name) if totals else None
        usage[name] = (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else None
        )
    if prices is not None and all(
        usage[key] is not None
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    ):
        if set(prices) != {
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
        } or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
            for v in prices.values()
        ):
            raise DataError("invalid_prices", "prices")
        uncached = usage["input_tokens"] - usage["cached_input_tokens"]
        if uncached >= 0:
            usage["usd"] = (
                uncached * prices["input_per_million"]
                + usage["cached_input_tokens"] * prices["cached_input_per_million"]
                + usage["output_tokens"] * prices["output_per_million"]
            ) / 1_000_000
    return usage


def collect_sapiens_usage(logs: Path) -> SapiensUsage:
    """Sum each session's last cumulative token count; keep missing facts unknown."""
    _, snapshots, has_invalid_session = _session_snapshot(logs)
    unknown: SapiensUsage = {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "session_count": len(snapshots)
        if snapshots and not has_invalid_session
        else None,
    }
    if has_invalid_session or not snapshots:
        return unknown
    totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for _, content in snapshots:
        last: dict[str, JsonValue] | None = None
        for line in content.splitlines():
            if not line.strip():
                continue
            event = decode_json(line, "sessions")
            if not isinstance(event, dict) or event.get("type") != "event_msg":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            candidate = (
                info.get("total_token_usage") if isinstance(info, dict) else None
            )
            last = candidate if isinstance(candidate, dict) else None
        if last is None:
            return unknown
        session_totals: dict[str, int] = {}
        for name in totals:
            count = last.get(name)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                return unknown
            session_totals[name] = count
        if session_totals["cached_input_tokens"] > session_totals["input_tokens"]:
            return unknown
        for name in totals:
            totals[name] += session_totals[name]
    return {
        "input_tokens": totals["input_tokens"],
        "cached_input_tokens": totals["cached_input_tokens"],
        "output_tokens": totals["output_tokens"],
        "session_count": len(snapshots),
    }


def _write_session_snapshot(
    logs: Path, snapshots: Sequence[tuple[Path, bytes]]
) -> None:
    """Materialize validated relative references beneath a trusted logs directory."""
    for reference, content in snapshots:
        target = logs / reference
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _session_archive_snapshot(archive: bytes) -> list[tuple[Path, bytes]]:
    """Validate a bounded uncompressed archive before writing any session files.

    Reject links, special files, duplicate/escaping paths and oversized trees with
    DataError. Only regular JSONL files become snapshots; other files stay in memory.
    """
    snapshots = []
    references: set[Path] = set()
    remaining = MAX_EVIDENCE_BYTES
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream:
            reference = Path(member.name)
            if (
                reference.is_absolute()
                or ".." in reference.parts
                or not reference.parts
                or reference.parts[0] != "sessions"
                or reference in references
                or len(reference.parts)
                > MAX_SESSION_DEPTH + (1 if member.isdir() else 2)
                or not (member.isdir() or member.isreg())
                or member.sparse is not None
            ):
                raise DataError("unsafe_session", "sessions")
            references.add(reference)
            if len(references - {Path("sessions")}) > MAX_SESSION_ENTRIES:
                raise DataError("session_tree_too_large", "sessions")
            if member.isdir() or not member.name.endswith(".jsonl"):
                continue
            if member.size < 0 or member.size > remaining:
                raise DataError("session_too_large", "sessions")
            content_stream = stream.extractfile(member)
            if content_stream is None:
                raise DataError("unsafe_session", "sessions")
            with content_stream:
                content = content_stream.read(remaining + 1)
            _validate_session_content(content)
            remaining -= len(content)
            snapshots.append((reference, content))
    return sorted(snapshots)


def _validate_session_content(content: bytes) -> None:
    """Raise DataError unless every nonblank JSONL line is a strict JSON object."""
    for line in content.splitlines():
        if line.strip() and not isinstance(decode_json(line, "sessions"), dict):
            raise DataError("invalid_session", "sessions")


def _read_session(name: str, directory: int, limit: int) -> bytes:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DataError("unsafe_session", "sessions")
        if info.st_size > limit:
            raise DataError("session_too_large", "sessions")
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise DataError("session_too_large", "sessions")
    return content


def _session_snapshot(logs: Path) -> tuple[list[str], list[tuple[Path, bytes]], bool]:
    """Snapshot bounded native logs through directory handles, never follow links.

    Return sorted relative references, validated file snapshots and an invalid flag.
    A true flag rejects the entire collection: references may describe partial
    evidence, but callers must not consume the snapshots. Missing sessions return
    empty collections with a false flag.
    """
    references = []
    snapshots = []
    entries = 0
    remaining = MAX_EVIDENCE_BYTES
    has_invalid_entry = False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def _visit(directory: int, relative: Path, depth: int) -> None:
        nonlocal entries, remaining, has_invalid_entry
        if depth > MAX_SESSION_DEPTH:
            raise DataError("session_tree_too_large", "sessions")
        with os.scandir(directory) as children:
            for child in children:
                entries += 1
                if entries > MAX_SESSION_ENTRIES:
                    raise DataError("session_tree_too_large", "sessions")
                reference = relative / child.name
                if child.name.endswith(".jsonl"):
                    references.append(reference.as_posix())
                    try:
                        content = _read_session(child.name, directory, remaining)
                        # Native Harbor uses permissive JSON and unbounded line reads.
                        # Give it only checked, finite regular-file snapshots.
                        _validate_session_content(content)
                        remaining -= len(content)
                        snapshots.append((reference, content))
                    except (OSError, DataError):
                        has_invalid_entry = True
                elif child.is_dir(follow_symlinks=False):
                    descriptor = os.open(child.name, flags, dir_fd=directory)
                    try:
                        _visit(descriptor, reference, depth + 1)
                    finally:
                        os.close(descriptor)
                elif child.is_symlink():
                    references.append(reference.as_posix())
                    has_invalid_entry = True

    try:
        descriptor = os.open(logs, flags)
        try:
            try:
                directory = os.open("sessions", flags, dir_fd=descriptor)
            except FileNotFoundError:
                return [], [], False
            try:
                _visit(directory, Path("sessions"), 0)
            finally:
                os.close(directory)
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        has_invalid_entry = bool(references)
    except (OSError, DataError):
        has_invalid_entry = True
    return sorted(references), sorted(snapshots), has_invalid_entry


def _allowance_report(account_response: JsonValue) -> CodexAllowance:
    """Return available usage; reject exhausted or malformed facts with DataError."""
    if (
        isinstance(account_response, dict)
        and account_response.get("ordinaryUsageAllowed") is False
    ):
        raise DataError("subscription_exhausted", "codex_account")
    if (
        not isinstance(account_response, dict)
        or account_response.get("ordinaryUsageAllowed") is not True
    ):
        raise DataError("subscription_status_unavailable", "codex_account")
    buckets = account_response.get("rateLimitsByLimitId")
    if buckets is not None and not isinstance(buckets, dict):
        raise DataError("subscription_status_unavailable", "codex_account")
    bucket = (
        buckets.get("codex", account_response.get("rateLimits"))
        if buckets
        else account_response.get("rateLimits")
    )
    if not isinstance(bucket, dict) or not isinstance(bucket.get("primary"), dict):
        raise DataError("subscription_status_unavailable", "codex_account")
    spend_control_reached = bucket.get("spendControlReached")
    if spend_control_reached is not None and not isinstance(
        spend_control_reached, bool
    ):
        raise DataError("subscription_status_unavailable", "codex_account")
    if spend_control_reached is True:
        raise DataError("subscription_exhausted", "codex_account")
    if bucket.get("rateLimitReachedType") is not None:
        raise DataError("subscription_exhausted", "codex_account")
    primary = _allowance_window(bucket["primary"])
    if primary is None:
        raise DataError("subscription_status_unavailable", "codex_account")
    return {
        "rateLimits": {
            "primary": primary,
            "secondary": _allowance_window(bucket.get("secondary")),
        },
        "observed_at_unix": time.time(),
    }


def _allowance_window(window: JsonValue) -> AllowanceWindow | None:
    """Preserve an absent window; reject malformed or exhausted ones with DataError."""
    if window is None:
        return None
    if not isinstance(window, dict):
        raise DataError("subscription_status_unavailable", "codex_account")
    used_percent = window.get("usedPercent")
    if (
        isinstance(used_percent, bool)
        or not isinstance(used_percent, (int, float))
        or not 0 <= used_percent <= 100
    ):
        raise DataError("subscription_status_unavailable", "codex_account")
    if used_percent >= 100:
        raise DataError("subscription_exhausted", "codex_account")
    window_duration_minutes = window.get("windowDurationMins")
    resets_at_unix = window.get("resetsAt")
    for value in (window_duration_minutes, resets_at_unix):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise DataError("subscription_status_unavailable", "codex_account")
    return {
        "usedPercent": used_percent,
        "windowDurationMins": window_duration_minutes
        if isinstance(window_duration_minutes, int)
        else None,
        "resetsAt": resets_at_unix if isinstance(resets_at_unix, int) else None,
    }
