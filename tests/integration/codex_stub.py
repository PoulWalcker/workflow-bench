#!/usr/local/bin/python
"""Inert external CLI probe; this file is included only in a control image."""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

if "--version" in sys.argv:
    print("codex-cli 0.118.0")
    sys.exit(0)

assert "resume" not in sys.argv and "exec" in sys.argv
assert Path.cwd() == Path("/work")
assert os.environ["OPENAI_API_KEY"] == "wb-synthetic-no-provider-access"
assert (
    json.loads((Path(os.environ["CODEX_HOME"]) / "auth.json").read_bytes())[
        "OPENAI_API_KEY"
    ]
    == os.environ["OPENAI_API_KEY"]
)
config = tomllib.loads((Path(os.environ["CODEX_HOME"]) / "config.toml").read_text())
assert config["web_search"] == "disabled"
assert config["openai_base_url"] == "http://provider:8080/v1"
for path in (
    "/tests",
    "/solution",
    "/bench/input",
    "/var/run/docker.sock",
    "/root/.codex/auth.json",
    "/work/tests",
    "/work/solution",
    "/app/workflow_bench/experiment.py",
):
    assert not Path(path).exists(), path
assert "WB_CONTROL_KEY" not in os.environ
assert not (Path(os.environ["HOME"]) / ".agents").exists()
opener = build_opener(ProxyHandler({}))
assert opener.open("http://provider:8080/", timeout=3).status == 200
for host, port in (
    ("1.1.1.1", 443),
    ("host.docker.internal", int(Path("/synthetic-host-port").read_text())),
):
    try:
        connection = socket.create_connection((host, port), timeout=0.5)
    except OSError:
        pass
    else:
        connection.close()
        raise AssertionError("network escape: " + host)

assert len(config["mcp_servers"]) == 1
server = next(iter(config["mcp_servers"].values()))
mcp = subprocess.Popen(
    [server["command"], *server["args"]],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    text=True,
)


def call(identifier, method, params=None):
    mcp.stdin.write(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": identifier,
                "method": method,
                "params": params or {},
            }
        )
        + "\n"
    )
    mcp.stdin.flush()
    return json.loads(mcp.stdout.readline())["result"]


assert (
    call(1, "initialize", {"protocolVersion": "2024-11-05"})["serverInfo"]["name"]
    == "workflow-bench-tools"
)
contract = json.loads(Path("/work/tools.json").read_bytes())
example = json.loads(Path("/work/task.json").read_bytes())["example"]["input"]
assert {tool["name"] for tool in call(2, "tools/list")["tools"]} == {
    tool["name"] for tool in contract["tools"]
}
reads = [tool for tool in contract["tools"] if tool["effect"] == "read"]
write = next(tool for tool in contract["tools"] if tool["effect"] == "write")


def arguments(tool):
    return {
        name: example[name]
        for name in tool["arguments_schema"]["properties"]
        if name in example
    }


first = call(
    3, "tools/call", {"name": reads[0]["name"], "arguments": arguments(reads[0])}
)
assert not first["isError"]
sent = call(4, "tools/call", {"name": write["name"], "arguments": arguments(write)})
assert not sent["isError"]
connection = json.loads(Path("/work/tools-connection.json").read_bytes())
read = reads[-1]
http = Request(
    connection["tool_url"] + "/tools/" + read["name"],
    data=json.dumps({"schema_version": "1.0", "arguments": arguments(read)}).encode(),
    headers={
        "Authorization": "Bearer " + connection["capability"],
        "Content-Type": "application/json",
    },
)
assert "result" in json.load(opener.open(http, timeout=3))
invalid = call(5, "tools/call", {"name": reads[0]["name"], "arguments": {}})
assert invalid["isError"] and "invalid_arguments" in invalid["content"][0]["text"]
forbidden = call(6, "tools/call", {"name": "reset", "arguments": {}})
assert forbidden["isError"] and "forbidden" in forbidden["content"][0]["text"]
limited = call(
    7, "tools/call", {"name": reads[0]["name"], "arguments": arguments(reads[0])}
)
assert limited["isError"] and "limit_exceeded" in limited["content"][0]["text"]
assert json.load(opener.open(http, timeout=3))["error"]["code"] == "limit_exceeded"
http.add_header("Authorization", "Bearer unrelated-capability")
assert json.load(opener.open(http, timeout=3))["error"]["code"] == "forbidden"
mcp.stdin.close()
mcp.wait(timeout=3)
mode = Path("/synthetic-mode").read_text().strip()
if mode == "session-fifo":
    sessions = Path(os.environ["CODEX_HOME"]) / "sessions/2026/10/12"
    sessions.mkdir(parents=True)
    os.mkfifo(sessions / "rollout.jsonl")
    os.mkfifo("/logs/agent/trajectory.json")
if mode in {"timeout", "cancel"}:
    child = "import time; from pathlib import Path; time.sleep(10); Path('/work/workflow.json').write_text('late writer'); time.sleep(60)"
    subprocess.Popen([sys.executable, "-c", child], start_new_session=True)
    print(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "child-started"},
            }
        ),
        flush=True,
    )
    time.sleep(60)
else:
    shutil.copyfile("/synthetic-workflow.json", "/work/workflow.json")
    print(
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": 0}}
        ),
        flush=True,
    )
