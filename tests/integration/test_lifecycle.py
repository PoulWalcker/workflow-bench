import asyncio
import json
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from tests.integration.controls import identity, node, reset

from workflow_bench.data import read_json
from workflow_bench.execution import accept_artifact, replay
from workflow_bench.harbor import (
    LifecycleFacts,
    assert_stopped,
    docker,
    replay_environment,
    run_native_trial,
)
from workflow_bench.n8n_contracts import REPLAY_PROJECT_PREFIX, SUBMISSION_TRIAL_PREFIX

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks/t1-send-message"


def test_primary_cancel_survives_failed_evidence_export(e1_config, tmp_path):
    from workflow_bench.experiment import run_manual

    task = tmp_path / "source-task"
    shutil.copytree(TASK, task)
    workflow = read_json(task / "solution/workflow.json", "control")
    workflow["nodes"][2]["parameters"]["jsCode"] = "while (true) {}"
    (task / "solution/workflow.json").write_text(json.dumps(workflow))

    async def check():
        pending = asyncio.create_task(run_manual(task, ("fresh-a",), config=e1_config))
        try:
            async with asyncio.timeout(120):
                while True:
                    imports = list(
                        e1_config.output_root.glob(
                            REPLAY_PROJECT_PREFIX + "*/harbor/agent/import.log"
                        )
                    )
                    if imports:
                        project = imports[0].parents[2].name
                        container = await docker(
                            "ps",
                            "--filter",
                            "label=com.docker.compose.project=" + project,
                            "--filter",
                            "label=com.docker.compose.service=main",
                            "--format",
                            "{{.ID}}",
                        )
                        if container:
                            # The current Replay owns this simulator; killing it is the fault source.
                            await docker("kill", container)
                            break
                    if pending.done():
                        await pending
                        pytest.fail("Replay did not reach the injected fault")
                    await asyncio.sleep(0.2)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            report = read_json(e1_config.output_root / "report.json", "report")
            assert report["error"] == "cancelled"
            assert report["cleanup_errors"] == report["residual_resources"] == []
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    asyncio.run(check())


def test_real_manual_cancellation_stops_submission_process(e1_config, tmp_path):
    from workflow_bench.experiment import run_manual

    async def check():
        task_path = tmp_path / "source-task"
        shutil.copytree(TASK, task_path)
        solve = task_path / "solution/solve.sh"
        solve.write_text(solve.read_text() + "\nsleep 600\n")
        cancel = asyncio.Event()
        running = asyncio.create_task(
            run_manual(task_path, ("fresh-a",), config=e1_config, cancel=cancel)
        )
        project = None
        try:
            async with asyncio.timeout(90):
                while True:
                    trials = list(
                        (e1_config.output_root / "harbor").glob(
                            SUBMISSION_TRIAL_PREFIX + "*"
                        )
                    )
                    if trials:
                        project = trials[0].name + "__env"
                        container = await docker(
                            "ps",
                            "--filter",
                            f"label=com.docker.compose.project={project}",
                            "--filter",
                            "label=com.docker.compose.service=main",
                            "--format",
                            "{{.ID}}",
                        )
                        if container:
                            processes = await docker(
                                "top", container, "-eo", "pid,args"
                            )
                            if "sleep 600" in processes:
                                (
                                    e1_config.output_root
                                    / "submission-before-cancel.txt"
                                ).write_text(processes)
                                break
                    if running.done():
                        await running
                        pytest.fail("submission exited before cancellation")
                    await asyncio.sleep(0.25)
            cancel.set()
            async with asyncio.timeout(2 * e1_config.cleanup_timeout_sec + 20):
                report = await running
            assert report["error"] == "cancelled"
            assert report["completeness"] == "unavailable" and report["score"] is None
            assert not report["cleanup_errors"] and not report["residual_resources"]
            await assert_stopped(project, deleted=True)
            await assert_stopped(trials[0].name + "__verifier__trial", deleted=True)
        finally:
            if not running.done():
                cancel.set()
                await asyncio.gather(running, return_exceptions=True)

    asyncio.run(check())


