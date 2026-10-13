"""Unmodified CORPORA host and CLI at Harbor's installed-agent seam."""

import asyncio
import logging
import re
import shlex
import time
from datetime import UTC, datetime
from typing import TypedDict, cast, override

from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from workflow_bench.composer import SessionSafeCodex
from workflow_bench.contracts import JsonValue
from workflow_bench.data import MAX_JSON_BYTES, DataError, decode_json
from workflow_bench.observability import format_phase_line

LOGGER = logging.getLogger(__name__)

SAPIENS_REVISION = "71e93cb3de00183c263ec440919b313cf92ed8af"
HOST_PORT = 4174
HOST_URL = f"http://127.0.0.1:{HOST_PORT}"
DATA_DIR = "/tmp/sapiens-data"
CLI = "python -m sapiens.corpora.host.cli --url " + HOST_URL + " --format json "


class _CliResponse(TypedDict):
    schema_version: int
    ok: bool
    data: dict[str, JsonValue]


class SapiensInstalledAgent(SessionSafeCodex):
    """Use Harbor's Codex config/MCP/auth seams, with Sapiens owning planning."""

    capabilities = AgentCapabilities(native_config=True, mcp_servers=True)

    @staticmethod
    def name() -> str:
        """Return the native Harbor agent name."""
        return "sapiens"

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        """Verify the prepared image has the required Sapiens and Codex versions."""
        # Images are prepared before execution; never install over the runtime network.
        result = await self.exec_as_agent(
            environment,
            command="test "
            + shlex.quote(SAPIENS_REVISION)
            + ' = "$(cat /opt/sapiens/REVISION)" && codex --version && command -v ps',
        )
        if result.return_code or not await self._installed_codex_satisfies_version(
            environment
        ):
            raise RuntimeError("sapiens_image_unprepared")

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        """Submit one instruction to a fresh Sapiens host and await its completion."""
        started = time.monotonic()
        phase_result = "failed"
        try:
            await self._run_sapiens(instruction, environment, context)
            phase_result = "completed"
        except asyncio.CancelledError:
            phase_result = "cancelled"
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

    async def _run_sapiens(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        """Submit once to the host and await the Chief turn's terminal state."""
        if self.model_name is None:
            raise RuntimeError("sapiens_model_required")
        home = self._REMOTE_CODEX_HOME.as_posix()
        env = {
            "CODEX_HOME": home,
            "SAPIENS_CODEX_MODEL": self.model_name.split("/")[-1],
            "SAPIENS_CODEX_REASONING_EFFORT": self._base_config[
                "model_reasoning_effort"
            ],
        }
        checked = await self.exec_as_agent(
            environment,
            command=f"test ! -e {home} && test ! -e {DATA_DIR} && mkdir -m 700 {home}",
            env=env,
        )
        if checked.return_code:
            raise RuntimeError("sapiens_home_not_fresh")
        auth = self._resolve_auth_json_path()
        if auth:
            # Harbor resolves only the explicit auth source supplied after preflight.
            await self._upload_agent_owned_file(environment, auth, home + "/auth.json")
        else:
            result = await self.exec_as_agent(
                environment,
                command="python -c "
                + shlex.quote(
                    "import json,os; from pathlib import Path; "
                    "Path(os.environ['CODEX_HOME'],'auth.json').write_text("
                    "json.dumps({'OPENAI_API_KEY':os.environ['OPENAI_API_KEY']}))"
                ),
                env=env,
            )
            if result.return_code:
                raise RuntimeError("sapiens_auth_setup_failed")
        await self._upload_effective_config(
            environment,
            self._build_effective_config(self.model_connection.configured_base_url),
            home + "/config.toml",
        )
        await self.exec_as_agent(
            environment, command=f"chmod 600 {home}/auth.json", env=env
        )
        logs = self.environment_logs_dir.as_posix()
        # Write native sessions directly into Harbor's log collection. Copying in
        # finally is too late: cancellation stops the container before agent cleanup.
        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -m 700 {logs}/sessions && ln -s {logs}/sessions {home}/sessions"
            ),
            env=env,
        )
        started = await self.exec_as_agent(
            environment,
            command=(
                f"python -m sapiens --port {HOST_PORT} --data-dir {DATA_DIR}"
                f" > {logs}/sapiens-host.txt 2>&1 & echo $! > /tmp/sapiens-host.pid"
            ),
            env=env,
        )
        if started.return_code:
            raise RuntimeError("sapiens_host_start_failed")
        for _ in range(50):
            ready = await environment.exec(
                command=CLI + "doctor", env=env, timeout_sec=6
            )
            if ready.return_code == 0:
                (self.logs_dir / "sapiens-doctor.json").write_text(ready.stdout or "")
                break
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError("sapiens_host_unavailable")
        # Submission and observation are separate; never repeat an uncertain write.
        accepted = await environment.exec(
            command=CLI + "chat " + shlex.quote(self.render_instruction(instruction)),
            env=env,
        )
        (self.logs_dir / "sapiens-accepted.json").write_text(accepted.stdout or "")
        receipt = self._response(accepted.stdout)
        if accepted.return_code or not receipt.get("ok"):
            raise RuntimeError("sapiens_submission_unknown")
        turn_id = receipt["data"].get("id")
        if not isinstance(turn_id, str) or not re.fullmatch(r"[a-f0-9]{32}", turn_id):
            raise RuntimeError("sapiens_submission_unknown")
        started = time.monotonic()
        LOGGER.info(
            "phase=sapiens-observation sapiens_turn_id=%s result=started", turn_id
        )
        observer = asyncio.create_task(
            environment.exec(
                command=CLI + "conversation watch " + shlex.quote(turn_id), env=env
            )
        )
        try:
            while not observer.done():
                done, _ = await asyncio.wait({observer}, timeout=30)
                if not done:
                    LOGGER.info(
                        "phase=sapiens-observation sapiens_turn_id=%s elapsed=%.0fs",
                        turn_id,
                        time.monotonic() - started,
                    )
            observed = await observer
        finally:
            if not observer.done():
                observer.cancel()
                await asyncio.gather(observer, return_exceptions=True)
        (self.logs_dir / "sapiens-terminal.json").write_text(observed.stdout or "")
        terminal = self._response(observed.stdout)
        has_completed = (
            observed.return_code == 0
            and terminal["ok"]
            and terminal["data"].get("state") == "Completed"
        )
        LOGGER.info(
            "phase=sapiens-observation sapiens_turn_id=%s result=%s elapsed=%.2fs",
            turn_id,
            "completed" if has_completed else "not_completed",
            time.monotonic() - started,
        )
        if not has_completed:
            raise RuntimeError("sapiens_terminal_not_completed")
        context.model_usage = {}

    @staticmethod
    def _response(stdout: str | None) -> _CliResponse:
        raw = (stdout or "").encode()
        if len(raw) > MAX_JSON_BYTES:
            raise RuntimeError("sapiens_response_too_large")
        try:
            value = decode_json(raw, "sapiens_cli")
        except DataError:
            raise RuntimeError("sapiens_response_invalid") from None
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or not isinstance(value.get("ok"), bool)
            or not isinstance(value.get("data"), dict)
        ):
            raise RuntimeError("sapiens_response_invalid")
        return cast(_CliResponse, value)
