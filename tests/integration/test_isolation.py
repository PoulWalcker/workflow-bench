import asyncio
import json

from aiohttp import web
from tests.integration.controls import identity, node, reset

from workflow_bench.harbor import assert_stopped, docker, replay_environment


def test_real_network_files_and_cross_run_capabilities(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        host = web.Application()

        async def private_marker(request):
            return web.Response(text="synthetic-private-marker")

        host.router.add_get("/{path:.*}", private_marker)
        listener = web.AppRunner(host, access_log=None)
        await listener.setup()
        await web.TCPSite(listener, "0.0.0.0", 0).start()
        host_port = listener.addresses[0][1]
        try:
            async with replay_environment(e1_config, identity()) as victim:
                await reset(victim)
                async with replay_environment(e1_config, identity()) as context:
                    await reset(context)
                    await context.check_isolation()
                    main = await docker(
                        "ps",
                        "--filter",
                        f"label=com.docker.compose.project={victim.project}",
                        "--filter",
                        "label=com.docker.compose.service=main",
                        "--format",
                        "{{.ID}}",
                    )
                    victim_networks = json.loads(
                        await docker(
                            "inspect",
                            main,
                            "--format",
                            "{{json .NetworkSettings.Networks}}",
                        )
                    )
                    other_ip = victim_networks[victim.project + "_tools"]["IPAddress"]
                    targets = [
                        f"http://host.docker.internal:{host_port}/private",
                        f"http://{other_ip}:{e1_config.tools_port}/tools/get_chat",
                        f"http://{other_ip}:{e1_config.control_port}/control/export",
                        "http://192.0.2.1:80/controlled-unrouted",
                    ]
                    script = f"""const fs = require('fs');
(async () => {{
  const reached = await Promise.all({json.dumps(targets)}.map(url => fetch(url, {{signal: AbortSignal.timeout(1000)}}).then(() => true, () => false)));
  const paths = ['/tests/private-marker.txt', '/solution/workflow.json', '/bench/input', '/var/run/docker.sock', '/app/workflow_bench/experiment.py'];
  const privateFiles = paths.map(path => {{try {{fs.readFileSync(path); return true;}} catch {{return false;}}}});
  let write = false; try {{fs.writeFileSync('/bench/input/evidence.json', 'forged'); write = true;}} catch {{}}
  console.log(JSON.stringify({{reached, privateFiles, write, controlSecret: !!process.env.WB_CONTROL_KEY}}));
}})().catch(() => process.exit(1));
"""
                    for service in ("n8n", "runner"):
                        result = await node(context, script, service=service)
                        assert not any(result["reached"])
                        assert (
                            not any(result["privateFiles"])
                            and not result["write"]
                            and not result["controlSecret"]
                        )
                    issued = await context.control(
                        "issue",
                        {
                            "identity": context.identity,
                            "actor": "workflow",
                            "ttl_sec": 60,
                            "max_calls": 3,
                        },
                    )
                    capability = issued["capability"]
                    base = f"http://simulator:{e1_config.tools_port}"
                    requests = [
                        (
                            "send_message",
                            {"chat_id": "42", "text": "forbidden", "actor": "admin"},
                        ),
                        (
                            "send_message",
                            {
                                "chat_id": "42",
                                "text": "forbidden",
                                "run_id": victim.identity["run_id"],
                            },
                        ),
                        ("get_chat", {"chat_id": "42"}),
                        ("send_message", {"chat_id": "42", "text": "after-limit"}),
                    ]
                    request_script = """
(async () => {{
 const results=[];
 for (const [name, args] of {}) {{
   results.push(await (await fetch({}+'/tools/'+name, {{method:'POST', headers:{{Authorization:{},'Content-Type':'application/json'}}, body:JSON.stringify({{schema_version:'1.0',arguments:args}})}})).json());
 }}
 console.log(JSON.stringify(results));
}})().catch(() => process.exit(1));
""".format(json.dumps(requests), json.dumps(base), json.dumps("Bearer " + capability))
                    results = await node(context, request_script)
                    assert [r.get("error", {}).get("code") for r in results] == [
                        "invalid_arguments",
                        "invalid_arguments",
                        None,
                        "limit_exceeded",
                    ]
                    await context.control("revoke", {"identity": context.identity})
                    results = await node(context, request_script)
                    assert all(r["error"]["code"] == "forbidden" for r in results)
                    await context.finish()
                    facts = await context.control("export")
                    assert facts["before"]["state"] == facts["after"]["state"]
                    (e1_config.output_root / "isolation.json").write_text(
                        json.dumps({"targets": targets, "facts": facts})
                    )
                await assert_stopped(context.project, deleted=True)
                await victim.finish()
                facts = await victim.control("export")
                assert facts["events"] == []
            await assert_stopped(victim.project, deleted=True)
        finally:
            await listener.cleanup()

    asyncio.run(check())
