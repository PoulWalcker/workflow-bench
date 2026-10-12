"""Capability-scoped app transport and separate host control listener."""

import asyncio
import logging
import os
import secrets
import signal
import socket
import time
from copy import deepcopy
from typing import Protocol
from uuid import uuid4

from aiohttp import web

from workflow_bench.contracts import JsonValue
from workflow_bench.data import (
    MAX_JSON_BYTES,
    DataError,
    decode_json,
    resource_schema,
    validate_contract,
    validate_json,
)

LIMITS = resource_schema("e1.schema.json")["properties"]
MAX_JOURNALED_REQUESTS = (
    resource_schema("wire.schema.json")["$defs"]["evidence_v1"]["properties"]["events"][
        "maxItems"
    ]
    // 3
)
LOGGER = logging.getLogger(__name__)


class ToolError(ValueError):
    def __init__(self, code: str, violation: str | None = None) -> None:
        self.code = code
        self.violation = violation
        super().__init__(code)


class Application(Protocol):
    tools: dict[str, JsonValue]
    state_schema: dict[str, JsonValue]
    state: dict[str, JsonValue]
    evidence_version: str
    identity_contract: str
    actor: str
    fault_operations: set[str]
    fault_modes: set[str]
    close_on_limit: bool

    def check_state(self, state: dict[str, JsonValue]) -> None: ...

    def validate_arguments(self, operation: str, arguments: JsonValue) -> None: ...

    def forbidden_violation(self, operation: str) -> str | None: ...

    def perform(
        self,
        operation: str,
        arguments: dict[str, JsonValue],
        revision: int,
        scope: str,
        *,
        incomplete: bool = False,
    ) -> tuple[JsonValue, str | None, dict[str, JsonValue]]: ...


