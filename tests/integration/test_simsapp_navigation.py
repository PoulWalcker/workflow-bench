"""Model-free SimsApp controls through real Harbor isolation and UI transport."""

import asyncio
import hashlib
import json
import math
import shlex
from pathlib import Path
from uuid import uuid4

import pytest
from tests.fast.test_simsapp import seed
from tests.integration.controls import node

from workflow_bench.evaluation import read_evidence
from workflow_bench.harbor import assert_stopped, replay_environment

ROOT = Path(__file__).resolve().parents[2]


def identity():
    profile = ROOT / "simapps/simsapp/tools.json"
    return {
        "protocol": "ui_control",
        "run_id": uuid4().hex,
        "control_id": uuid4().hex,
        "case_id": "navigation",
        "profile": "simsapp-ui-v1",
        "profile_hash": hashlib.sha256(profile.read_bytes()).hexdigest(),
    }


async def start(context, state=None):
    await context.control(
        "reset",
        {
            "identity": context.identity,
            "state": seed() if state is None else state,
            "profile": context.identity["profile"],
            "limits": {"call_timeout_sec": context.config.tool_timeout_sec},
        },
    )
    issued = await context.control(
        "issue",
        {
            "identity": context.identity,
            "actor": "control",
            "ttl_sec": context.config.total_timeout_sec,
            "max_calls": context.config.max_calls,
        },
    )
    return issued["capability"]


def script(context, capability, body):
    return (
        "const base="
        + json.dumps(f"http://simulator:{context.config.tools_port}")
        + "; const authorization="
        + json.dumps("Bearer " + capability)
        + "; const callTimeout="
        + json.dumps(math.ceil(context.config.tool_timeout_sec * 1000))
        + ";"
        + """
async function call(name, args={}) {
  return await (await fetch(base+'/tools/'+name, {method:'POST',headers:{Authorization:authorization,'Content-Type':'application/json'},body:JSON.stringify({schema_version:'1.0',arguments:args}),signal:AbortSignal.timeout(callTimeout)})).json();
}
function nodes(n) { return [{label:'',actions:[],...n,...(n.simulation||{})}, ...(n.children||[]).flatMap(nodes)]; }
async function observe() { return (await call('ui_observe')).result; }
function locator(o, label, hint, role) {
 const n=nodes(o.tree).find(n=>n.label===label && (hint===undefined || n.identity?.identity_hint===hint) && (role===undefined || n.role===role));
 return {scope:o.scope,revision:o.revision,ref:n.ref};
}
async function act(o,label,action='activate',text,role) {
 return call('ui_action',{action,locator:locator(o,label,undefined,role),...(text===undefined?{}:{text})});
}
(async()=>{"""
        + body
        + """})().catch(()=>process.exit(1));"""
    )


async def export(context):
    facts = await context.control("export")
    path = context.root / "evidence.json"
    path.write_text(json.dumps(facts))
    return read_evidence(path, expected_identity=context.identity).document


