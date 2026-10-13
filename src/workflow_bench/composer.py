"""Codex composition at Harbor's installed-agent seam; no agent loop."""

import json
import math
import os
import re
import selectors
import stat
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, override

from harbor.agents.installed.codex import Codex
from harbor.models.agent.context import AgentContext
from harbor.models.trajectories import Trajectory

from workflow_bench.contracts import JsonValue
from workflow_bench.data import (
    MAX_EVIDENCE_BYTES,
    DataError,
    decode_json,
    read_json,
    resource_schema,
    validate_json,
)

MAX_SESSION_ENTRIES = 256
MAX_SESSION_DEPTH = 8


def read_codex_limits(auth_path: Path, *, timeout_sec: float) -> dict[str, JsonValue]:
    """Read the subscription's live limits in a clean, host-only native session."""
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

            def request(message: dict[str, JsonValue]) -> Any:
                nonlocal buffer
                stdin.write((json.dumps(message) + "\n").encode())
                stdin.flush()
                while time.monotonic() < deadline:
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        response = json.loads(line)
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
                request(
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
                result = request(
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
    if not isinstance(result, dict) or result.get("ordinaryUsageAllowed") is not True:
        raise DataError("subscription_status_unavailable", "codex_account")
    bucket = (result.get("rateLimitsByLimitId") or {}).get(
        "codex", result.get("rateLimits")
    )
    if not isinstance(bucket, dict) or not isinstance(bucket.get("primary"), dict):
        raise DataError("subscription_status_unavailable", "codex_account")
    for window in (bucket["primary"], bucket.get("secondary")):
        if window is None:
            continue
        used = window.get("usedPercent")
        if (
            isinstance(used, bool)
            or not isinstance(used, (int, float))
            or not 0 <= used <= 100
        ):
            raise DataError("subscription_status_unavailable", "codex_account")
        if used >= 100 or bucket.get("rateLimitReachedType") is not None:
            raise DataError("subscription_exhausted", "codex_account")
    # Preserve quota facts without account identifiers or auth material.
    return {"rateLimits": bucket, "observed_at_unix": time.time()}


class SessionSafeCodex(Codex):
    """Keep the stock agent loop; bound its candidate-controlled log ingestion."""

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


def codex_preflight(
    composer: dict[str, JsonValue],
    *,
    budget: dict[str, JsonValue] | None,
    runtime: dict[str, JsonValue],
    authorized: bool,
    auth_path: Path | None = None,
) -> dict[str, JsonValue]:
    """Reject execution before credential access or resource creation."""
    required = {
        "mode",
        "image",
        "cli_version",
        "model",
        "reasoning_effort",
        "exploration_max_calls",
    }
    if (
        not isinstance(composer, dict)
        or set(composer) not in (required, required | {"authentication"})
        or not isinstance(composer["mode"], str)
        or composer["mode"] not in {"model-free", "model"}
        or not isinstance(composer["image"], str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", composer["image"])
        or not isinstance(composer["cli_version"], str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", composer["cli_version"])
        or not isinstance(composer["model"], str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", composer["model"])
        or not isinstance(composer["reasoning_effort"], str)
        or composer["reasoning_effort"]
        not in {"none", "minimal", "low", "medium", "high", "xhigh"}
        or isinstance(composer["exploration_max_calls"], bool)
        or not isinstance(composer["exploration_max_calls"], int)
        or not 1 <= composer["exploration_max_calls"] <= 100
    ):
        raise DataError("invalid_composer_config", "composer")
    if composer["mode"] == "model-free":
        if (
            budget is not None
            or composer["model"] != "synthetic"
            or "authentication" in composer
        ):
            raise DataError("invalid_model_free_config", "composer")
        return {
            "execution_enabled": True,
            "model_calls": 0,
            "provider": "isolated_stub",
        }
    if composer.get("authentication") == "chatgpt":
        validate_json(runtime, resource_schema("e1.schema.json"), "e1_config")
        if not authorized:
            raise DataError("model_not_authorized", "composer")
        if auth_path is None:
            raise DataError("codex_auth_required", "composer")
        if budget is not None or composer["model"] == "synthetic":
            raise DataError("invalid_subscription_config", "composer")
        return {
            "execution_enabled": True,
            "provider": "chatgpt_subscription",
            "max_attempts": 2,
        }
    if not authorized:
        raise DataError("model_not_authorized", "composer")
    # The API-billed mode is closed: no trusted API project spending constraint is
    # verified, and a declaration in a run config cannot attest to enforcement.
    raise DataError("provider_enforcement_unverified", "model_budget")


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
