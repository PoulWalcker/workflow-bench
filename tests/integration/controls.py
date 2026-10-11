import hashlib
import json
import shlex
from pathlib import Path
from uuid import uuid4

from workflow_bench.data import read_json
from workflow_bench.harbor import ReplayContext

ROOT = Path(__file__).resolve().parents[2]


def identity() -> dict[str, str]:
    tools = ROOT / "simapps/telegram/tools.json"
    return {
        "run_id": uuid4().hex,
        "attempt_id": uuid4().hex,
        "replay_id": uuid4().hex,
        "artifact_hash": "a" * 64,
        "case_id": "isolation",
        "profile": read_json(tools, "tools")["profile"],
        "profile_hash": hashlib.sha256(tools.read_bytes()).hexdigest(),
    }


async def reset(context: ReplayContext) -> None:
    await context.control(
        "reset",
        {
            "identity": context.identity,
            "state": {"chats": [{"id": "42", "display_name": "Anna"}], "messages": []},
            "profile": context.identity["profile"],
            "limits": {"call_timeout_sec": context.config.tool_timeout_sec},
        },
    )


async def node(
    context: ReplayContext, script: str, *, service: str = "n8n"
) -> dict | list:
    result = await context.environment.service_exec(
        "node -e " + shlex.quote(script),
        service=service,
        timeout_sec=10,
    )
    assert result.return_code == 0, result.stderr
    return json.loads(result.stdout)
