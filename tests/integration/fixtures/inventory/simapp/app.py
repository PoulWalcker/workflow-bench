"""An independent inventory application for the model-free Composer control."""

import asyncio
import os
import secrets
import signal
import socket
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from aiohttp import web

from workflow_bench.data import (
    MAX_JSON_BYTES,
    decode_json,
    read_json,
    resource_schema,
    validate_contract,
    validate_json,
)

ROOT = Path(__file__).resolve().parent
TOOLS = read_json(ROOT / "tools.json", "tools")
STATE_SCHEMA = read_json(ROOT / "state.schema.json", "state_schema")


async def serve():
    state, identity, before, frozen = {}, None, None, None
    events, capability, calls, maximum, admission = [], None, 0, 0, False
    pending, drained = {}, asyncio.Event()
    drained.set()
    timeout, expiry = None, 0
    revision = 0

    async def control(request):
        nonlocal \
            state, \
            identity, \
            before, \
            frozen, \
            capability, \
            maximum, \
            admission, \
            timeout, \
            expiry
        if (
            request.headers.get("Authorization")
            != "Bearer " + os.environ["WB_CONTROL_KEY"]
        ):
            raise web.HTTPForbidden()
        operation = (
            "export" if request.method == "GET" else request.match_info["operation"]
        )
        if operation == "export":
            if frozen is None:
                raise web.HTTPConflict()
            return web.json_response(frozen)
        async with asyncio.timeout(
            timeout
            or resource_schema("e1.schema.json")["properties"]["control_timeout_sec"][
                "maximum"
            ]
        ):
            data = decode_json(await request.read(), "control")
        validate_contract("identity", data["identity"])
        if operation == "reset":
            assert identity is None
            validate_json(data["state"], STATE_SCHEMA, "state")
            assert data["profile"] == TOOLS["profile"]
            identity, state = data["identity"], deepcopy(data["state"])
            timeout = data["limits"]["call_timeout_sec"]
            before = {"revision": 0, "state": deepcopy(state)}
            return web.json_response({"before_ref": "/before"})
        assert data["identity"] == identity
        if operation == "issue":
            capability, maximum, admission = (
                secrets.token_hex(32),
                data["max_calls"],
                True,
            )
            expiry = time.monotonic() + data["ttl_sec"]
            return web.json_response({"capability": capability})
        admission = False
        if operation == "freeze":
            try:
                async with asyncio.timeout(data["drain_sec"]):
                    await drained.wait()
            except TimeoutError:
                pass
            if frozen is not None:
                return web.json_response(
                    {
                        "freeze_status": frozen["freeze_status"],
                        "pending_call_ids": frozen["pending_call_ids"],
                    }
                )
            for call_id, (name, arguments, error) in pending.items():
                events.append(
                    {
                        "seq": len(events) + 1,
                        "call_id": call_id,
                        "actor": "workflow",
                        "profile": TOOLS["profile"],
                        "operation": name,
                        "arguments": arguments,
                        "stage": "response",
                        "details": {"status": "unknown", "error": error},
                        "timestamp": time.time(),
                    }
                )
            frozen = {
                "schema_version": "1.0",
                "identity": identity,
                "before": before,
                "after": {"revision": revision, "state": deepcopy(state)},
                "events": deepcopy(events),
                "violations": [],
                "freeze_status": "incomplete" if pending else "complete",
                "pending_call_ids": list(pending),
            }
        return web.json_response({"closed": True})

    async def tool(request):
        nonlocal calls, revision
        name = request.match_info["name"]
        call_id, error, arguments, result = uuid4().hex, None, {}, None
        if (
            not admission
            or time.monotonic() >= expiry
            or request.headers.get("Authorization") != "Bearer " + str(capability)
        ):
            error = "forbidden"
        elif calls >= maximum:
            error = "limit_exceeded"
        else:
            calls += 1
            spec = next((tool for tool in TOOLS["tools"] if tool["name"] == name), None)
            try:
                async with asyncio.timeout(timeout):
                    data = decode_json(await request.read(), "tool")
                assert spec is not None and data["schema_version"] == "1.0"
                validate_json(data["arguments"], spec["arguments_schema"], "arguments")
                arguments = data["arguments"]
            except (ValueError, KeyError, AssertionError, TimeoutError):
                error = "invalid_arguments"
        if frozen is not None:
            return web.json_response(
                {"call_id": call_id, "error": {"code": "forbidden", "retryable": False}}
            )
        if error is None and (not admission or time.monotonic() >= expiry):
            error = "forbidden"
        effect = {"status": "no_effect", "message_id": None}
        admission_error = error
        if error is None:
            item = arguments["item"]
            if name == "inventory":
                result = deepcopy(state)
            elif item not in state["stock"]:
                error = "not_found"
            else:
                state["stock"].remove(item)
                state["reservations"].append(item)
                revision += 1
                result = {"reserved": item}
                effect = {
                    "status": "committed",
                    "message_id": call_id,
                    "evidence_ref": "/after/state/reservations",
                }
        for stage, details in [
            (
                "accepted",
                {
                    "status": "accepted" if admission_error is None else "rejected",
                    "error": admission_error,
                },
            ),
            ("effect", effect),
        ]:
            events.append(
                {
                    "seq": len(events) + 1,
                    "call_id": call_id,
                    "actor": "workflow",
                    "profile": TOOLS["profile"],
                    "operation": name,
                    "arguments": arguments,
                    "stage": stage,
                    "details": details,
                    "timestamp": time.time(),
                }
            )
        pending[call_id] = (name, arguments, error)
        drained.clear()
        response = web.json_response(
            {
                "call_id": call_id,
                **(
                    {"error": {"code": error, "retryable": False}}
                    if error
                    else {"result": result}
                ),
            }
        )
        status = "unknown"
        try:
            async with asyncio.timeout(timeout):
                await response.prepare(request)
                await response.write_eof()
            status = "sent"
        except (ConnectionError, TimeoutError):
            status = "failed"
        finally:
            if frozen is None:
                events.append(
                    {
                        "seq": len(events) + 1,
                        "call_id": call_id,
                        "actor": "workflow",
                        "profile": TOOLS["profile"],
                        "operation": name,
                        "arguments": arguments,
                        "stage": "response",
                        "details": {"status": status, "error": error},
                        "timestamp": time.time(),
                    }
                )
            pending.pop(call_id, None)
            if not pending:
                drained.set()
        return response

    tools, management = (
        web.Application(client_max_size=MAX_JSON_BYTES),
        web.Application(client_max_size=MAX_JSON_BYTES),
    )
    tools.router.add_post("/tools/{name}", tool)
    management.router.add_post("/control/{operation}", control)
    management.router.add_get("/control/export", control)
    stopped = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopped.set)
    runners = []
    try:
        for app, host, port in [
            (tools, "0.0.0.0", int(os.environ["WB_TOOLS_PORT"])),
            (
                management,
                socket.gethostbyname("control"),
                int(os.environ["WB_CONTROL_PORT"]),
            ),
        ]:
            runner = web.AppRunner(app, access_log=None)
            runners.append(runner)
            await runner.setup()
            await web.TCPSite(runner, host, port).start()
        await stopped.wait()
    finally:
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(serve())
