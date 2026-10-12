"""Explicit model-free Harbor UI controls, followed by its separate verifier.

These are ui_control episodes, never native n8n Replay or a benchmark score.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import math
import shlex
import shutil
from pathlib import Path
from uuid import uuid4

from workflow_bench.cli import load_config
from workflow_bench.data import read_json
from workflow_bench.definition import load_cases, load_task
from workflow_bench.evaluation import read_evidence
from workflow_bench.harbor import assert_stopped, replay_environment, run_native_trial

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]
LOGGER = logging.getLogger(__name__)


def script(
    case_input: dict, base: str, capability: str, timeout: float, limit: int, mode: str
) -> str:
    return (
        (TASK / "solution/reference.js").read_text()
        + "\n"
        + f"""
const input = {json.dumps(case_input)};
const base = {json.dumps(base)}, capability = {json.dumps(capability)};
async function call(name, args) {{
  return await (await fetch(base+'/tools/'+name, {{method:'POST',
    headers:{{Authorization:'Bearer '+capability,'Content-Type':'application/json'}},
    body:JSON.stringify({{schema_version:'1.0',arguments:args}}),
    signal:AbortSignal.timeout({math.ceil(timeout * 1000)})}})).json();
}}
(async()=>{{
  if ({json.dumps(mode)} === 'altered') input.text += ' changed';
  let state = {{input}}, response = null;
  for (let i=0; i<{limit}; i++) {{
    state = step(state, response);
    if (state.done) break;
    response = await call(state.operation, state.arguments);
  }}
  if (!state.done) throw new Error('control_limit');
  if ({json.dumps(mode)} === 'bypass') await call('send_message', {{}});
  if ({json.dumps(mode)} === 'duplicate') {{
    state = {{input}}; response = null;
    for (let i=0; i<{limit}; i++) {{
      state=step(state,response); if(state.done) break;
      response=await call(state.operation,state.arguments);
    }}
  }}
  console.log(JSON.stringify(state.claim));
}})().catch(()=>process.exit(1));
"""
    )


async def run(config_path: Path, output: Path) -> None:
    config = load_config(config_path, output=output)
    output.mkdir(mode=0o700)
    materials = load_task(TASK, tool_contract=ROOT / "simapps/simsapp/tools.json")
    cases = load_cases(materials)
    stage = output / "task"
    shutil.copytree(TASK, stage, ignore=shutil.ignore_patterns("__pycache__"))
    inputs = stage / "tests/bench-input"
    inputs.mkdir()
    run_id = uuid4().hex
    ids = []
    expected_failures = {}
    scenarios = [(case, "reference") for case in cases]
    scenarios += [(cases[0], mode) for mode in ("altered", "duplicate", "bypass")]
    async with asyncio.timeout(config.total_timeout_sec):
        for case, mode in scenarios:
            case_id = case.id + "-" + mode
            LOGGER.info("phase=ui-control case=%s status=start", case_id)
            identity = {
                "protocol": "ui_control",
                "run_id": run_id,
                "control_id": uuid4().hex,
                "case_id": case_id,
                "profile": materials.tool_contract["profile"],
                "profile_hash": hashlib.sha256(
                    (ROOT / "simapps/simsapp/tools.json").read_bytes()
                ).hexdigest(),
            }
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
                issued = await context.control(
                    "issue",
                    {
                        "identity": identity,
                        "actor": "control",
                        "ttl_sec": config.total_timeout_sec,
                        "max_calls": config.max_calls,
                    },
                )
                await context.check_isolation()
                result = await context.environment.service_exec(
                    "node -e "
                    + shlex.quote(
                        script(
                            case.input,
                            f"http://simulator:{config.tools_port}",
                            issued["capability"],
                            config.tool_timeout_sec,
                            config.max_calls,
                            mode,
                        )
                    ),
                    service="n8n",
                    timeout_sec=config.execute_timeout_sec,
                )
                if result.return_code != 0:
                    raise RuntimeError("ui_control_failed")
                claim = json.loads(result.stdout)
                await context.control("revoke", {"identity": identity})
                await context.control(
                    "freeze",
                    {"identity": identity, "drain_sec": config.drain_timeout_sec},
                )
                if not await context.finish():
                    raise RuntimeError("unconfirmed_stop")
                facts = await context.control("export")
                root = inputs / case_id
                root.mkdir()
                (root / "evidence.json").write_text(json.dumps(facts))
                read_evidence(root / "evidence.json", expected_identity=identity)
                (root / "case.json").write_text(
                    json.dumps(
                        {
                            "id": case_id,
                            "identity": identity,
                            "input": case.input,
                            "expected": case.expected,
                        }
                    )
                )
                (root / "claim.json").write_text(json.dumps(claim))
                if context.stop_errors or context.lifecycle.cleanup_errors:
                    raise RuntimeError("cleanup_failed")
            await assert_stopped(context.project, deleted=True)
            ids.append(case_id)
            if mode != "reference":
                expected_failures[case_id] = {
                    "altered": "text",
                    "duplicate": "multiplicity",
                    "bypass": "ui_only",
                }[mode]
            LOGGER.info("phase=ui-control case=%s status=stopped", case_id)
        # Harbor owns input upload, root protection, verifier isolation and collection.
        lines = [
            "#!/bin/sh",
            "set -eu",
            "test ! -w /bench/input",
            'test "$(id -u)" != 0',
        ]
        lines.extend(
            f"python /tests/verify.py --criteria-only --input-dir /bench/input/{case_id} --output /logs/verifier/{case_id}.json --state-schema /bench/state.schema.json"
            for case_id in ids
        )
        (stage / "tests/test.sh").write_text("\n".join(lines) + "\n")

        async def prepared(_path: Path) -> None:
            pass

        native = await run_native_trial(stage, uuid4().hex, prepared, config=config)
        verifier_dir = output / Path(native.result_ref).parent / "verifier"
        summary = []
        for case_id in ids:
            document = read_json(verifier_dir / (case_id + ".json"), "criteria")
            protected = read_evidence(
                inputs / case_id / "evidence.json",
                expected_identity=document["identity"],
            )
            if document["evidence_hash"] != protected.sha256:
                raise RuntimeError("evidence_hash_mismatch")
            criteria = {c["criterion_id"]: c["status"] for c in document["criteria"]}
            if case_id in expected_failures:
                assert criteria[expected_failures[case_id]] == "fail"
            else:
                assert all(
                    s in {"pass", "not_applicable"} for s in criteria.values()
                ), (case_id, criteria)
            summary.append({"case_id": case_id, "criteria": criteria})
        (output / "control-results.json").write_text(
            json.dumps(
                {
                    "protocol": "ui_control",
                    "native_replay": False,
                    "native_verifier_error": native.exception_type,
                    "controls": summary,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.config.resolve(), args.output.resolve()))
