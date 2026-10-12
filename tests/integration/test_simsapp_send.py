"""Exact UI send effects checked through real Harbor and FrozenEvidence."""

import asyncio
import json
import subprocess
from uuid import uuid4

import pytest
from tests.fast.test_simsapp import nodes, seed
from tests.integration.controls import node
from tests.integration.test_simsapp_navigation import export, identity, script, start

from workflow_bench.harbor import assert_stopped, replay_environment

TEXT = "  Привет 👩🏽‍💻\ne\u0301 {{literal}}  "


@pytest.mark.parametrize(
    "lost_response", [False, True], ids=["normal", "lost-response"]
)
def test_real_composer_send_exact_effect_and_readback(e1_config, lost_response):
    async def check():
        e1_config.output_root.mkdir()
        async with asyncio.timeout(e1_config.total_timeout_sec):
            async with replay_environment(e1_config, identity()) as context:
                state = seed()
                state["ui"].update(
                    screen="conversation", active_conversation_id="private-a"
                )
                state["ui"]["drafts"]["private-b"] = "Старый целевой draft"
                state["messages"].append(
                    {
                        "id": "old-equal",
                        "conversation_id": "private-b",
                        "direction": "outgoing",
                        "text": TEXT,
                    }
                )
                capability = await start(context, state)
                await context.check_isolation()
                prepared = await node(
                    context,
                    script(
                        context,
                        capability,
                        """
await act(await observe(),'Back');
await act(await observe(),'Search');
await act(await observe(),'Search','focus');
await act(await observe(),'Search','replace_text','Север');
await act(await observe(),'Лена');
const opened=await observe();
const oldDraft=nodes(opened.tree).find(n=>n.role==='AXTextArea').value;
const wrongFocus=await act(opened,'Message','replace_text','wrong','AXTextArea');
await act(opened,'Message','focus',undefined,'AXTextArea');
const stale=await act(opened,'Send');
await act(await observe(),'Message','replace_text',"""
                        + json.dumps(TEXT)
                        + """,'AXTextArea');
const ready=await observe();
const bypass=await call('send_message',{chat_id:'private-b',text:'bypass'});
const admin=await fetch(base+'/control/export',{signal:AbortSignal.timeout(callTimeout)});
console.log(JSON.stringify({ready,sendLocator:locator(ready,'Send'),oldDraft,errors:[wrongFocus,stale,bypass].map(r=>r.error.code),admin:admin.status}));
""",
                    ),
                )
                assert prepared["oldDraft"] == "Старый целевой draft"
                assert prepared["errors"] == [
                    "not_focused",
                    "stale_locator",
                    "forbidden",
                ]
                assert prepared["admin"] == 404
                ready = prepared["ready"]
                send_locator = prepared["sendLocator"]
                assert "private-" not in json.dumps(ready)
                assert [
                    n["value"]
                    for n in nodes(ready["tree"])
                    if n["role"] == "AXStaticText" and n["label"] == "Message"
                ] == ["  История\n", TEXT]
                if lost_response:
                    await context.control(
                        "fault",
                        {
                            "identity": context.identity,
                            "mode": "drop_response",
                            "delay_sec": 0,
                        },
                    )
                result = await node(
                    context,
                    script(
                        context,
                        capability,
                        """
const sendLocator="""
                        + json.dumps(send_locator)
                        + """;
let unknown=false, acknowledgement=null;
try { acknowledgement=await call('ui_action',{action:'activate',locator:sendLocator}); }
catch { unknown=true; }
const current=await observe();
const repeated=await call('ui_action',{action:'activate',locator:sendLocator});
const disabled=await act(current,'Send');
console.log(JSON.stringify({unknown,acknowledgement,current,errors:[repeated,disabled].map(r=>r.error.code)}));
""",
                    ),
                )
                assert result["unknown"] == lost_response
                assert result["errors"] == ["stale_locator", "disabled"]
                current = result["current"]
                assert current["revision"] == ready["revision"] + 1

                assert [
                    n["value"]
                    for n in nodes(current["tree"])
                    if n["role"] == "AXStaticText" and n["label"] == "Message"
                ] == ["  История\n", TEXT, TEXT]
                composer = next(
                    n for n in nodes(current["tree"]) if n["role"] == "AXTextArea"
                )
                assert composer["value"] == "" and composer["focused"]
                await context.control("revoke", {"identity": context.identity})
                await context.control(
                    "freeze",
                    {
                        "identity": context.identity,
                        "drain_sec": e1_config.drain_timeout_sec,
                    },
                )
                frozen = await export(context)
                late = await node(
                    context,
                    script(
                        context,
                        capability,
                        "console.log(JSON.stringify(await call('ui_action',{action:'activate',locator:"
                        + json.dumps(send_locator)
                        + "})));",
                    ),
                )
                assert late["error"]["code"] == "forbidden"
                assert await context.control("export") == frozen
                assert await context.finish()
                facts = await export(context)
                assert (
                    facts["freeze_status"] == "complete"
                    and not facts["pending_call_ids"]
                )
                after = facts["after"]["state"]
                assert after["messages"][:-1] == state["messages"]
                message = after["messages"][-1]
                assert message["id"] not in {m["id"] for m in state["messages"]}
                assert {k: v for k, v in message.items() if k != "id"} == {
                    "conversation_id": "private-b",
                    "direction": "outgoing",
                    "text": TEXT,
                }
                assert after["conversations"] == state["conversations"]
                assert after["ui"]["drafts"] == {
                    "private-a": "Чужой draft",
                    "private-b": "",
                }
                effects = [
                    e
                    for e in facts["events"]
                    if e["stage"] == "effect" and e["details"]["message_id"] is not None
                ]
                assert (
                    len(effects) == 1
                    and effects[0]["details"]["message_id"] == message["id"]
                )
                response = next(
                    e
                    for e in facts["events"]
                    if e["stage"] == "response"
                    and e["call_id"] == effects[0]["call_id"]
                )
                assert response["details"]["status"] == (
                    "failed" if lost_response else "sent"
                )
                assert "ui_only_bypass" in facts["violations"]
                assert not context.stop_errors and not context.lifecycle.cleanup_errors
            await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


def test_real_mcp_inventory_and_business_bypass_denied(e1_config):
    name = "wb18-mcp-" + uuid4().hex
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "send_message",
                "arguments": {"chat_id": "private-b", "text": "bypass"},
            },
        },
    ]
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "-i",
                "--env",
                "WB_TOOL_URL=http://127.0.0.1:9",
                "--env",
                "WB_CAPABILITY=synthetic",
                e1_config.app_image,
                "env",
                "-u",
                "PYTHONPATH",
                "python",
                "-m",
                "workflow_bench.mcp",
                "--contract",
                "/app/simapp/tools.json",
                "--timeout",
                "1",
            ],
            input="".join(json.dumps(r) + "\n" for r in requests),
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        initialized, listed, denied = [
            json.loads(line)["result"] for line in result.stdout.splitlines()
        ]
        assert initialized["serverInfo"]["name"] == "workflow-bench-tools"
        assert {t["name"] for t in listed["tools"]} == {"ui_observe", "ui_action"}
        assert denied["isError"]
        assert json.loads(denied["content"][0]["text"]) == {"error": "forbidden"}
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
