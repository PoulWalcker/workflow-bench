import asyncio
import json
import shutil
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from workflow_bench.data import read_json
from workflow_bench.definition import load_cases, load_task
from workflow_bench.execution import accept_artifact, replay
from workflow_bench.harbor import replay_environment, run_native_trial

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks/t1-send-message"


async def native_control(config, workflow, *, fault=None):
    import hashlib

    config.output_root.mkdir()
    stage = config.output_root / "task"
    shutil.copytree(TASK, stage)
    (stage / "tests/private-marker.txt").write_text("WB05_SYNTHETIC_PRIVATE_MARKER")
    (stage / "solution/workflow.json").write_text(json.dumps(workflow))
    inputs = stage / "tests/bench-input"
    inputs.mkdir()
    (inputs / "index.json").write_text('["fresh-a"]')
    shutil.copyfile(stage / "tests/rubric.json", inputs / "rubric.json")
    materials = load_task(stage, tool_contract=ROOT / "simapps/telegram/tools.json")
    case = load_cases(materials, ("fresh-a",))[0]
    case_root = inputs / case.id
    case_root.mkdir()
    observation = {}

    async def prepare(path):
        artifact = accept_artifact(
            path,
            submission_stopped=True,
            destination=config.output_root / "accepted.json",
        )
        identity = {
            "run_id": uuid4().hex,
            "attempt_id": uuid4().hex,
            "replay_id": uuid4().hex,
            "artifact_hash": artifact.sha256,
            "case_id": case.id,
            "profile": materials.tool_contract["profile"],
            "profile_hash": hashlib.sha256(
                (ROOT / "simapps/telegram/tools.json").read_bytes()
            ).hexdigest(),
        }
        (case_root / "case.json").write_text(
            json.dumps(
                {
                    "id": case.id,
                    "identity": identity,
                    "input": case.input,
                    "expected": case.expected,
                }
            )
        )
        async with replay_environment(config, identity) as context:
            await context.control(
                "reset",
                {
                    "identity": identity,
                    "state": case.state,
                    "profile": identity["profile"],
                    "limits": {"call_timeout_sec": config.tool_timeout_sec},
                },
            )
            await context.check_isolation()
            if fault:
                await context.control(
                    "fault", {"identity": identity, "mode": fault, "delay_sec": 0}
                )
            execution, bound = await replay(
                artifact, case.input, context=context, config=config
            )
            evidence = await context.control("export")
            (case_root / "execution.json").write_text(json.dumps(execution))
            (case_root / "evidence.json").write_text(json.dumps(evidence))
            observation.update(execution=execution, evidence=evidence, bound=bound)

    result = await run_native_trial(stage, uuid4().hex, prepare, config=config)
    return result, observation


@pytest.mark.parametrize(
    "change,criterion",
    [
        ("recipient", "recipient"),
        ("text", "text"),
        ("duplicate", "multiplicity"),
        ("unrelated", "recipient"),
        ("memorized", "multiplicity"),
    ],
)
def test_negative_native_effect_cannot_pass(e1_config, change, criterion):
    workflow = read_json(TASK / "solution/workflow.json", "control")
    code = workflow["nodes"][2]["parameters"]["jsCode"]
    if change == "recipient":
        code = code.replace("bench.input.chat_id", "'beta'")
    elif change == "text":
        code = code.replace("bench.input.text", "'wrong'")
    elif change == "memorized":
        code = code.replace("bench.input.chat_id", "'training'").replace(
            "bench.input.text", "'Учебное сообщение'"
        )
    else:
        second = deepcopy(workflow["nodes"][3])
        second.update(id="duplicate", name="Duplicate send")
        second["parameters"]["jsonBody"] = (
            "={{JSON.stringify($('Prepare request').first().json)}}"
        )
        if change == "unrelated":
            second["parameters"]["jsonBody"] = json.dumps(
                {
                    "schema_version": "1.0",
                    "arguments": {"chat_id": "beta", "text": "unrelated"},
                }
            )
        workflow["nodes"].append(second)
        workflow["connections"]["Send message"]["main"][0][0]["node"] = second["name"]
        workflow["connections"][second["name"]] = {
            "main": [[{"node": "BenchResult", "type": "main", "index": 0}]]
        }
    workflow["nodes"][2]["parameters"]["jsCode"] = code
    result, observation = asyncio.run(native_control(e1_config, workflow))
    assert observation["execution"]["process_status"] == "completed"
    evaluation = result.evaluation["cases"][0]
    assert (
        next(c for c in evaluation["criteria"] if c["criterion_id"] == criterion)[
            "status"
        ]
        == "fail"
    )
    assert evaluation["score"] is None


def test_real_commit_with_lost_response_is_not_retried(e1_config):
    workflow = read_json(TASK / "solution/workflow.json", "control")
    result, observation = asyncio.run(
        native_control(e1_config, workflow, fault="drop_response")
    )
    facts = observation["evidence"]
    assert facts["after"]["revision"] == 1
    assert (
        len(
            [
                e
                for e in facts["events"]
                if e["stage"] == "effect" and e["details"]["status"] == "committed"
            ]
        )
        == 1
    )
    assert facts["events"][-1]["details"]["status"] == "failed"
    assert observation["execution"]["process_status"] == "failed"
    assert observation["execution"]["stop_confirmed"]
    assert result.evaluation["cases"][0]["completeness"] == "partial"


