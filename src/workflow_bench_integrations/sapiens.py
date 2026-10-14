"""Unmodified CORPORA host and CLI at Harbor's installed-agent seam."""

import asyncio
import json
import re
import shlex
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast, override

from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.models.agent.context import AgentContext

from workflow_bench.composer import SessionSafeCodex, collect_sapiens_usage
from workflow_bench.contracts import JsonValue
from workflow_bench.data import MAX_JSON_BYTES, DataError, decode_json
from workflow_bench.harbor import DeadlineDockerEnvironment
from workflow_bench.observability import format_phase_line, format_sapiens_cli_line

SAPIENS_REVISION = "71e93cb3de00183c263ec440919b313cf92ed8af"
HOST_PORT = 4174
HOST_URL = f"http://127.0.0.1:{HOST_PORT}"
DATA_DIR = "/tmp/sapiens-data"
CLI = "python -m sapiens.corpora.host.cli --url " + HOST_URL + " --format json "


class _CliResponse(TypedDict):
    schema_version: int
    ok: bool
    data: dict[str, JsonValue]


type CompletionDecision = Literal["working", "completed", "agent_outcome"]


class SapiensTransitionTracker:
    """Return safe turn and workload state changes across public host snapshots."""

    _TURN_STATES = {
        "queued",
        "running",
        "output_pending",
        "done",
        "failed",
        "interrupted",
    }
    _WORKLOAD_STATES = {
        "Running",
        "Queued",
        "Delegated",
        "Completed",
        "WaitingForAdmin",
        "Failed",
        "Interrupted",
        "Unresolved",
    }

    def __init__(self, *, trial: str) -> None:
        self._trial = trial
        self._states: dict[tuple[str, str], str] = {}

    def observe(
        self, snapshot: Mapping[str, object], observed_at: datetime
    ) -> list[str]:
        """Return changed states, mapping unrecognized names to ``other``.

        Each first observed state is a change from ``none``. Repeated snapshots
        yield no lines.
        """
        timestamp = observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        lines = []
        for kind, records, field, vocabulary in (
            ("turn", snapshot.get("turns"), "status", self._TURN_STATES),
            ("workload", snapshot.get("workloads"), "state", self._WORKLOAD_STATES),
        ):
            if not isinstance(records, list):
                continue
            for record in records:
                if not isinstance(record, dict):
                    continue
                identifier, current = record.get("id"), record.get(field)
                if not isinstance(identifier, str) or not isinstance(current, str):
                    continue
                key = (kind, identifier)
                previous = self._states.get(key)
                if previous == current:
                    continue
                self._states[key] = current
                safe_id = (
                    identifier
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier)
                    else "other"
                )
                prior_name = previous if previous in vocabulary else "other"
                if previous is None:
                    prior_name = "none"
                current_name = current if current in vocabulary else "other"
                lines.append(
                    f"at={timestamp} phase=sapiens-transition trial={self._trial} "
                    f"kind={kind} id={safe_id} from={prior_name} to={current_name}"
                )
        return lines


class SapiensCompletion:
    """Decide when two observed Pulse ticks have no Sapiens work remaining."""

    def __init__(self) -> None:
        self._last_pulse: tuple[str, int] | None = None
        self._quiet_ticks = 0

    @property
    def quiet_ticks(self) -> int:
        """Return the consecutive quiet Pulse ticks in the latest observation."""
        return self._quiet_ticks

    def observe(self, snapshot: Mapping[str, object]) -> CompletionDecision:
        """Return a terminal decision only after two distinct quiet Pulse ticks.

        ``agent_outcome`` means Sapiens stopped without normal completion; the
        adapter returns so the independent verifier can judge task results.
        ``working`` keeps observation active. Invalid or incomplete public state
        raises rather than proving completion.
        """
        pulse = snapshot.get("pulse")
        turns = snapshot.get("turns")
        workloads = snapshot.get("workloads")
        run_activity = snapshot.get("run_activity")
        if (
            not isinstance(pulse, dict)
            or not isinstance(turns, list)
            or not isinstance(workloads, list)
            or not isinstance(run_activity, dict)
        ):
            raise RuntimeError("sapiens_state_invalid")
        numbers = pulse.get("numbers")
        identity = pulse.get("id")
        tick = numbers.get("bpm60") if isinstance(numbers, dict) else None
        if (
            not isinstance(identity, str)
            or not isinstance(tick, int)
            or isinstance(tick, bool)
            or tick < 0
            or any(
                not isinstance(turn, dict) or not isinstance(turn.get("status"), str)
                for turn in turns
            )
            or any(
                not isinstance(work, dict) or not isinstance(work.get("state"), str)
                for work in workloads
            )
        ):
            raise RuntimeError("sapiens_state_invalid")
        current_pulse = (identity, tick)
        is_busy = (
            any(
                turn["status"] in {"queued", "running", "output_pending"}
                for turn in turns
            )
            or any(
                work["state"] in {"Running", "Queued", "Delegated"}
                for work in workloads
            )
            or bool(run_activity)
        )
        if is_busy:
            self._quiet_ticks = 0
        if current_pulse == self._last_pulse:
            return "working"
        if self._last_pulse is not None and (
            identity != self._last_pulse[0] or tick != self._last_pulse[1] + 1
        ):
            self._quiet_ticks = 0
        self._last_pulse = current_pulse
        self._quiet_ticks = 0 if is_busy else self._quiet_ticks + 1
        if self._quiet_ticks < 2:
            return "working"
        is_agent_outcome = any(
            work["state"] in {"WaitingForAdmin", "Failed", "Interrupted", "Unresolved"}
            for work in workloads
        ) or any(turn["status"] in {"failed", "interrupted"} for turn in turns)
        return "agent_outcome" if is_agent_outcome else "completed"


