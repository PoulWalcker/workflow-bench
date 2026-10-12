"""The stdio MCP surface exports only the installed public tool contract."""

import json
import os
import subprocess
import sys


def test_stdio_lists_public_tools_and_rejects_admin_without_http(native_task_files):
    _, contract = native_task_files
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "reset", "arguments": {}},
        },
    ]
    result = subprocess.run(
        [sys.executable, "-m", "workflow_bench.mcp", "--contract", str(contract)],
        input="".join(json.dumps(item) + "\n" for item in requests),
        capture_output=True,
        text=True,
        timeout=5,
        env={
            **os.environ,
            "WB_TOOL_URL": "http://unreachable.invalid",
            "WB_CAPABILITY": "synthetic",
        },
    )
    assert result.returncode == 0, result.stderr
    replies = [json.loads(line) for line in result.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["protocolVersion"] == "2024-11-05"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {"reserve"}
    assert replies[2]["result"]["isError"] is True
    assert "forbidden" in replies[2]["result"]["content"][0]["text"]
