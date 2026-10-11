"""Accept a stopped native submission and bind only its declared input slot."""

import asyncio
import base64
import hashlib
import json
import logging
import math
import os
import stat
import time
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import ClientError

from workflow_bench.contracts import (
    BoundWorkflow,
    E1Config,
    JsonValue,
    WorkflowArtifact,
)
from workflow_bench.data import (
    MAX_JSON_BYTES,
    DataError,
    decode_json,
    resource_schema,
    validate_contract,
    validate_json,
)

if TYPE_CHECKING:
    from workflow_bench.harbor import ReplayContext

LOGGER = logging.getLogger(__name__)


class ArtifactError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def accept_artifact(
    collected_file: Path, *, submission_stopped: bool, destination: Path
) -> WorkflowArtifact:
    """Copy submitted bytes after the writer has stopped; never repair a file."""
    if not submission_stopped:
        raise ArtifactError("unconfirmed_submission")
    if not collected_file.is_absolute() or not destination.is_absolute():
        raise ArtifactError("unsafe_file")
    if any(p.is_symlink() for p in (collected_file, *collected_file.parents)):
        raise ArtifactError("unsafe_file")
    profile = resource_schema("workflow.schema.json")
    try:
        descriptor = os.open(
            collected_file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ArtifactError("unsafe_file")
            content = stream.read(profile["x-max-bytes"] + 1)
    except FileNotFoundError:
        raise ArtifactError("missing") from None
    except OSError:
        raise ArtifactError("unsafe_file") from None
    if len(content) > profile["x-max-bytes"]:
        raise ArtifactError("too_large")
    try:
        document = decode_json(content, "workflow.json")
    except DataError:
        raise ArtifactError("invalid_json") from None
    try:
        validate_json(document, profile, "workflow.json")
        _check_graph(document)
    except (DataError, ValueError, KeyError, TypeError):
        raise ArtifactError("invalid_profile") from None
    with destination.open("xb") as stream:
        stream.write(content)
    destination.chmod(0o600)
    return WorkflowArtifact(
        destination, hashlib.sha256(content).hexdigest(), len(content), document
    )


def _check_graph(workflow: dict[str, JsonValue]) -> None:
    nodes = workflow["nodes"]
    names = {node["name"] for node in nodes}
    if len(names) != len(nodes) or len({node["id"] for node in nodes}) != len(nodes):
        raise ValueError("duplicate_node")
    by_name = {node["name"]: node for node in nodes}
    edges = {}
    for name, connections in workflow["connections"].items():
        if name not in names:
            raise ValueError("unknown_node")
        edges[name] = [edge["node"] for slot in connections["main"] for edge in slot]
        if not set(edges[name]) <= names:
            raise ValueError("unknown_node")
    triggers = [n for n in nodes if n["type"] == "n8n-nodes-base.manualTrigger"]
    if len(triggers) != 1 or edges.get(triggers[0]["name"]) != ["BenchInput"]:
        raise ValueError("input_path")
    input_node = by_name["BenchInput"]
    if input_node["type"] != "n8n-nodes-base.set":
        raise ValueError("input_type")
    assignments = input_node["parameters"]["assignments"]["assignments"]
    if len(assignments) != 1:
        raise ValueError("input_fields")
    entry = assignments[0]
    if entry["name"] != "bench" or entry["type"] != "object":
        raise ValueError("input_field")
    if not isinstance(entry["value"], str) or not entry["value"].startswith("{"):
        raise ValueError("input_literal")
    if decode_json(entry["value"].encode(), "bench") != {"input": {}, "tools": {}}:
        raise ValueError("input_literal")
    result_node = by_name["BenchResult"]
    if result_node["type"] != "n8n-nodes-base.set" or edges.get("BenchResult"):
        raise ValueError("result_terminal")
    fields = result_node["parameters"]["assignments"]["assignments"]
    if sorted(f["name"] for f in fields) != ["reason_code", "result", "status"]:
        raise ValueError("result_fields")
    if any(
        "BenchInput" in targets
        for source, targets in edges.items()
        if source != triggers[0]["name"]
    ):
        raise ValueError("input_incoming")
    reachable = set()
    pending = [triggers[0]["name"]]
    while pending:
        current = pending.pop()
        if current not in reachable:
            reachable.add(current)
            pending.extend(edges.get(current, []))
    if reachable != names:
        raise ValueError("unreachable_node")
    if any(not edges.get(name) for name in names - {"BenchResult"}):
        raise ValueError("unclaimed_terminal")
    terminating = {"BenchResult"}
    pending = ["BenchResult"]
    while pending:
        target = pending.pop()
        for source, targets in edges.items():
            if target in targets and source not in terminating:
                terminating.add(source)
                pending.append(source)
    if terminating != names:
        raise ValueError("closed_branch")


def bind_workflow(
    artifact: WorkflowArtifact,
    *,
    case_input: JsonValue,
    base_url: str,
    capability: str,
    destination: Path,
) -> BoundWorkflow:
    """Serialize input as literal JSON text; preserve all other native parameters."""
    document = deepcopy(artifact.document)
    index = next(
        i for i, node in enumerate(document["nodes"]) if node["name"] == "BenchInput"
    )
    value = {
        "input": case_input,
        "tools": {"base_url": base_url, "capability": capability},
    }
    document["nodes"][index]["parameters"]["assignments"]["assignments"][0]["value"] = (
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    )
    content = json.dumps(document, ensure_ascii=False, allow_nan=False).encode()
    if len(content) > MAX_JSON_BYTES:
        raise ArtifactError("bound_too_large")
    with destination.open("xb") as stream:
        stream.write(content)
    destination.chmod(0o600)
    return BoundWorkflow(
        destination,
        artifact.sha256,
        hashlib.sha256(content).hexdigest(),
        (f"/nodes/{index}/parameters/assignments/assignments/0/value",),
    )


def _cli_data(output: str) -> dict[str, JsonValue] | None:
    data = None
    decoder = json.JSONDecoder()
    for offset in range(len(output)):
        if output[offset] == "{" and (offset == 0 or output[offset - 1] == "\n"):
            try:
                _, consumed = decoder.raw_decode(output[offset:])
                candidate = decode_json(
                    output[offset : offset + consumed].encode(), "n8n_output"
                )
                if candidate.get("mode") == "cli" and isinstance(
                    candidate.get("data"), dict
                ):
                    data = candidate
            except (ValueError, AttributeError):
                continue
    return data


async def replay(
    artifact: WorkflowArtifact,
    case_input: JsonValue,
    *,
    context: "ReplayContext",
    config: E1Config,
) -> tuple[dict[str, JsonValue], BoundWorkflow]:
    """Borrow Harbor handles; import/execute once, freeze and stop, never retry a write."""
    issued = await context.control(
        "issue",
        {
            "identity": context.identity,
            "actor": "workflow",
            "ttl_sec": config.execute_timeout_sec + config.drain_timeout_sec,
            "max_calls": config.max_calls,
        },
    )
    bound = bind_workflow(
        artifact,
        case_input=case_input,
        base_url=f"http://simulator:{config.tools_port}",
        capability=issued["capability"],
        destination=context.root / "bound.json",
    )
    encoded = base64.b64encode(bound.path.read_bytes()).decode()
    logs = context.root / "harbor/agent"
    logs.mkdir()
    result: dict[str, JsonValue] = {
        "process_status": "not_started",
        "exit_code": None,
        "claim": None,
        "stop_confirmed": False,
    }
    LOGGER.info("phase=replay case_id=%s log=%s", context.identity["case_id"], logs)
    started = time.monotonic()
    try:
        async with asyncio.timeout(config.execute_timeout_sec):
            uploaded = await context.environment.service_exec(
                f"printf %s '{encoded}' | base64 -d > /tmp/workflow.json",
                service="n8n",
                timeout_sec=math.ceil(config.control_timeout_sec),
            )
            if uploaded.return_code:
                raise RuntimeError("workflow_transfer_failed")
            imported = await context.environment.service_exec(
                f'n8n import:workflow --input=/tmp/workflow.json > /tmp/import-output 2>&1; status=$?; head -c {MAX_JSON_BYTES} /tmp/import-output; exit "$status"',
                service="n8n",
                timeout_sec=math.ceil(config.execute_timeout_sec),
            )
            (logs / "import.log").write_text(
                (imported.stdout or "") + (imported.stderr or "")
            )
            if imported.return_code:
                result.update(process_status="failed", exit_code=imported.return_code)
            else:
                workflow_id = artifact.document["id"]
                executed = await context.environment.service_exec(
                    f'n8n execute --id={workflow_id} --rawOutput > /tmp/execute-output 2>&1; status=$?; head -c {MAX_JSON_BYTES} /tmp/execute-output; exit "$status"',
                    service="n8n",
                    timeout_sec=math.ceil(config.execute_timeout_sec),
                )
                output = (executed.stdout or "") + (executed.stderr or "")
                (logs / "execute.log").write_text(output)
                data = _cli_data(output)
                result.update(
                    process_status="completed"
                    if executed.return_code == 0
                    and data
                    and data.get("status") == "success"
                    else "failed",
                    exit_code=executed.return_code,
                )
                if (
                    data
                    and data["data"].get("resultData", {}).get("lastNodeExecuted")
                    == "BenchResult"
                ):
                    try:
                        items = data["data"]["resultData"]["runData"]["BenchResult"][
                            -1
                        ]["data"]["main"][0]
                        if len(items) == 1:
                            claim = items[0]["json"]
                            validate_contract("claim", claim)
                            result["claim"] = claim
                    except (DataError, KeyError, IndexError, TypeError):
                        pass
    except TimeoutError:
        result["process_status"] = "timed_out"
    except (ConnectionError, ClientError, RuntimeError) as error:
        result.update(
            process_status="unknown", errors=["exec_failed:" + type(error).__name__]
        )
    except asyncio.CancelledError:
        result["process_status"] = "cancelled"
        raise
    finally:
        LOGGER.info("phase=freeze case_id=%s", context.identity["case_id"])
        result["stop_requested"] = True
        result["stop_confirmed"] = await context.finish()
        stop = json.loads((context.root / "stop.json").read_text())
        result["errors"] = result.get("errors", []) + stop["errors"]
        if not result["stop_confirmed"]:
            result["initial_process_status"] = result["process_status"]
            result["process_status"] = "unknown"
        (context.root / "execution.json").write_text(json.dumps(result))
        LOGGER.info(
            "phase=replay result=%s case_id=%s elapsed=%.2fs",
            result["process_status"],
            context.identity["case_id"],
            time.monotonic() - started,
        )
    return result, bound
