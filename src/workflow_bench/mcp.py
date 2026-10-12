"""Minimal newline JSON-RPC stdio transport over the simulator HTTP contract."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from workflow_bench.contracts import JsonValue
from workflow_bench.data import MAX_JSON_BYTES, decode_json, read_json


def serve(
    contract: dict[str, JsonValue],
    *,
    tool_url: str,
    capability: str,
    timeout_sec: float,
) -> None:
    tools = {tool["name"]: tool for tool in contract["tools"]}
    # Ambient proxy settings must not redirect the capability outside the sandbox.
    opener = build_opener(ProxyHandler({}))
    while line := sys.stdin.buffer.readline(MAX_JSON_BYTES + 1):
        try:
            request = decode_json(line, "mcp_request")
            if "id" not in request:
                continue
            method = request.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": request.get("params", {}).get(
                        "protocolVersion", "2024-11-05"
                    ),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "workflow-bench-tools", "version": "1.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": tool["name"],
                            "description": tool["description"],
                            "inputSchema": tool["arguments_schema"],
                        }
                        for tool in tools.values()
                    ]
                }
            elif method == "tools/call":
                params = request.get("params", {})
                name = params.get("name")
                payload = {"error": "forbidden"}
                if name in tools:
                    body = json.dumps(
                        {
                            "schema_version": "1.0",
                            "arguments": params.get("arguments", {}),
                        }
                    ).encode()
                    http = Request(
                        tool_url + "/tools/" + name,
                        data=body,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": "Bearer " + capability,
                        },
                    )
                    try:
                        with opener.open(http, timeout=timeout_sec) as response:
                            payload = decode_json(
                                response.read(MAX_JSON_BYTES + 1), "tool_response"
                            )
                    except HTTPError as error:
                        payload = decode_json(
                            error.read(MAX_JSON_BYTES + 1), "tool_response"
                        )
                    except (URLError, TimeoutError, OSError):
                        payload = {"error": "transport_unknown"}
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(payload, ensure_ascii=False),
                        }
                    ],
                    "isError": "error" in payload,
                }
            else:
                print(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request["id"],
                            "error": {"code": -32601, "message": "Method not found"},
                        }
                    ),
                    flush=True,
                )
                continue
            print(
                json.dumps(
                    {"jsonrpc": "2.0", "id": request["id"], "result": result},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid request"},
                    }
                ),
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", required=True)
    parser.add_argument("--connection")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    connection = (
        read_json(Path(args.connection), "connection")
        if args.connection
        else {
            "tool_url": os.environ["WB_TOOL_URL"],
            "capability": os.environ["WB_CAPABILITY"],
        }
    )
    serve(
        read_json(Path(args.contract), "tools"),
        tool_url=connection["tool_url"],
        capability=connection["capability"],
        timeout_sec=args.timeout,
    )


if __name__ == "__main__":
    main()