class Simulator:
    """Shared capability, transport and protected freeze; semantics stay in app."""

    def __init__(self, control_key: str, application: Application) -> None:
        self.application = application
        self.scope = uuid4().hex
        self.control_key = control_key
        self.lock = asyncio.Lock()
        self.identity: dict[str, str] | None = None
        self.before: dict[str, JsonValue] | None = None
        self.events: list[dict[str, JsonValue]] = []
        self.revision = 0
        self.capability: str | None = None
        self.expiry = 0.0
        self.max_calls = 0
        self.calls = 0
        self.requests = 0
        self.violations: list[str] = []
        self.call_timeout = 0.0
        self.admission = False
        self.frozen: dict[str, JsonValue] | None = None
        self.fault_mode: str | None = None
        self.fault_delay = 0.0
        self.pending: dict[str, tuple[str, JsonValue, str]] = {}
        self.drained = asyncio.Event()
        self.drained.set()

    async def control(self, request: web.Request) -> web.Response:
        if not secrets.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + self.control_key
        ):
            raise web.HTTPForbidden()
        operation = request.match_info["operation"]
        content = None
        if not (operation == "export" and request.method == "GET"):
            async with asyncio.timeout(
                self.call_timeout or LIMITS["control_timeout_sec"]["maximum"]
            ):
                content = await request.read()
        async with self.lock:
            if operation == "export" and request.method == "GET":
                if self.frozen is None:
                    raise web.HTTPConflict()
                return web.json_response(self.frozen)
            try:
                data = decode_json(content, "control")
                if not isinstance(data, dict):
                    raise ValueError()
                fields = {
                    "reset": {"identity", "state", "profile", "limits"},
                    "issue": {"identity", "actor", "ttl_sec", "max_calls"},
                    "revoke": {"identity"},
                    "freeze": {"identity", "drain_sec"},
                    "fault": {"identity", "mode", "delay_sec"},
                }
                if operation not in fields or set(data) != fields[operation]:
                    raise ValueError()
                validate_contract(self.application.identity_contract, data["identity"])
                if operation != "reset" and data["identity"] != self.identity:
                    raise ValueError()
                if operation == "reset":
                    if self.identity is not None:
                        raise ValueError()
                    validate_json(data["state"], self.application.state_schema, "state")
                    self.application.check_state(data["state"])
                    if data["profile"] != self.application.tools["profile"]:
                        raise ValueError()
                    if not isinstance(data["limits"], dict) or set(data["limits"]) != {
                        "call_timeout_sec"
                    }:
                        raise ValueError()
                    validate_json(
                        data["limits"]["call_timeout_sec"],
                        LIMITS["tool_timeout_sec"],
                        "call_timeout",
                    )
                    self.identity = data["identity"]
                    self.application.state = deepcopy(data["state"])
                    self.before = {
                        "revision": 0,
                        "state": deepcopy(self.application.state),
                    }
                    self.call_timeout = float(data["limits"]["call_timeout_sec"])
                    return web.json_response({"before_ref": "/before"})
                if operation == "issue":
                    if (
                        self.identity is None
                        or self.capability is not None
                        or self.frozen is not None
                        or data["identity"] != self.identity
                    ):
                        raise ValueError()
                    validate_json(
                        data["ttl_sec"],
                        {"type": "number", "exclusiveMinimum": 0},
                        "ttl",
                    )
                    validate_json(data["max_calls"], LIMITS["max_calls"], "max_calls")
                    ttl, calls = float(data["ttl_sec"]), data["max_calls"]
                    if data["actor"] != self.application.actor:
                        raise ValueError()
                    self.capability = secrets.token_hex(32)
                    self.expiry = time.monotonic() + ttl
                    self.max_calls = calls
                    self.admission = True
                    return web.json_response({"capability": self.capability})
                if operation == "revoke":
                    self.admission = False
                    return web.json_response({"revoked": True})
                if operation == "fault":
                    if (
                        data["mode"] not in self.application.fault_modes
                        or self.frozen is not None
                    ):
                        raise ValueError()
                    validate_json(
                        data["delay_sec"],
                        {"type": "number", "minimum": 0, "maximum": 3600},
                        "fault_delay",
                    )
                    self.fault_delay = float(data["delay_sec"])
                    self.fault_mode = data["mode"]
                    return web.json_response({"configured": True})
                if operation == "freeze":
                    validate_json(
                        data["drain_sec"], LIMITS["drain_timeout_sec"], "drain"
                    )
                    self.admission = False
                else:
                    raise ValueError()
            except (DataError, ValueError, KeyError, TypeError):
                raise web.HTTPBadRequest(reason="invalid_control") from None
        try:
            async with asyncio.timeout(data["drain_sec"]):
                await self.drained.wait()
        except TimeoutError:
            pass
        async with self.lock:
            if self.frozen is None:
                pending_ids = list(self.pending)
                for call_id, (name, arguments, stage) in self.pending.items():
                    if stage == "accepted":
                        self._event(
                            call_id,
                            name,
                            arguments,
                            "effect",
                            {"status": "unknown", "message_id": None},
                        )
                    self._event(
                        call_id,
                        name,
                        arguments,
                        "response",
                        {"status": "unknown", "error": None},
                    )
                self.frozen = {
                    "schema_version": self.application.evidence_version,
                    "identity": self.identity,
                    "before": self.before,
                    "after": {
                        "revision": self.revision,
                        "state": deepcopy(self.application.state),
                    },
                    "events": deepcopy(self.events),
                    "violations": list(self.violations),
                    "freeze_status": "incomplete" if pending_ids else "complete",
                    "pending_call_ids": pending_ids,
                }
            return web.json_response(
                {
                    "freeze_status": self.frozen["freeze_status"],
                    "pending_call_ids": self.frozen["pending_call_ids"],
                }
            )

    def _event(
        self,
        call_id: str,
        operation: str,
        arguments: JsonValue,
        stage: str,
        details: JsonValue,
    ) -> None:
        self.events.append(
            {
                "seq": len(self.events) + 1,
                "call_id": call_id,
                "actor": self.application.actor,
                "profile": self.application.tools["profile"],
                "operation": operation,
                "arguments": arguments,
                "stage": stage,
                "details": details,
                "timestamp": time.time(),
            }
        )

    async def tool(self, request: web.Request) -> web.StreamResponse:
        operation = request.match_info["name"]
        async with self.lock:
            call_id = uuid4().hex
            error = None
            result: JsonValue = None
            arguments: JsonValue = {}
            authorized = self.capability is not None and secrets.compare_digest(
                request.headers.get("Authorization", ""), "Bearer " + self.capability
            )
            if self.frozen is not None:
                return web.json_response(
                    {
                        "call_id": call_id,
                        "error": {"code": "forbidden", "retryable": False},
                    }
                )
            if self.requests >= MAX_JOURNALED_REQUESTS:
                code = (
                    "forbidden"
                    if not authorized
                    or not self.admission
                    or time.monotonic() >= self.expiry
                    else "limit_exceeded"
                )
                violation = (
                    self.application.forbidden_violation(operation)
                    if code == "forbidden"
                    else None
                )
                for item in ("request_limit_exceeded", violation):
                    if item is not None and item not in self.violations:
                        self.violations.append(item)
                return web.json_response(
                    {"call_id": call_id, "error": {"code": code, "retryable": False}}
                )
            self.requests += 1
            if operation not in {
                tool["name"] for tool in self.application.tools["tools"]
            }:
                operation = "unsupported"
            if not authorized or not self.admission or time.monotonic() >= self.expiry:
                error = "forbidden"
            elif self.calls >= self.max_calls:
                error = "limit_exceeded"
                if self.application.close_on_limit:
                    self.admission = False
            else:
                self.calls += 1
        if error is None:
            try:
                async with asyncio.timeout(self.call_timeout):
                    content = await request.read()
                data = decode_json(content, "tool")
                if (
                    set(data) != {"schema_version", "arguments"}
                    or data["schema_version"] != "1.0"
                ):
                    raise ValueError()
                self.application.validate_arguments(operation, data["arguments"])
                arguments = data["arguments"]
            except ToolError as failure:
                error = failure.code
                if (
                    failure.violation is not None
                    and failure.violation not in self.violations
                ):
                    self.violations.append(failure.violation)
            except (
                DataError,
                ValueError,
                TypeError,
                KeyError,
                StopIteration,
                TimeoutError,
            ):
                error = "invalid_arguments"
        async with self.lock:
            if self.frozen is not None:
                return web.json_response(
                    {
                        "call_id": call_id,
                        "error": {"code": "forbidden", "retryable": False},
                    }
                )
            if error is None and (
                not self.admission or time.monotonic() >= self.expiry
            ):
                error = "forbidden"
            self._event(
                call_id,
                operation,
                arguments,
                "accepted",
                {"status": "accepted" if error is None else "rejected", "error": error},
            )
            admitted = error is None
            mode = (
                self.fault_mode
                if admitted and operation in self.application.fault_operations
                else None
            )
            delay = self.fault_delay
            if mode:
                self.fault_mode = None
            self.pending[call_id] = (operation, arguments, "accepted")
            self.drained.clear()
        if mode == "stall_before_commit":
            await asyncio.sleep(delay)
        async with self.lock:
            if self.frozen is not None:
                self.pending.pop(call_id, None)
                if not self.pending:
                    self.drained.set()
                return web.json_response(
                    {
                        "call_id": call_id,
                        "error": {
                            "code": error or "transport_unknown",
                            "retryable": False,
                        },
                    }
                )
            effect: dict[str, JsonValue] = {"status": "no_effect", "message_id": None}
            if error is None:
                result, error, effect = self.application.perform(
                    operation,
                    arguments,
                    self.revision,
                    self.scope,
                    incomplete=mode == "incomplete_observation",
                )
                if effect["status"] == "committed":
                    self.revision += 1
            self._event(call_id, operation, arguments, "effect", effect)
            self.pending[call_id] = (operation, arguments, "effect")
            body = (
                {"call_id": call_id, "error": {"code": error, "retryable": False}}
                if error
                else {"call_id": call_id, "result": result}
            )
        response = web.json_response(body)
        status = "unknown"
        try:
            if mode == "drop_response" and effect["status"] == "committed":
                if request.transport is not None:
                    request.transport.abort()
                raise ConnectionResetError()
            async with asyncio.timeout(self.call_timeout):
                await response.prepare(request)
                await response.write_eof()
            status = "sent"
        except (ConnectionError, TimeoutError):
            status = "failed"
        finally:
            async with self.lock:
                if self.frozen is None:
                    self._event(
                        call_id,
                        operation,
                        arguments,
                        "response",
                        {"status": status, "error": error},
                    )
                self.pending.pop(call_id, None)
                if not self.pending:
                    self.drained.set()
        return response


async def serve(application: Application) -> None:
    simulator = Simulator(os.environ["WB_CONTROL_KEY"], application)
    tools = web.Application(client_max_size=MAX_JSON_BYTES)
    tools.router.add_post("/tools/{name}", simulator.tool)
    control = web.Application(client_max_size=MAX_JSON_BYTES)
    control.router.add_post("/control/{operation}", simulator.control)
    control.router.add_get("/control/{operation}", simulator.control)
    runners = []
    stopped = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    try:
        for app, host, port in [
            (tools, "0.0.0.0", int(os.environ["WB_TOOLS_PORT"])),
            (
                control,
                socket.gethostbyname("control"),
                int(os.environ["WB_CONTROL_PORT"]),
            ),
        ]:
            runner = web.AppRunner(app, access_log=None)
            runners.append(runner)
            await runner.setup()
            await web.TCPSite(runner, host, port).start()
        LOGGER.info("phase=setup simulator ready")
        await stopped.wait()
    finally:
        for runner in reversed(runners):
            await runner.cleanup()
        LOGGER.info("phase=cleanup simulator stopped")
