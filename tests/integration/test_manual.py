import asyncio
import json
from pathlib import Path

import pytest

from workflow_bench.cli import load_config
from workflow_bench.data import read_json
from workflow_bench.experiment import run_manual

TASK = Path(__file__).resolve().parents[2] / "tasks/t1-send-message"


@pytest.fixture
def e1_config(request: pytest.FixtureRequest, tmp_path: Path):
    if not request.config.getoption("--run-integration"):
        pytest.fail("integration resources require --run-integration")
    path = request.config.getoption("--e1-config")
    if not path:
        pytest.fail("prepare images and pass --e1-config; no integration skip")
    return load_config(Path(path).resolve(), output=tmp_path / "run")


def test_manual_t1_reaches_independent_verifier(e1_config) -> None:
    case_ids = ("fresh-a", "fresh-b", "missing")
    result = asyncio.run(run_manual(TASK, case_ids, config=e1_config))
    assert result["harbor_exception"] == "RewardFileNotFoundError"
    assert len(result["evaluation"]["cases"]) == len(case_ids)
    for case, replay in zip(
        result["evaluation"]["cases"], result["replays"], strict=True
    ):
        assert case["completeness"] == "complete"
        assert case["score"] is None and case["verdict"] == "unknown"
        assert all(c["status"] in {"pass", "not_applicable"} for c in case["criteria"])
        assert replay["execution"]["process_status"] == "completed"
        assert replay["identity"]["artifact_hash"] == result["artifact_hash"]
        assert replay["database_fresh"] and replay["isolation_confirmed"]
        facts = read_json(e1_config.output_root / replay["evidence_ref"], "facts")
        assert facts["before"]["revision"] == 0
        log = (e1_config.output_root / replay["log_ref"] / "execute.log").read_text()
        assert "Registered runner" in log and "JS Task Runner" in log
        workflow = read_json(TASK / "solution/workflow.json", "control")
        code_node = next(
            n["name"] for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.code"
        )
        assert json.dumps(code_node) in log
    assert len({r["identity"]["replay_id"] for r in result["replays"]}) == 3
    assert len({r["bound_hash"] for r in result["replays"]}) == 3
    assert result["cleanup_errors"] == result["residual_resources"] == []


@pytest.mark.parametrize("count", [100, 101])
def test_real_t1_reads_are_complete_or_explicitly_limited(
    e1_config, count: int
) -> None:
    async def check() -> None:
        import hashlib
        import shlex
        from uuid import uuid4

        from workflow_bench.harbor import replay_environment

        e1_config.output_root.mkdir(mode=0o700)
        tools = TASK.parents[1] / "simapps/telegram/tools.json"
        identity = {
            "run_id": uuid4().hex,
            "attempt_id": uuid4().hex,
            "replay_id": uuid4().hex,
            "artifact_hash": hashlib.sha256(b"read-control").hexdigest(),
            "case_id": "read-boundary",
            "profile": read_json(tools, "tools")["profile"],
            "profile_hash": hashlib.sha256(tools.read_bytes()).hexdigest(),
        }
        state = {
            "chats": [{"id": "exact", "display_name": "Anna"}],
            "messages": [
                {
                    "id": f"m-{i}",
                    "chat_id": "exact",
                    "direction": "incoming",
                    "text": f"text-{i}",
                }
                for i in range(count)
            ],
        }
        async with replay_environment(e1_config, identity) as context:
            await context.control(
                "reset",
                {
                    "identity": identity,
                    "state": state,
                    "profile": identity["profile"],
                    "limits": {"call_timeout_sec": e1_config.tool_timeout_sec},
                },
            )
            issued = await context.control(
                "issue",
                {
                    "identity": identity,
                    "actor": "workflow",
                    "ttl_sec": e1_config.execute_timeout_sec,
                    "max_calls": e1_config.max_calls,
                },
            )
            calls = [
                ["get_chat", {"chat_id": "exact"}],
                ["list_messages", {"chat_id": "exact"}],
                ["send_message", {"chat_id": "Anna", "text": "must not write"}],
            ]
            script = f"""
const calls = {json.dumps(calls)};
const baseUrl = {json.dumps(f"http://simulator:{e1_config.tools_port}/tools/")};
const authorization = {json.dumps("Bearer " + issued["capability"])};
(async () => {{
    const responses = [];
    for (const [name, args] of calls) {{
        const r = await fetch(baseUrl + name, {{
            method: "POST",
            headers: {{Authorization: authorization, "Content-Type": "application/json"}},
            body: JSON.stringify({{schema_version: "1.0", arguments: args}}),
            signal: AbortSignal.timeout({int(e1_config.tool_timeout_sec * 1000)})
        }});
        responses.push(await r.json());
    }}
    console.log(JSON.stringify(responses));
    process.exit(0);
}})().catch(() => process.exit(1));
"""
            response = await context.environment.service_exec(
                "node -e " + shlex.quote(script),
                service="n8n",
                timeout_sec=int(e1_config.execute_timeout_sec),
            )
            assert response.return_code == 0
            results = json.loads(response.stdout)
            assert results[0]["result"] == state["chats"][0]
            if count == 100:
                assert results[1]["result"] == state["messages"]
            else:
                assert results[1]["error"]["code"] == "limit_exceeded"
                assert "result" not in results[1]
            assert results[2]["error"]["code"] == "not_found"
            await context.finish()
            facts = await context.control("export")
            assert facts["before"]["state"] == facts["after"]["state"] == state
            assert facts["after"]["revision"] == 0
            assert all(
                e["details"]["status"] == "no_effect"
                for e in facts["events"]
                if e["stage"] == "effect"
            )

    asyncio.run(check())
