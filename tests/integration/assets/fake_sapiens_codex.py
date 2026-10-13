#!/usr/bin/env python3
"""Answer pinned Sapiens decision prompts inside an integration test image."""

import json
import os
import re
import sys
import time
from pathlib import Path
from uuid import uuid4


def _decision(prompt: str) -> dict[str, object]:
    """Return one response for the current Sapiens decision node and scenario."""
    node_match = re.search(r"decision at node (\w+)", prompt)
    if node_match is None:
        raise ValueError("missing Sapiens decision node")
    node = node_match.group(1)
    scenario = os.environ["WB_SAPIENS_SCENARIO"]
    context = json.loads(prompt.rsplit("\nContext:\n", 1)[1])
    is_chief = context["selfId"] == context["chiefId"]
    if node == "Assessing":
        if scenario in {"delegate", "unclear"} and is_chief:
            return {"event": "OutsideSpecialization"}
        return {"event": "FitsSpecialization", "mode": "Exec"}
    if node == "ChiefTriage" and scenario == "unclear":
        decision = {"event": "RequestUnclear", "question": "Which basket?"}
        Path("/logs/agent/unclear-decision.json").write_text(json.dumps(decision))
        return decision
    if node == "ChiefTriage" and scenario == "delegate":
        return {"event": "NewSpecialistNeeded"}
    if node == "CreatingSapi" and scenario == "delegate":
        return {
            "event": "SapiSpecified",
            "name": "BasketExpert",
            "role": "Calculate basket totals",
        }
    if node == "Delegation" and scenario == "delegate":
        return {
            "event": "HandoffPrepared",
            "request": "Calculate the basket total and write /work/output/answer.json",
        }
    if node == "ReadyToWork":
        return {
            "event": "TaskPrepared",
            "taskType": "basket-total",
            "specification": {
                "objective": "Write the basket total to answer.json",
                "inputs": ["Basket prices in Admin request"],
                "expectedOutputs": ["/work/output/answer.json"],
                "completionCriteria": [
                    "The answer file has the correct count and total"
                ],
            },
        }
    if node == "Execution":
        if scenario == "stop":
            if os.fork() == 0:
                os.setsid()
                Path("/logs/agent/child-started").write_text(str(os.getpid()))
                time.sleep(8)
                Path("/logs/agent/late-write").write_text("escaped stop")
                time.sleep(120)
                os._exit(0)
            time.sleep(120)
            raise RuntimeError("stop control unexpectedly resumed")
        if scenario == "delegate":
            if is_chief:
                raise ValueError("Chief executed specialist work")
            time.sleep(3)
            Path("/logs/agent/specialist-executed.json").write_text(
                json.dumps({"self": context["selfId"], "chief": context["chiefId"]})
            )
        answer = {"item_count": 7, "total_cents": 1178}
        Path("/work/output/answer.json").write_text(json.dumps(answer))
        return {
            "event": "Outcome",
            "reply": "Basket answer written",
            "outcome": {
                "status": "Completed",
                "satisfiedCriteria": [
                    "The answer file has the correct count and total"
                ],
                "artifacts": ["/work/output/answer.json"],
            },
            "evidence": ["The answer file was written"],
        }
    raise ValueError(f"unexpected Sapiens node {node}")


def main() -> int:
    """Emit Codex JSONL events with a prepared Sapiens decision as the answer."""
    if "--version" in sys.argv:
        sys.stdout.write("codex-cli 0.162.1\n")
        return 0
    if len(sys.argv) < 2 or sys.argv[1] != "exec":
        raise ValueError("expected codex exec")
    if os.environ.get("WB_SAPIENS_SCENARIO") not in {
        "direct",
        "delegate",
        "unclear",
        "stop",
    }:
        raise ValueError("unexpected control scenario")
    prompt = sys.stdin.read()
    response = {"reason": "Prepared test decision", "evidence": ["Fixture request"]}
    response.update(_decision(prompt))
    sys.stdout.write(
        json.dumps({"type": "thread.started", "thread_id": str(uuid4())}) + "\n"
    )
    sys.stdout.write(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(response)},
            }
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