def test_real_navigation_negative_access_and_protected_freeze(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        async with asyncio.timeout(e1_config.total_timeout_sec):
            async with replay_environment(e1_config, identity()) as context:
                capability = await start(context)
                await context.check_isolation()
                observed = await node(
                    context,
                    script(
                        context,
                        capability,
                        """
const initial=await observe();
await act(initial,'Search');
const unfocused=await observe();
const wrongFocus=await act(unfocused,'Search','replace_text','Юг');
const disabled=await act(unfocused,'Clear text');
await act(unfocused,'Search','focus');
const stale=await act(unfocused,'Search','replace_text','Юг');
const cardinalities=[];
for (const query of ['никто','Юг','Лена','Север']) {
 await act(await observe(),'Search','replace_text',query);
 const results=await observe();
 cardinalities.push(nodes(results.tree).filter(n=>n.identity).length);
}
const results=await observe();
const selected=nodes(results.tree).find(n=>n.identity?.identity_hint==='Север');
await call('ui_action',{action:'activate',locator:{scope:results.scope,revision:results.revision,ref:selected.ref}});
const conversation=await observe();
const bypass=await call('send_message',{chat_id:'private-b',text:'bypass'});
await act(conversation,'Back');
const current=await observe();
const admin=await fetch(base+'/control/export',{signal:AbortSignal.timeout(1000)});
console.log(JSON.stringify({initial,current,conversation,cardinalities,errors:[wrongFocus,disabled,stale,bypass].map(r=>r.error.code),admin:admin.status}));
""",
                    ),
                )
                assert observed["cardinalities"] == [0, 1, 2, 1]
                assert observed["errors"] == [
                    "not_focused",
                    "disabled",
                    "stale_locator",
                    "forbidden",
                ]
                assert observed["admin"] == 404
                assert observed["current"]["screen"] == "chat_list"
                assert "private-" not in json.dumps(observed["conversation"])
                await context.control("revoke", {"identity": context.identity})
                await context.control(
                    "freeze",
                    {
                        "identity": context.identity,
                        "drain_sec": e1_config.drain_timeout_sec,
                    },
                )
                before = await export(context)
                late = await node(
                    context,
                    script(
                        context,
                        capability,
                        "console.log(JSON.stringify(await call('ui_action',{action:'activate',locator:locator("
                        + json.dumps(observed["current"])
                        + ",'Search')})));",
                    ),
                )
                assert late["error"]["code"] == "forbidden"
                assert await context.control("export") == before
                assert await context.finish()
                facts = await export(context)
                assert facts["freeze_status"] == "complete"
                assert facts["before"]["state"] == facts["after"]["state"]
                assert "ui_only_bypass" in facts["violations"]
                transitions = [
                    e["details"]["transition"]
                    for e in facts["events"]
                    if "transition" in e["details"]
                ]
                assert any(
                    c["path"] == "/ui/active_conversation_id"
                    and c["after"] == "private-b"
                    for t in transitions
                    for c in t["changes"]
                )
                observations = [
                    e["details"]["observation"]
                    for e in facts["events"]
                    if "observation" in e["details"]
                ]
                assert any(
                    o["visible_message_ids"] == ["private-m"]
                    and o["visible_conversation_ids"] == ["private-b"]
                    for o in observations
                )
                assert not context.lifecycle.cleanup_errors
            await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


def test_real_lost_response_keeps_navigation_commit_and_readback(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        async with asyncio.timeout(e1_config.total_timeout_sec):
            async with replay_environment(e1_config, identity()) as context:
                capability = await start(context)
                initial = await node(
                    context,
                    script(
                        context,
                        capability,
                        "console.log(JSON.stringify(await observe()));",
                    ),
                )
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
                        "let unknown=false; try { await act("
                        + json.dumps(initial)
                        + ",'Search'); } catch { unknown=true; } console.log(JSON.stringify({unknown, current:await observe()}));",
                    ),
                )
                assert result["unknown"] and result["current"]["screen"] == "search"
                assert result["current"]["revision"] == 1
                assert await context.finish()
                facts = await export(context)
                assert facts["after"]["state"]["ui"]["screen"] == "search"
                failed = [
                    e
                    for e in facts["events"]
                    if e["stage"] == "response" and e["details"]["status"] == "failed"
                ]
                assert len(failed) == 1
                assert any(
                    e["call_id"] == failed[0]["call_id"]
                    and e["details"]["status"] == "committed"
                    for e in facts["events"]
                )
            await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("control", ["Search", "Send"])
