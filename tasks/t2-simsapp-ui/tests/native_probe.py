"""Submit a supported observation-only native artifact to locate the next blocker.

This probe is deliberately not the reference solution and cannot pass the Task.
"""

import argparse
import asyncio
import json
import logging
import shutil
from pathlib import Path

from workflow_bench.cli import load_config
from workflow_bench.experiment import run_manual

TASK = Path(__file__).resolve().parents[1]


async def probe(config: Path, output: Path) -> None:
    output.mkdir(mode=0o700)
    stage = output / "probe-task"
    shutil.copytree(TASK, stage, ignore=shutil.ignore_patterns("__pycache__"))
    workflow = json.loads((stage / "solution/workflow.json").read_text())
    workflow["nodes"] = [
        n for n in workflow["nodes"] if n["name"] not in {"Decide", "Finished"}
    ]
    request = next(n for n in workflow["nodes"] if n["name"] == "UI request")
    request["parameters"]["url"] = (
        "={{$('BenchInput').first().json.bench.tools.base_url + '/tools/ui_observe'}}"
    )
    request["parameters"]["jsonBody"] = '{"schema_version":"1.0","arguments":{}}'
    terminal = workflow["nodes"][-1]["parameters"]["assignments"]["assignments"]
    for field in terminal:
        field["value"] = {
            "status": "unknown",
            "reason_code": "diagnostic_only",
            "result": "={{null}}",
        }[field["name"]]
    names = [n["name"] for n in workflow["nodes"]]
    workflow["connections"] = {
        a: {"main": [[{"node": b, "type": "main", "index": 0}]]}
        for a, b in zip(names, names[1:], strict=False)
    }
    (stage / "solution/workflow.json").write_text(json.dumps(workflow))
    report = await run_manual(
        stage, config=load_config(config, output=output / "run"), case_ids=("unique",)
    )

    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "score": report["score"],
                "report": str(output / "run/report.json"),
            }
        )
    )
    if report["business_completeness"] == "unavailable":
        raise SystemExit(2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(probe(args.config.resolve(), args.output.resolve()))
