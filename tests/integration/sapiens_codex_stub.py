#!/usr/local/bin/python
"""Inert external process; real Sapiens owns all decisions and CLI observation."""

import json
import os
import selectors
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

if "--version" in sys.argv:
    print("codex-cli 0.118.0")
    sys.exit(0)

prompt = sys.stdin.read()
assert "exec" in sys.argv
assert Path.cwd().parent == Path("/tmp/sapiens-data/workspaces")
assert os.environ["HOME"] == "/home/composer"
assert not Path("/opt/sapiens/blindly4").exists()
assert not Path("/root/.codex/auth.json").exists()
assert not Path("/work/tests").exists() and not Path("/work/solution").exists()
assert not Path("/var/run/docker.sock").exists()
assert "WB_CONTROL_KEY" not in os.environ
home = Path(os.environ["CODEX_HOME"])
assert (
    json.loads((home / "auth.json").read_text())["OPENAI_API_KEY"]
    == "wb-synthetic-no-provider-access"
)
assert os.environ["SAPIENS_CODEX_MODEL"] == "synthetic"
print(
    json.dumps({"type": "thread.started", "thread_id": "synthetic-control"}), flush=True
)
base = {"reason": "Synthetic transport control", "evidence": ["Control fixture"]}
if "decision at node Assessing." in prompt:
    response = {**base, "event": "FitsSpecialization", "mode": "Exec"}
elif "decision at node ReadyToWork." in prompt:
    response = {
        **base,
        "event": "TaskPrepared",
        "taskType": "work",
        "specification": {
            "objective": "Synthetic transport control",
            "inputs": ["/work/task.json"],
            "expectedOutputs": ["/work/workflow.json"],
            "completionCriteria": ["Control file submitted"],
        },
    }
else:
    assert "decision at node Execution." in prompt
    # Native Codex initializes the real configured MCP server without turn/start.
    native = subprocess.Popen(
        ["codex-real", "app-server", "--listen", "stdio://"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    with selectors.DefaultSelector() as selector:
        selector.register(native.stdout, selectors.EVENT_READ)
        buffer = b""

        def request(identifier, method, params):
            global buffer
            native.stdin.write(
                (
                    json.dumps({"id": identifier, "method": method, "params": params})
                    + "\n"
                ).encode()
            )
            native.stdin.flush()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    response = json.loads(line)
                    if response.get("id") == identifier:
                        assert "error" not in response, response
                        return response["result"]
                if selector.select(0.2):
                    chunk = os.read(native.stdout.fileno(), 65536)
                    assert chunk
                    buffer += chunk
            raise TimeoutError("native MCP discovery timeout")

        try:
            request(
                1, "initialize", {"clientInfo": {"name": "wb08_probe", "version": "1"}}
            )
            native.stdin.write(b'{"method":"initialized"}\n')
            native.stdin.flush()
            status = request(2, "mcpServerStatus/list", {})
            Path("/logs/agent/sapiens-native-mcp.json").write_text(json.dumps(status))
            contract = json.loads(Path("/work/tools.json").read_text())
            discovered = {
                tool["name"]
                for server in status["data"]
                for tool in server["tools"].values()
            }
            assert discovered == {tool["name"] for tool in contract["tools"]}, (
                discovered
            )
        finally:
            native.terminate()
            native.wait(timeout=5)
            native.stdin.close()
            native.stdout.close()

    config = tomllib.loads((home / "config.toml").read_text())
    server = config["mcp_servers"]["tools"]
    process = subprocess.Popen(
        [server["command"], *server["args"]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
    )

    def call(identifier, method, params=None):
        process.stdin.write(
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
        process.stdin.flush()
        return json.loads(process.stdout.readline())["result"]

    assert (
        call(1, "initialize", {"protocolVersion": "2024-11-05"})["serverInfo"]["name"]
        == "workflow-bench-tools"
    )
    contract = json.loads(Path("/work/tools.json").read_text())
    example = json.loads(Path("/work/task.json").read_text())["example"]["input"]
    tools = call(2, "tools/list")["tools"]
    assert {tool["name"] for tool in tools} == {
        tool["name"] for tool in contract["tools"]
    }
    for identifier, tool in enumerate(contract["tools"], 3):
        arguments = {
            key: example[key]
            for key in tool["arguments_schema"]["properties"]
            if key in example
        }
        assert not call(
            identifier, "tools/call", {"name": tool["name"], "arguments": arguments}
        )["isError"]
    process.stdin.close()
    process.wait(timeout=3)
    Path("/logs/agent/sapiens-tools.json").write_text(
        json.dumps([tool["name"] for tool in tools])
    )
    mode = Path("/synthetic-mode").read_text().strip()
    if mode in {"timeout", "cancel", "native-cancel", "disconnect"}:
        sessions = home / "sessions"
        sessions.mkdir(exist_ok=True)
        (sessions / "control.jsonl").write_text(
            json.dumps({"type": "wb_control", "payload": {"phase": "execution"}}) + "\n"
        )
        child = "import time; from pathlib import Path; time.sleep(12); Path('/work/workflow.json').write_text('late writer'); time.sleep(120)"
        child_process = subprocess.Popen(
            [sys.executable, "-c", child], start_new_session=True
        )
        Path("/logs/agent/sapiens-child.json").write_text(
            json.dumps({"child": child_process.pid, "parent": os.getpid()})
        )
        time.sleep(120)
    shutil.copyfile("/synthetic-workflow.json", "/work/workflow.json")
    response = {
        **base,
        "event": "Outcome",
        "reply": "Synthetic control file submitted",
        "outcome": {
            "status": "Completed",
            "satisfiedCriteria": ["Control file submitted"],
            "artifacts": ["/work/workflow.json"],
        },
    }
print(
    json.dumps(
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(response)},
        }
    ),
    flush=True,
)
print(
    json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": 0}}
    ),
    flush=True,
)