def test_real_timeout_cancel_stop_children_and_seal_pending_navigation(
    e1_config, cancelled, control
):
    async def check():
        e1_config.output_root.mkdir()
        async with asyncio.timeout(e1_config.total_timeout_sec):
            async with replay_environment(e1_config, identity()) as context:
                state = seed()
                if control == "Send":
                    state["ui"].update(
                        screen="conversation", active_conversation_id="private-b"
                    )
                    state["ui"]["drafts"]["private-b"] = "pending send"
                capability = await start(context, state)
                initial = await node(
                    context,
                    script(
                        context,
                        capability,
                        "console.log(JSON.stringify(await observe()));",
                    ),
                )
                await context.control(
                    "fault",
                    {
                        "identity": context.identity,
                        "mode": "stall_before_commit",
                        "delay_sec": e1_config.drain_timeout_sec
                        + e1_config.control_timeout_sec,
                    },
                )
                busy = script(
                    context,
                    capability,
                    "require('child_process').spawn('sleep',['600']); await act("
                    + json.dumps(initial)
                    + ","
                    + json.dumps(control)
                    + "); await new Promise(()=>{});",
                )

                async def stop_writer():
                    assert await context.finish()

                context.environment.cancel_writer = stop_writer

                async def run():
                    await context.environment.service_exec(
                        "node -e " + shlex.quote(busy),
                        service="n8n",
                        timeout_sec=math.ceil(e1_config.execute_timeout_sec),
                    )

                running = asyncio.create_task(run())
                try:
                    # Confirm the actual child exists before the timeout/cancel source.
                    async with asyncio.timeout(e1_config.setup_timeout_sec):
                        while True:
                            checked = await context.environment.service_exec(
                                "pgrep -f '^sleep 600$'",
                                service="n8n",
                                timeout_sec=math.ceil(e1_config.control_timeout_sec),
                            )
                            if checked.return_code == 0:
                                break
                            if running.done():
                                await running
                                pytest.fail("control_exited_before_fault")
                            await asyncio.sleep(0.1)
                    if cancelled:
                        running.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await running
                    else:
                        with pytest.raises(TimeoutError):
                            async with asyncio.timeout(0.1):
                                await running
                    await assert_stopped(context.project, services={"n8n", "runner"})
                    stopped = json.loads((context.root / "stop.json").read_text())
                    assert stopped["stop_confirmed"] and not stopped["errors"]
                    facts = await export(context)
                    assert (
                        facts["freeze_status"] == "incomplete"
                        and facts["pending_call_ids"]
                    )
                    assert facts["before"] == facts["after"]
                    # Wait past the accepted fault's commit opportunity, under the total deadline.
                    await asyncio.sleep(e1_config.drain_timeout_sec)
                    assert await context.control("export") == facts
                finally:
                    if not running.done():
                        running.cancel()
                        await asyncio.gather(running, return_exceptions=True)
            await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


def test_real_fresh_world_rejects_previous_capability_and_scope(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        async with asyncio.timeout(e1_config.total_timeout_sec):
            async with replay_environment(e1_config, identity()) as previous:
                old_capability = await start(previous)
                old_observation = await node(
                    previous,
                    script(
                        previous,
                        old_capability,
                        "const old=await observe(); await act(old,'Search'); await act(await observe(),'Search','focus'); await act(await observe(),'Search','replace_text','Север'); console.log(JSON.stringify(await observe()));",
                    ),
                )
                assert await previous.finish()
                old_facts = await export(previous)
                assert old_facts["after"]["state"]["ui"]["query"] == "Север"
            await assert_stopped(previous.project, deleted=True)
            async with replay_environment(e1_config, identity()) as current:
                capability = await start(current)
                denied = await node(
                    current,
                    script(
                        current,
                        old_capability,
                        "console.log(JSON.stringify(await call('ui_observe')));",
                    ),
                )
                assert denied["error"]["code"] == "forbidden"
                observed = await node(
                    current,
                    script(
                        current,
                        capability,
                        "const current=await observe(); const stale=await act("
                        + json.dumps(old_observation)
                        + ",'Search','focus'); console.log(JSON.stringify({current,stale}));",
                    ),
                )
                assert observed["stale"]["error"]["code"] == "stale_locator"
                assert observed["current"]["revision"] == 0
                assert observed["current"]["screen"] == "chat_list"
                assert observed["current"]["scope"] != old_observation["scope"]
                assert await current.finish()
                facts = await export(current)
                assert (
                    facts["before"]
                    == facts["after"]
                    == {"revision": 0, "state": seed()}
                )
                assert all(
                    e["details"]["status"] != "committed" for e in facts["events"]
                )
            await assert_stopped(current.project, deleted=True)

    asyncio.run(check())
