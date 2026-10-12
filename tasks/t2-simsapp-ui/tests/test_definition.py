from pathlib import Path

from workflow_bench.definition import export_public, load_cases, load_task

TASK = Path(__file__).resolve().parents[1]
ROOT = TASK.parents[1]


def test_task_loads_and_exports_only_public_materials(tmp_path):
    materials = load_task(TASK, tool_contract=ROOT / "simapps/simsapp/tools.json")
    cases = load_cases(materials)
    assert cases[0].input == {
        "display_name": "Alex Morgan",
        "reference": "#A-1042",
        "text": "Your order will be delivered on Friday.",
    }
    package = export_public(materials, tmp_path / "public")
    assert {p.name for p in package.root.iterdir()} == {
        "instruction.md",
        "task.json",
        "tools.json",
        "workflow.md",
        "workflow.schema.json",
        "composer.md",
    }
    assert not (package.root / "tests").exists()


def test_private_final_is_loaded_but_never_exported(tmp_path):
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(
        "prepare_private", TASK / "prepare_private.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case = {
        "id": "synthetic-final",
        "input": {
            "display_name": "Final sentinel",
            "reference": "#FINAL",
            "text": "PRIVATE_SENTINEL",
        },
        "state": {
            "conversations": [],
            "messages": [],
            "ui": {
                "screen": "chat_list",
                "active_conversation_id": None,
                "query": "",
                "focus": None,
                "drafts": {},
            },
        },
        "expected": {"outcome": "refused", "reason_code": "not_found"},
    }
    final = tmp_path / "source.json"
    final.write_text(
        json.dumps({"schema_version": "1.0", "purpose": "final", "cases": [case]})
    )
    destination = tmp_path / "private-task"
    module.prepare(TASK, final, destination, ROOT / "simapps/simsapp/tools.json")
    materials = load_task(
        destination, tool_contract=ROOT / "simapps/simsapp/tools.json"
    )
    assert load_cases(materials, purpose="final")[0].id == "synthetic-final"
    assert destination.stat().st_mode & 0o777 == 0o700
    package = export_public(materials, tmp_path / "public-final")
    assert all("PRIVATE_SENTINEL" not in p.read_text() for p in package.root.iterdir())


def test_verifier_schema_and_development_states_match_public_contract():
    import json

    from workflow_bench.data import validate_json

    public = json.loads((TASK / "task.json").read_text())
    assert (
        json.loads((TASK / "tests/input.schema.json").read_text())
        == public["input_schema"]
    )
    schema = json.loads((ROOT / "simapps/simsapp/state.schema.json").read_text())
    materials = load_task(TASK, tool_contract=ROOT / "simapps/simsapp/tools.json")
    for case in load_cases(materials):
        validate_json(case.state, schema, "state")
        assert len(case.state["messages"]) < 100


def test_missing_private_final_is_not_substituted_with_development():
    import pytest

    from workflow_bench.data import DataError

    materials = load_task(TASK, tool_contract=ROOT / "simapps/simsapp/tools.json")
    with pytest.raises(DataError, match="missing_final_cases"):
        load_cases(materials, purpose="final")