@pytest.mark.parametrize("cancelled", [False, True])
def test_real_replay_timeout_and_cancellation_stop_children(e1_config, cancelled):
    async def check():
        e1_config.output_root.mkdir()
        workflow = read_json(TASK / "solution/workflow.json", "control")
        workflow["nodes"][2]["parameters"]["jsCode"] = (
            "console.log('WB05_BUSY_JS'); while (true) {}"
        )
        source = e1_config.output_root / "busy.json"
        source.write_text(json.dumps(workflow))
        artifact = accept_artifact(
            source,
            submission_stopped=True,
            destination=e1_config.output_root / "accepted.json",
        )
        config = replace(e1_config, execute_timeout_sec=40)
        async with replay_environment(config, identity()) as context:
            await reset(context)
            task = asyncio.create_task(
                replay(
                    artifact,
                    {"chat_id": "42", "text": "never"},
                    context=context,
                    config=config,
                )
            )
            if cancelled:
                try:
                    async with asyncio.timeout(30):
                        container = await docker(
                            "ps",
                            "--filter",
                            f"label=com.docker.compose.project={context.project}",
                            "--filter",
                            "label=com.docker.compose.service=n8n",
                            "--format",
                            "{{.ID}}",
                        )
                        while True:
                            processes = await docker(
                                "top", container, "-eo", "pid,args"
                            )
                            if any(
                                "node" in line
                                and "n8n execute" in line
                                and "sh -c" not in line
                                for line in processes.splitlines()
                            ):
                                break
                            await asyncio.sleep(0.25)
                        (context.root / "processes-before-cancel.txt").write_text(
                            processes
                        )
                except BaseException:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                execution = read_json(context.root / "execution.json", "execution")
                assert execution["process_status"] == "cancelled"
            else:
                execution, _ = await task
                assert execution["process_status"] == "timed_out"
            assert execution["stop_confirmed"]
            await assert_stopped(context.project, services={"n8n", "runner"})
            facts = await context.control("export")
            assert facts["after"]["revision"] == 0
            (context.root / "timeout-evidence.json").write_text(json.dumps(facts))
        await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