class SapiensInstalledAgent(SessionSafeCodex):
    """Use Harbor's Codex config/MCP/auth seams, with Sapiens owning planning."""

    capabilities = AgentCapabilities(native_config=True, mcp_servers=True)
    _last_outcome: CompletionDecision | None = None

    @staticmethod
    def name() -> str:
        """Return the native Harbor agent name."""
        return "sapiens"

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        """Report all validated Codex sessions while blocking trajectory fallback."""
        usage = collect_sapiens_usage(self.logs_dir)
        context.n_input_tokens = usage["input_tokens"]
        context.n_cache_tokens = usage["cached_input_tokens"]
        context.n_output_tokens = usage["output_tokens"]
        metadata = dict(context.metadata or {})
        metadata["sapiens_session_count"] = usage["session_count"]
        if self._last_outcome is not None:
            metadata["sapiens_outcome"] = self._last_outcome
        context.metadata = metadata
        context.model_usage = {}

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        """Verify the prepared image has the required Sapiens and Codex versions."""
        # Images are prepared before execution; never install over the runtime network.
        result = await self.exec_as_agent(
            environment,
            command="test "
            + shlex.quote(SAPIENS_REVISION)
            + ' = "$(cat /opt/sapiens/REVISION)" && codex --version',
        )
        if result.return_code or not await self._installed_codex_satisfies_version(
            environment
        ):
            raise RuntimeError("sapiens_image_unprepared")

    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        """Submit once, stop on cancellation, then let Harbor collect logs."""
        started = time.monotonic()
        phase_result = "failed"
        self._last_outcome = None
        try:
            phase_result = await self._run_sapiens(instruction, environment)
            self._last_outcome = phase_result
        except asyncio.CancelledError:
            phase_result = "cancelled"
            if (
                isinstance(environment, DeadlineDockerEnvironment)
                and environment.cancel_writer is not None
            ):
                # Observation can be cancelled between Docker exec calls.
                await environment.cancel_writer()
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
        self, instruction: str, environment: BaseEnvironment
    ) -> CompletionDecision:
        """Submit once to the host and return all Sapiens work's terminal state."""
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
            ready = await self._sapiens_cli(
                environment, "doctor", CLI + "doctor", env, timeout_sec=6
            )
            if ready.return_code == 0:
                (self.logs_dir / "sapiens-doctor.json").write_text(ready.stdout or "")
                break
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError("sapiens_host_unavailable")
        # Submission and observation are separate; never repeat an uncertain write.
        submitted_argument = self.render_instruction(instruction)
        accepted = await self._sapiens_cli(
            environment,
            "chat",
            CLI + "chat " + shlex.quote(submitted_argument),
            env,
            submitted_argument=submitted_argument,
        )
        (self.logs_dir / "sapiens-accepted.json").write_text(accepted.stdout or "")
        receipt = self._response(accepted.stdout)
        if accepted.return_code or not receipt.get("ok"):
            raise RuntimeError("sapiens_submission_unknown")
        turn_id = receipt["data"].get("id")
        if not isinstance(turn_id, str) or not re.fullmatch(r"[a-f0-9]{32}", turn_id):
            raise RuntimeError("sapiens_submission_unknown")
        started = time.monotonic()
        self.logger.info(
            "%s sapiens_turn_id=%s",
            format_phase_line(
                "sapiens-observation",
                "started",
                0,
                datetime.now(UTC),
                trial=self.logs_dir.parent.name,
            ),
            turn_id,
        )
        completion = SapiensCompletion()
        transitions = SapiensTransitionTracker(trial=self.logs_dir.parent.name)
        state_command = "python -c " + shlex.quote(
            "import sys,urllib.request; "
            f"sys.stdout.buffer.write(urllib.request.urlopen('{HOST_URL}/api/state',"
            f"timeout=5).read({MAX_JSON_BYTES + 1}))"
        )
        while True:
            observed = await environment.exec(
                command=state_command, env=env, timeout_sec=6
            )
            if observed.return_code:
                raise RuntimeError("sapiens_state_unavailable")
            raw_state = (observed.stdout or "").encode()
            if len(raw_state) > MAX_JSON_BYTES:
                raise RuntimeError("sapiens_state_too_large")
            try:
                snapshot = decode_json(raw_state, "sapiens_state")
            except DataError:
                raise RuntimeError("sapiens_state_invalid") from None
            if not isinstance(snapshot, dict):
                raise RuntimeError("sapiens_state_invalid")
            decision = completion.observe(snapshot)
            for line in transitions.observe(snapshot, datetime.now(UTC)):
                self.logger.info(line)
            if decision != "working":
                break
            await asyncio.sleep(0.2)
        # Record state names only; the public snapshot can include private requests.
        turns = cast(list[dict[str, object]], snapshot["turns"])
        workloads = cast(list[dict[str, object]], snapshot["workloads"])
        workload_states = sorted({cast(str, work["state"]) for work in workloads})
        (self.logs_dir / "sapiens-terminal.json").write_text(
            json.dumps(
                {
                    "turn_id": turn_id,
                    "outcome": decision,
                    "workload_states": workload_states,
                }
            )
        )
        # Export only the transcript fields while the host database is still live.
        # This is diagnostic: a failed export cannot change the Trial outcome.
        try:
            snapshot_source = Path(__file__).with_name("sapiens_state.py").read_text()
            copied = await environment.exec(
                command="python -c "
                + shlex.quote(snapshot_source)
                + " "
                + shlex.quote(DATA_DIR)
                + " "
                + shlex.quote(logs + "/sapiens-state.json"),
                env=env,
                timeout_sec=15,
            )
        except Exception:
            self.logger.warning(
                "phase=sapiens-state trial=%s result=unavailable",
                self.logs_dir.parent.name,
            )
        else:
            if copied.return_code:
                self.logger.warning(
                    "phase=sapiens-state trial=%s result=unavailable",
                    self.logs_dir.parent.name,
                )
        # State names can be untrusted strings; log only the known vocabulary.
        turn_states = sorted({cast(str, turn["status"]) for turn in turns})
        turn_states_for_log = (
            ",".join(
                sorted(
                    {
                        status
                        if status
                        in {
                            "queued",
                            "running",
                            "output_pending",
                            "done",
                            "failed",
                            "interrupted",
                        }
                        else "other"
                        for status in turn_states
                    }
                )
            )
            or "none"
        )
        workload_states_for_log = (
            ",".join(
                sorted(
                    {
                        state
                        if state
                        in {
                            "Running",
                            "Queued",
                            "Delegated",
                            "Completed",
                            "WaitingForAdmin",
                            "Failed",
                            "Interrupted",
                            "Unresolved",
                        }
                        else "other"
                        for state in workload_states
                    }
                )
            )
            or "none"
        )
        self.logger.info(
            "%s sapiens_turn_id=%s elapsed=%.2fs turn_states=%s workload_states=%s "
            "run_activity_empty=%s quiet_ticks=%s",
            format_phase_line(
                "sapiens-observation",
                decision,
                time.monotonic() - started,
                datetime.now(UTC),
                trial=self.logs_dir.parent.name,
            ),
            turn_id,
            time.monotonic() - started,
            turn_states_for_log,
            workload_states_for_log,
            str(not snapshot["run_activity"]).lower(),
            completion.quiet_ticks,
        )
        return decision

    async def _sapiens_cli(
        self,
        environment: BaseEnvironment,
        subcommand: Literal["doctor", "chat"],
        command: str,
        env: dict[str, str],
        *,
        timeout_sec: int | None = None,
        submitted_argument: str | None = None,
    ) -> ExecResult:
        """Run one CLI attempt and log its sanitized result even if it raises."""
        started = time.monotonic()
        response: ExecResult | None = None
        try:
            response = await environment.exec(
                command=command, env=env, timeout_sec=timeout_sec
            )
            return response
        finally:
            self.logger.info(
                format_sapiens_cli_line(
                    subcommand,
                    response.return_code if response is not None else None,
                    time.monotonic() - started,
                    (response.stdout or response.stderr)
                    if response is not None
                    else None,
                    datetime.now(UTC),
                    trial=self.logs_dir.parent.name,
                    submitted_argument=submitted_argument,
                )
            )

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
