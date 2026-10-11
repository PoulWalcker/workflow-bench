import json
import os
from pathlib import Path

import pytest

from workflow_bench.execution import ArtifactError, accept_artifact, bind_workflow

CONTROL = (
    Path(__file__).resolve().parents[2] / "tasks/t1-send-message/solution/workflow.json"
)


def test_missing_submission_cannot_be_replayed(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="missing"):
        accept_artifact(
            tmp_path / "missing.json",
            submission_stopped=True,
            destination=tmp_path / "accepted.json",
        )


def test_credential_reference_is_rejected_even_on_unused_node(tmp_path: Path) -> None:
    workflow = json.loads(CONTROL.read_bytes())
    workflow["nodes"][3]["credentials"] = {"httpHeaderAuth": {"id": "private"}}
    submitted = tmp_path / "workflow.json"
    submitted.write_text(json.dumps(workflow))
    with pytest.raises(ArtifactError, match="invalid_profile"):
        accept_artifact(
            submitted, submission_stopped=True, destination=tmp_path / "accepted.json"
        )


def test_binding_preserves_source_logic_and_encodes_input_as_data(
    tmp_path: Path,
) -> None:
    original = CONTROL.read_bytes()
    artifact = accept_artifact(
        CONTROL, submission_stopped=True, destination=tmp_path / "accepted.json"
    )
    bound = bind_workflow(
        artifact,
        case_input={"chat_id": "new", "text": '={{danger}}\n"quoted"'},
        base_url="http://simulator:9000",
        capability="test-capability",
        destination=tmp_path / "bound.json",
    )
    source = json.loads(original)
    result = json.loads(bound.path.read_bytes())
    literal = result["nodes"][1]["parameters"]["assignments"]["assignments"][0]["value"]
    assert isinstance(literal, str) and literal.startswith("{")
    assert json.loads(literal)["input"] == {
        "chat_id": "new",
        "text": '={{danger}}\n"quoted"',
    }
    result["nodes"][1]["parameters"]["assignments"]["assignments"][0]["value"] = source[
        "nodes"
    ][1]["parameters"]["assignments"]["assignments"][0]["value"]
    assert result == source
    assert artifact.path.read_bytes() == original
    assert bound.source_hash == artifact.sha256 and bound.bound_hash != artifact.sha256


@pytest.mark.parametrize(
    "change",
    [
        "pinData",
        "staticData",
        "version",
        "option",
        "port",
        "slot",
        "duplicate_name",
        "retry",
        "extra_trigger",
    ],
)
def test_unsupported_native_configuration_is_rejected(
    tmp_path: Path, change: str
) -> None:
    workflow = json.loads(CONTROL.read_bytes())
    if change in {"pinData", "staticData"}:
        workflow[change] = {}
    elif change == "version":
        workflow["nodes"][2]["typeVersion"] = 99
    elif change == "option":
        workflow["nodes"][3]["parameters"]["options"]["redirect"] = {
            "followRedirects": True
        }
    elif change == "port":
        workflow["connections"]["Start"]["main"][0][0]["index"] = 1
    elif change == "slot":
        workflow["nodes"][1]["parameters"]["assignments"]["assignments"][0]["value"] = (
            '={"input":{},"tools":{}}'
        )
    elif change == "duplicate_name":
        workflow["nodes"][2]["name"] = "BenchInput"
    elif change == "retry":
        workflow["nodes"][3]["retryOnFail"] = True
    else:
        workflow["nodes"].append(
            {**workflow["nodes"][0], "id": "extra", "name": "Extra"}
        )
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(workflow))
    with pytest.raises(ArtifactError, match="invalid_profile"):
        accept_artifact(
            path, submission_stopped=True, destination=tmp_path / "accepted.json"
        )


@pytest.mark.parametrize(
    "kind",
    [
        "symlink",
        "hardlink",
        "fifo",
        "unconfirmed",
        "duplicate_json",
        "nonfinite",
        "too_large",
    ],
)
def test_unsafe_or_unfinished_submission_cannot_become_artifact(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "candidate.json"
    expected = "unsafe_file"
    if kind == "symlink":
        path.symlink_to(CONTROL)
    elif kind == "hardlink":
        original = tmp_path / "original.json"
        original.write_bytes(CONTROL.read_bytes())
        path.hardlink_to(original)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "unconfirmed":
        path.write_bytes(CONTROL.read_bytes())
        expected = "unconfirmed_submission"
    elif kind == "duplicate_json":
        path.write_text('{"name":"a","name":"b"}')
        expected = "invalid_json"
    elif kind == "nonfinite":
        path.write_text('{"name": NaN}')
        expected = "invalid_json"
    else:
        path.write_bytes(b" " * 65537)
        expected = "too_large"
    with pytest.raises(ArtifactError, match=expected):
        accept_artifact(
            path,
            submission_stopped=kind != "unconfirmed",
            destination=tmp_path / "accepted.json",
        )