def test_real_pending_drain_and_expired_capability(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        async with replay_environment(e1_config, identity()) as context:
            await reset(context)
            issued = await context.control(
                "issue",
                {
                    "identity": context.identity,
                    "actor": "workflow",
                    "ttl_sec": 0.01,
                    "max_calls": 8,
                },
            )
            await asyncio.sleep(0.02)
            script = """
(async () => {
 const r = await fetch(BASE+'/tools/send_message', {method:'POST',headers:{Authorization:CAP,'Content-Type':'application/json'},body:JSON.stringify({schema_version:'1.0',arguments:{chat_id:'42',text:'expired'}})});
 console.log(JSON.stringify(await r.json()));
})().catch(() => process.exit(1));
""".replace("BASE", json.dumps(f"http://simulator:{e1_config.tools_port}")).replace(
                "CAP", json.dumps("Bearer " + issued["capability"])
            )
            result = await node(context, script)
            assert result["error"]["code"] == "forbidden"
            await context.finish()
            assert (await context.control("export"))["after"]["revision"] == 0
        async with replay_environment(e1_config, identity()) as context:
            await reset(context)
            issued = await context.control(
                "issue",
                {
                    "identity": context.identity,
                    "actor": "workflow",
                    "ttl_sec": 60,
                    "max_calls": 8,
                },
            )
            await context.control(
                "fault",
                {
                    "identity": context.identity,
                    "mode": "stall_before_commit",
                    "delay_sec": 2,
                },
            )
            script = """
(async () => {
 const r = await fetch(BASE+'/tools/send_message', {method:'POST',headers:{Authorization:CAP,'Content-Type':'application/json'},body:JSON.stringify({schema_version:'1.0',arguments:{chat_id:'42',text:'pending'}})});
 console.log(JSON.stringify(await r.json()));
})().catch(() => process.exit(1));
""".replace("BASE", json.dumps(f"http://simulator:{e1_config.tools_port}")).replace(
                "CAP", json.dumps("Bearer " + issued["capability"])
            )
            pending = asyncio.create_task(node(context, script))
            await asyncio.sleep(0.5)
            await context.control(
                "freeze", {"identity": context.identity, "drain_sec": 0.05}
            )
            before = await context.control("export")
            assert (
                before["freeze_status"] == "incomplete" and before["pending_call_ids"]
            )
            await pending
            assert await context.control("export") == before
            assert before["after"]["revision"] == 0
            await context.finish()
            (context.root / "pending-evidence.json").write_text(json.dumps(before))

    asyncio.run(check())


@pytest.mark.parametrize("failure", ["error", "timeout"])
def test_real_verifier_failure_does_not_become_candidate_zero(e1_config, failure):
    async def check():
        e1_config.output_root.mkdir()
        stage = e1_config.output_root / "task"
        shutil.copytree(TASK, stage)
        (stage / "tests/test.sh").write_text(
            "#!/bin/sh\n" + ("exit 17\n" if failure == "error" else "sleep 60\n")
        )

        async def prepare(path):
            accept_artifact(
                path,
                submission_stopped=True,
                destination=e1_config.output_root / "accepted.json",
            )

        facts = LifecycleFacts()
        result = await run_native_trial(
            stage,
            uuid4().hex,
            prepare,
            config=replace(e1_config, verifier_timeout_sec=3),
            lifecycle=facts,
        )
        assert result.exception_type is not None
        assert result.evaluation["cases"] == []
        assert not facts.cleanup_errors and not facts.residual_resources

    asyncio.run(check())


def test_stop_refusal_is_unknown_until_final_cleanup(e1_config, monkeypatch):
    from harbor.environments.docker.docker import DockerEnvironment

    original = DockerEnvironment.stop_service

    async def refused(self, service):
        if service == "n8n":
            raise ConnectionError("synthetic stop transport failure")
        return await original(self, service)

    monkeypatch.setattr(DockerEnvironment, "stop_service", refused)

    async def check():
        e1_config.output_root.mkdir()
        async with replay_environment(e1_config, identity()) as context:
            await reset(context)
            assert await context.finish() is False
            stopped = read_json(context.root / "stop.json", "stop")
            assert stopped["stop_confirmed"] is False
            assert "n8n_stop_failed:ConnectionError" in stopped["errors"]
        await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


def test_failed_cleanup_reports_real_owned_resources(e1_config, monkeypatch):
    from harbor.environments.docker.docker import DockerEnvironment

    original = DockerEnvironment.stop

    async def unavailable(self, delete):
        raise ConnectionError("synthetic cleanup transport fault")

    async def check():
        e1_config.output_root.mkdir()
        facts = LifecycleFacts()
        context = None
        try:
            monkeypatch.setattr(DockerEnvironment, "stop", unavailable)
            async with replay_environment(
                e1_config, identity(), lifecycle=facts
            ) as context:
                await reset(context)
                assert await context.finish()
            assert any("stop_failed:ConnectionError" in e for e in facts.cleanup_errors)
            assert any(r.startswith("container:") for r in facts.residual_resources)
            assert any(r.startswith("network:") for r in facts.residual_resources)
            (e1_config.output_root / "cleanup-failure.json").write_text(
                json.dumps(
                    {
                        "cleanup_errors": facts.cleanup_errors,
                        "residual_resources": facts.residual_resources,
                    }
                )
            )
        finally:
            if context is not None:
                async with asyncio.timeout(e1_config.cleanup_timeout_sec):
                    await original(context.environment, delete=True)
                await assert_stopped(context.project, deleted=True)

    asyncio.run(check())


def test_failed_real_environment_start_retains_null_and_cleanup(e1_config):
    from workflow_bench.experiment import run_manual

    config = replace(e1_config, app_image="sha256:" + "0" * 64, setup_timeout_sec=5)
    with pytest.raises((RuntimeError, TimeoutError)):
        asyncio.run(run_manual(TASK, ("fresh-a",), config=config))
    report = read_json(config.output_root / "report.json", "report")
    assert report["score"] is None and report["completeness"] == "unavailable"
    assert report["evaluation"]["cases"] == []
    assert report["residual_resources"] == []


@pytest.mark.parametrize("blind_retry", [False, True])
def test_real_lost_response_observation_and_blind_retry_are_distinct(
    e1_config, blind_retry
):
    async def check():
        e1_config.output_root.mkdir()
        async with replay_environment(e1_config, identity()) as context:
            await reset(context)
            issued = await context.control(
                "issue",
                {
                    "identity": context.identity,
                    "actor": "workflow",
                    "ttl_sec": 60,
                    "max_calls": 8,
                },
            )
            await context.control(
                "fault",
                {"identity": context.identity, "mode": "drop_response", "delay_sec": 0},
            )
            script = (
                """
const base=BASE, authorization=CAP;
async function call(name, args) {
 return await (await fetch(base+'/tools/'+name, {method:'POST',headers:{Authorization:authorization,'Content-Type':'application/json'},body:JSON.stringify({schema_version:'1.0',arguments:args})})).json();
}
(async () => {
 let unknown=false;
 try {await call('send_message',{chat_id:'42',text:'exact'});} catch {unknown=true;}
 if (RETRY) await call('send_message',{chat_id:'42',text:'exact'});
 const observed=await call('list_messages',{chat_id:'42'});
 console.log(JSON.stringify({unknown,observed}));
})().catch(() => process.exit(1));
""".replace("BASE", json.dumps(f"http://simulator:{e1_config.tools_port}"))
                .replace("CAP", json.dumps("Bearer " + issued["capability"]))
                .replace("RETRY", json.dumps(blind_retry))
            )
            result = await node(context, script)
            assert result["unknown"]
            assert len(result["observed"]["result"]) == (2 if blind_retry else 1)
            assert await context.finish()
            evidence = await context.control("export")
            assert evidence["after"]["revision"] == (2 if blind_retry else 1)
            (context.root / "lost-response-evidence.json").write_text(
                json.dumps(evidence)
            )

    asyncio.run(check())