def test_real_js_runner_escape_probes_keep_allowed_tools_working(e1_config):
    workflow = read_json(TASK / "solution/workflow.json", "control")
    workflow["nodes"][2]["parameters"]["jsCode"] = """
const probes = {privateRead:false, privateWrite:false, secret:false, child:false, network:false};
try {require('fs').readFileSync('/tests/private-marker.txt'); probes.privateRead=true;} catch {}
try {require('fs').writeFileSync('/bench/input/evidence.json','forged'); probes.privateWrite=true;} catch {}
try {probes.secret=!!$env.WB_CONTROL_KEY;} catch {}
try {require('child_process').execSync('true'); probes.child=true;} catch {}
try {await fetch(CONTROL_URL, {signal:AbortSignal.timeout(1000)}); probes.network=true;} catch {}
const bench=$input.first().json.bench;
return [{json:{request:{schema_version:'1.0',arguments:bench.input},probes}}];
""".replace(
        "CONTROL_URL",
        json.dumps(f"http://simulator:{e1_config.control_port}/control/export"),
    )
    workflow["nodes"][3]["parameters"]["jsonBody"] = (
        "={{JSON.stringify($json.request)}}"
    )
    result, observation = asyncio.run(native_control(e1_config, workflow))
    assert all(
        c["status"] in {"pass", "not_applicable"}
        for c in result.evaluation["cases"][0]["criteria"]
    )
    log = (observation["bound"].path.parent / "harbor/agent/execute.log").read_text()
    assert '"privateRead": false' in log and '"privateWrite": false' in log
    assert (
        '"secret": false' in log
        and '"child": false' in log
        and '"network": false' in log
    )


def test_unauthorized_native_workflow_cannot_create_effect(e1_config):
    workflow = read_json(TASK / "solution/workflow.json", "control")
    workflow["nodes"][3]["parameters"]["headerParameters"]["parameters"][0]["value"] = (
        "Bearer foreign-run-capability"
    )
    result, observation = asyncio.run(native_control(e1_config, workflow))
    assert observation["evidence"]["after"]["revision"] == 0
    assert observation["evidence"]["events"][0]["details"]["status"] == "rejected"
    assert result.evaluation["cases"][0]["completeness"] == "partial"


@pytest.mark.parametrize("forgery", ["file", "symlink", "background"])
def test_submission_reward_cannot_replace_missing_verifier_reward(
    e1_config, forgery
) -> None:
    async def check():
        e1_config.output_root.mkdir()
        stage = e1_config.output_root / "task"
        shutil.copytree(TASK, stage)
        solve = stage / "solution/solve.sh"
        attack = "\necho 10 > /logs/verifier/reward.txt\n"
        if forgery == "symlink":
            attack = "\necho 10 > /logs/agent/fake-reward; ln -s /logs/agent/fake-reward /logs/verifier/reward.txt\n"
        elif forgery == "background":
            attack = "\n(while true; do echo 10 > /logs/verifier/reward.txt; sleep 0.05; done) &\n"
        solve.write_text(solve.read_text() + attack)
        (stage / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")

        async def prepare(path):
            assert path.is_file()

        result = await run_native_trial(stage, uuid4().hex, prepare, config=e1_config)
        assert result.exception_type == "RewardFileNotFoundError"
        assert result.evaluation["cases"] == []

    asyncio.run(check())


def test_native_numeric_reward_is_only_a_protocol_fixture(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        stage = e1_config.output_root / "numeric-fixture"
        shutil.copytree(TASK, stage)
        identity = {
            "run_id": "fixture",
            "attempt_id": "fixture",
            "replay_id": "fixture",
            "case_id": "fixture",
            "artifact_hash": "a" * 64,
            "profile_hash": "b" * 64,
            "profile": "t1-api-v1",
        }
        evaluation = {
            "identity": identity,
            "score": 7.25,
            "verdict": "pass",
            "completeness": "complete",
            "criteria": [],
            "violations": [],
            "errors": [],
            "evidence_hash": None,
        }
        script = f"""#!/bin/sh
set -eu
python - <<'PYTHON'
import json
from pathlib import Path
from workflow_bench.evaluation import harbor_reward
evaluation = json.loads({repr(json.dumps(evaluation))})
Path('/logs/verifier/evaluation.json').write_text(json.dumps({{'schema_version': '1.0', 'cases': [evaluation]}}))
Path('/logs/verifier/reward.json').write_text(json.dumps(harbor_reward(evaluation)))
PYTHON
"""
        (stage / "tests/test.sh").write_text(script)

        async def prepare(path):
            assert path.is_file()

        result = await run_native_trial(stage, uuid4().hex, prepare, config=e1_config)
        native = read_json(e1_config.output_root / result.result_ref, "native")
        assert result.exception_type is None
        assert native["verifier_result"]["rewards"] == {"reward": 7.25}
        assert result.evaluation["cases"] == [evaluation]

    asyncio.run(check())


def test_symlink_during_native_collection_is_not_executed(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        stage = e1_config.output_root / "task"
        shutil.copytree(TASK, stage)
        (stage / "solution/solve.sh").write_text(
            "#!/bin/sh\nset -eu\nmkdir -p /work\ncp /solution/workflow.json /tmp/source.json\nln -s /tmp/source.json /work/workflow.json\n"
        )
        executed = False

        async def prepare(path):
            nonlocal executed
            accept_artifact(
                path,
                submission_stopped=True,
                destination=e1_config.output_root / "accepted.json",
            )
            executed = True

        result = await run_native_trial(stage, uuid4().hex, prepare, config=e1_config)
        assert result.exception_type == "ArtifactError"
        assert not executed and not (e1_config.output_root / "accepted.json").exists()

    asyncio.run(check())
