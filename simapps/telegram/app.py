"""T1 state, capability-scoped tools and a separate host control listener."""

import asyncio
import json
import logging
import os
import secrets
import signal
import socket
import time
from copy import deepcopy
from pathlib import Path
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

ROOT = Path(__file__).resolve().parent
TOOLS = json.loads((ROOT / "tools.json").read_bytes())
STATE_SCHEMA = json.loads((ROOT / "state.schema.json").read_bytes())
LIMITS = resource_schema("e1.schema.json")["properties"]
MAX_JOURNALED_REQUESTS = (
    resource_schema("wire.schema.json")["$defs"]["evidence"]["properties"]["events"][
        "maxItems"
    ]
    // 3
)
LOGGER = logging.getLogger(__name__)


class Telegram:
    def __init__(self, control_key: str) -> None:
        self.control_key = control_key
        self.lock = asyncio.Lock()
        self.identity: dict[str, str] | None = None
        self.state: dict[str, JsonValue] = {"chats": [], "messages": []}
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
                validate_contract("identity", data["identity"])
                if operation != "reset" and data["identity"] != self.identity:
                    raise ValueError()
                if operation == "reset":
                    if self.identity is not None:
                        raise ValueError()
                    validate_json(data["state"], STATE_SCHEMA, "state")
                    self._check_state(data["state"])
                    if data["profile"] != TOOLS["profile"]:
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
                    self.state = deepcopy(data["state"])
                    self.before = {"revision": 0, "state": deepcopy(self.state)}
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
                    if data["actor"] != "workflow":
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
                        data["mode"] not in {"drop_response", "stall_before_commit"}
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
                    "schema_version": "1.0",
                    "identity": self.identity,
                    "before": self.before,
                    "after": {"revision": self.revision, "state": deepcopy(self.state)},
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

    @staticmethod
    def _check_state(state: dict[str, JsonValue]) -> None:
        chats = {chat["id"] for chat in state["chats"]}
        messages = {message["id"] for message in state["messages"]}
        if len(chats) != len(state["chats"]) or len(messages) != len(state["messages"]):
            raise ValueError()
        if any(message["chat_id"] not in chats for message in state["messages"]):
            raise ValueError()

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
                "actor": "workflow",
                "profile": TOOLS["profile"],
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
                for violation in (
                    "request_limit_exceeded",
                    *(
                        ["unauthorized_send"]
                        if operation == "send_message" and code == "forbidden"
                        else []
                    ),
                ):
                    if violation not in self.violations:
                        self.violations.append(violation)
                return web.json_response(
                    {"call_id": call_id, "error": {"code": code, "retryable": False}}
                )
            self.requests += 1
            if operation not in {tool["name"] for tool in TOOLS["tools"]}:
                operation = "unsupported"
            if not authorized or not self.admission or time.monotonic() >= self.expiry:
                error = "forbidden"
            elif self.calls >= self.max_calls:
                error = "limit_exceeded"
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
                spec = next(
                    tool for tool in TOOLS["tools"] if tool["name"] == operation
                )
                validate_json(data["arguments"], spec["arguments_schema"], "arguments")
                arguments = data["arguments"]
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
            mode = self.fault_mode if admitted and operation == "send_message" else None
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
                chat = next(
                    (
                        chat
                        for chat in self.state["chats"]
                        if chat["id"] == arguments["chat_id"]
                    ),
                    None,
                )
                if chat is None:
                    error = "not_found"
                elif operation == "get_chat":
                    result = deepcopy(chat)
                elif operation == "list_messages":
                    messages = [
                        m for m in self.state["messages"] if m["chat_id"] == chat["id"]
                    ]
                    if len(messages) > spec["limits"]["max_messages"]:
                        error = "limit_exceeded"
                    else:
                        result = deepcopy(messages)
                else:
                    result = {
                        "id": "m-" + uuid4().hex,
                        "chat_id": chat["id"],
                        "direction": "outgoing",
                        "text": arguments["text"],
                    }
                    self.state["messages"].append(deepcopy(result))
                    self.revision += 1
                    effect = {
                        "status": "committed",
                        "message_id": result["id"],
                        "evidence_ref": f"/after/state/messages/{len(self.state['messages']) - 1}",
                    }
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


async def serve() -> None:
    telegram = Telegram(os.environ["WB_CONTROL_KEY"])
    tools = web.Application(client_max_size=MAX_JSON_BYTES)
    tools.router.add_post("/tools/{name}", telegram.tool)
    control = web.Application(client_max_size=MAX_JSON_BYTES)
    control.router.add_post("/control/{operation}", telegram.control)
    control.router.add_get("/control/{operation}", telegram.control)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
