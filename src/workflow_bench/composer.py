"""Codex composition at Harbor's installed-agent seam; no agent loop."""

import asyncio
import json
import math
import os
import selectors
import shutil
import stat
import subprocess
import time
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

MAX_SESSION_ENTRIES = 256
MAX_SESSION_DEPTH = 8


class AllowanceWindow(TypedDict):
    """Native included-usage window; absent duration/reset facts stay unknown."""

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

            def _request(message: dict[str, JsonValue]) -> JsonValue:
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
        try:
            await super().run(instruction, environment, context)
        except asyncio.CancelledError:
            # Native Codex's finally uses exec, unavailable after confirmed stop.
            # Docker copy can still read the stopped container, without credentials.
            try:
                async with asyncio.timeout(10):
                    with TemporaryDirectory(prefix="wb-interrupted-") as directory:
                        recovered = Path(directory)
                        await environment.download_dir(
                            str(self._REMOTE_CODEX_HOME / "sessions"),
                            recovered / "sessions",
                        )
                        _, snapshots, invalid = _session_snapshot(recovered)
                        if not invalid and snapshots:
                            sessions = self.logs_dir / "sessions"
                            if sessions.is_symlink() or sessions.is_file():
                                sessions.unlink()
                            elif sessions.exists():
                                shutil.rmtree(sessions)
                            for reference, content in snapshots:
                                target = self.logs_dir / reference
                                target.parent.mkdir(parents=True, exist_ok=True)
                                target.write_bytes(content)
            except (OSError, RuntimeError, TimeoutError):
                self.logger.warning("phase=agent session_recovery=unavailable")
            raise

    @override
    def convert_trajectory(self, logs_dir: Path) -> Trajectory | None:
        _, snapshots, invalid = _session_snapshot(logs_dir)
        if invalid or not snapshots:
            return None
        with TemporaryDirectory(prefix="wb-session-") as directory:
            safe_logs = Path(directory)
            for reference, content in snapshots:
                target = safe_logs / reference
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            return super().convert_trajectory(safe_logs)

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        original = self.logs_dir
        _, snapshots, invalid = _session_snapshot(original)
        if not invalid and snapshots:
            with TemporaryDirectory(prefix="wb-session-") as directory:
                self.logs_dir = Path(directory)
                try:
                    for reference, content in snapshots:
                        target = self.logs_dir / reference
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
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
    raw_refs, snapshots, malformed = _session_snapshot(logs)
    totals = None
    if len(snapshots) == 1 and not malformed:
        try:
            lines = snapshots[0][1].decode("utf-8").splitlines()
        except (OSError, UnicodeError, DataError):
            lines = []
            malformed = True
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
                malformed = True
    if malformed:
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
    """Snapshot bounded native logs through directory handles, never follow links."""
    references = []
    snapshots = []
    entries = 0
    remaining = MAX_EVIDENCE_BYTES
    invalid = False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def visit(directory: int, relative: Path, depth: int) -> None:
        nonlocal entries, remaining, invalid
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
                        for line in content.splitlines():
                            if line.strip() and not isinstance(
                                decode_json(line, "sessions"), dict
                            ):
                                raise DataError("invalid_session", "sessions")
                        remaining -= len(content)
                        snapshots.append((reference, content))
                    except (OSError, DataError):
                        invalid = True
                elif child.is_dir(follow_symlinks=False):
                    descriptor = os.open(child.name, flags, dir_fd=directory)
                    try:
                        visit(descriptor, reference, depth + 1)
                    finally:
                        os.close(descriptor)
                elif child.is_symlink():
                    references.append(reference.as_posix())
                    invalid = True

    try:
        descriptor = os.open(logs, flags)
        try:
            try:
                directory = os.open("sessions", flags, dir_fd=descriptor)
            except FileNotFoundError:
                return [], [], False
            try:
                visit(directory, Path("sessions"), 0)
            finally:
                os.close(directory)
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        invalid = bool(references)
    except (OSError, DataError):
        invalid = True
    return sorted(references), sorted(snapshots), invalid


def _allowance_report(account_response: JsonValue) -> CodexAllowance:
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
    if bucket.get("spendControlReached") is True:
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
