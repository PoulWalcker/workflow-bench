import hashlib
import json
from pathlib import Path

import pytest

from workflow_bench.definition import export_public, load_task


@pytest.fixture
def task_files(tmp_path: Path) -> tuple[Path, Path]:
    task = tmp_path / "synthetic-task"
    task.mkdir()
    (task / "tests").mkdir()
    (task / "solution").mkdir()
    (task / "instruction.md").write_text("Reserve the requested item.\n")
    (task / "task.toml").write_text(
        'schema_version = "1.3"\n'
        "[metadata]\n"
        'wb_public = "task.json"\n'
        'wb_cases = "tests/cases.json"\n'
        'wb_rubric = "tests/rubric.json"\n'
        'wb_app_image = "synthetic-app:fixture"\n'
        'wb_tool_profile = "reserve"\n'
        "[environment]\n"
        'docker_image = "synthetic-composer:fixture"\n'
    )
    public = {
        "input_schema": {
            "type": "object",
            "properties": {"item": {"type": "string"}},
            "required": ["item"],
            "additionalProperties": False,
        },
        "example": {"input": {"item": "book"}, "state": {"stock": ["book"]}},
        "feedback": {"criterion_ids": ["reservation"], "private_values": False},
    }
    (task / "task.json").write_text(json.dumps(public))
    (task / "tests/cases.json").write_text(
        json.dumps(
            {
                "development": [
                    {
                        "id": "fresh",
                        "input": {"item": "pen"},
                        "state": {"stock": ["pen"]},
                        "expected": {"reserved": "pen"},
                    }
                ]
            }
        )
    )
    (task / "tests/rubric.json").write_text("{}")
    (task / "tests/test.sh").write_text("exit 0\n")
    (task / "solution/solve.sh").write_text("exit 0\n")
    tools = tmp_path / "public-tools.json"
    tools.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "app_image": "synthetic-app:fixture",
                "profile": "reserve",
                "tools": [
                    {
                        "name": "reserve",
                        "schema_version": "1.0",
                        "description": "Reserve one item.",
                        "arguments_schema": public["input_schema"],
                        "result_schema": {"type": "object"},
                        "effect": "write",
                        "limits": {"max_items": 1},
                        "errors": ["not_found", "transport_unknown"],
                        "idempotency": "none",
                        "effect_observation": "Read the reservation list.",
                    }
                ],
            }
        )
    )
    return task, tools


def test_exports_complete_public_package(task_files, tmp_path):
    task, tools = task_files
    package = export_public(load_task(task, tool_contract=tools), tmp_path / "public")

    assert package.root == tmp_path / "public"
    assert (
        package.root / "instruction.md"
    ).read_text() == "Reserve the requested item.\n"
    assert json.loads((package.root / "task.json").read_text())["example"] == {
        "input": {"item": "book"},
        "state": {"stock": ["book"]},
    }
    assert json.loads((package.root / "tools.json").read_text())["profile"] == "reserve"
    for name in ("workflow.md", "workflow.schema.json", "composer.md"):
        assert (package.root / name).read_text()
    for relative, digest in package.files:
        assert not Path(relative).is_absolute()
        assert (
            hashlib.sha256((package.root / relative).read_bytes()).hexdigest() == digest
        )


def test_private_materials_never_enter_export(task_files, tmp_path):
    task, tools = task_files
    marker = "PRIVATE-ONLY-CONTROL-9182"
    for relative in (
        "tests/cases.json",
        "tests/rubric.json",
        "tests/test.sh",
        "solution/solve.sh",
        "AGENTS.md",
        ".env",
        "personal.txt",
    ):
        (task / relative).write_text(marker)
    (task / "tests/cases.json").write_text(
        json.dumps(
            {
                "development": [
                    {
                        "id": "private-case",
                        "input": {"item": marker},
                        "state": {"stock": [marker]},
                        "expected": {"reserved": marker},
                    }
                ]
            }
        )
    )
    package = export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert {relative for relative, _ in package.files} == {
        "instruction.md",
        "task.json",
        "tools.json",
        "workflow.md",
        "workflow.schema.json",
        "composer.md",
    }
    for path in package.root.rglob("*"):
        if path.is_file():
            assert marker.encode() not in path.read_bytes()


def test_rejects_private_fields_in_public_envelope(task_files, tmp_path):
    task, tools = task_files
    public_path = task / "task.json"
    public = json.loads(public_path.read_text())
    public["expected"] = "PRIVATE-EXPECTATION-4711"
    public_path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match="invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert "PRIVATE-EXPECTATION-4711" not in str(caught.value)
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize(
    "unsafe",
    ["../outside.json", "/tmp/outside.json", "tests/cases.json", r"bad\u0000.json"],
)
def test_rejects_unsafe_public_reference(task_files, tmp_path, unsafe):
    task, tools = task_files
    config = task / "task.toml"
    config.write_text(
        config.read_text().replace('wb_public = "task.json"', f'wb_public = "{unsafe}"')
    )
    (tmp_path / "outside.json").write_text((task / "task.json").read_text())
    (task / "tests/cases.json").write_text((task / "task.json").read_text())
    with pytest.raises(ValueError, match="unsafe_path"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize(
    "relative",
    ["task.json", "instruction.md", "task.toml", "tools.json", "tests/cases.json"],
)
def test_rejects_symlink_materials(task_files, tmp_path, relative):
    task, tools = task_files
    path = tools if relative == "tools.json" else task / relative
    forbidden = tmp_path / "forbidden-source"
    forbidden.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(forbidden)
    with pytest.raises(ValueError, match="unsafe_path"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize(
    "malformed",
    [
        '{"example":',
        '{"input_schema": {}, "input_schema": {}}',
        '{"value": NaN}',
        '{"value": Infinity}',
        '{"value": 1e999}',
        b"\xff",
    ],
)
def test_rejects_malformed_json_without_values(task_files, tmp_path, malformed):
    task, tools = task_files
    public = json.loads((task / "task.json").read_text())
    if malformed == '{"input_schema": {}, "input_schema": {}}':
        value = (
            json.dumps(public)
            .replace('"example":', '"feedback": {}, "example":')
            .encode()
        )
    elif malformed in ('{"value": NaN}', '{"value": Infinity}', '{"value": 1e999}'):
        number = malformed.split(": ")[1][:-1]
        value = (
            json.dumps(public)
            .replace('"stock": ["book"]', f'"stock": {number}')
            .encode()
        )
    else:
        value = malformed if isinstance(malformed, bytes) else malformed.encode()
    (task / "task.json").write_bytes(value)
    with pytest.raises(ValueError, match="invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert str(caught.value) == "invalid_schema: task.json"
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize(
    "change", ["invalid_schema", "invalid_example", "remote_ref", "file_ref"]
)
def test_checks_input_schema_and_training_input(task_files, tmp_path, change):
    task, tools = task_files
    public_path = task / "task.json"
    public = json.loads(public_path.read_text())
    if change == "invalid_schema":
        public["input_schema"]["type"] = "not-a-json-type"
    elif change == "invalid_example":
        public["example"]["input"]["item"] = 42
    else:
        public["input_schema"]["$defs"] = {
            "unused": {
                "$ref": "https://invalid.example/schema"
                if change == "remote_ref"
                else "file:///private/expected.json"
            }
        }
    public_path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match="invalid_schema"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("kind", ["empty_directory", "file", "symlink"])
def test_destination_conflict_preserves_callers_files(task_files, tmp_path, kind):
    task, tools = task_files
    destination = tmp_path / "public"
    if kind == "empty_directory":
        destination.mkdir()
    elif kind == "file":
        destination.write_text("CALLER-OWNED")
    else:
        target = tmp_path / "caller-target"
        target.mkdir()
        destination.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="destination_exists"):
        export_public(load_task(task, tool_contract=tools), destination)
    if kind == "empty_directory":
        assert list(destination.iterdir()) == []
    elif kind == "file":
        assert destination.read_text() == "CALLER-OWNED"
    else:
        assert destination.is_symlink()
        assert list(target.iterdir()) == []
    assert not list(tmp_path.glob(".wb-public-*"))


@pytest.mark.parametrize(
    "relative",
    ["instruction.md", "task.toml", "task.json", "tools.json", "tests/cases.json"],
)
def test_missing_materials_have_safe_errors(task_files, tmp_path, relative):
    task, tools = task_files
    path = tools if relative == "tools.json" else task / relative
    path.unlink()
    with pytest.raises(ValueError, match="missing") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert str(task) not in str(caught.value)
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "other"),
        ("app_image", "other:fixture"),
        ("schema_version", "99.0"),
        ("expected", "PRIVATE-TOOL-VALUE"),
    ],
)
def test_tool_contract_matches_selected_profile(task_files, tmp_path, field, value):
    task, tools = task_files
    contract = json.loads(tools.read_text())
    contract[field] = value
    tools.write_text(json.dumps(contract))
    expected = (
        "profile_mismatch" if field in {"profile", "app_image"} else "invalid_schema"
    )
    with pytest.raises(ValueError, match=expected):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize(
    "value",
    [
        "wb_public = 7",
        'wb_public = ""',
        'wb_public = ["task.json"]',
        "wb_public = false",
        'other_public = "task.json"',
        'wb_public = "PRIVATE-NATIVE-VALUE"\nwb_public = "task.json"',
    ],
)
def test_invalid_native_config_is_sanitized(task_files, tmp_path, value):
    task, tools = task_files
    config = task / "task.toml"
    config.write_text(config.read_text().replace('wb_public = "task.json"', value))
    with pytest.raises(ValueError, match="invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert "PRIVATE-NATIVE-VALUE" not in str(caught.value)
    assert str(task) not in str(caught.value)


def test_second_task_loads_by_path_without_registration(
    task_files, tmp_path, monkeypatch
):
    task, tools = task_files
    second = tmp_path / "another-business-task"
    task.rename(second)
    (second / "instruction.md").write_text("Inspect the requested batch.\n")
    public = {
        "input_schema": {
            "type": "object",
            "properties": {"batch": {"type": "integer"}},
            "required": ["batch"],
        },
        "example": {"input": {"batch": 17}, "state": {"batches": [17, 18]}},
        "feedback": {"criterion_ids": ["inspection"], "private_values": False},
    }
    (second / "task.json").write_text(json.dumps(public))
    (second / "task.toml").write_text(
        (second / "task.toml").read_text().replace('"reserve"', '"inspect"')
    )
    contract = json.loads(tools.read_text())
    contract["profile"] = "inspect"
    contract["tools"][0]["name"] = "inspect"
    contract["tools"][0]["arguments_schema"] = public["input_schema"]
    tools.write_text(json.dumps(contract))
    monkeypatch.chdir(tmp_path)
    package = export_public(load_task(second, tool_contract=tools), tmp_path / "public")
    assert (
        json.loads((package.root / "task.json").read_text())["example"]
        == public["example"]
    )
    assert (
        package.root / "instruction.md"
    ).read_text() == "Inspect the requested batch.\n"


def test_write_failure_leaves_no_partial_package(task_files, tmp_path, monkeypatch):
    task, tools = task_files
    materials = load_task(task, tool_contract=tools)
    real_write = Path.write_bytes

    def failing_write(path, data):
        if path.name == "tools.json":
            raise OSError("PRIVATE-OS-DETAIL")
        return real_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", failing_write)
    with pytest.raises(ValueError, match="io_error") as caught:
        export_public(materials, tmp_path / "public")
    assert "PRIVATE-OS-DETAIL" not in str(caught.value)
    assert not (tmp_path / "public").exists()
    assert not list(tmp_path.glob(".wb-public-*"))
    assert (task / "instruction.md").read_text() == "Reserve the requested item.\n"


@pytest.mark.parametrize(
    "relative", ["task.json", "tools.json", "instruction.md", "task.toml"]
)
def test_oversized_materials_rejected_before_parsing(task_files, tmp_path, relative):
    task, tools = task_files
    path = tools if relative == "tools.json" else task / relative
    with path.open("ab") as stream:
        stream.write(b" " * (4 * 1024 * 1024))
    with pytest.raises(ValueError, match="invalid_schema"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("part", ["task", "tools", "destination"])
def test_internal_interfaces_require_absolute_paths(
    task_files, tmp_path, monkeypatch, part
):
    task, tools = task_files
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="unsafe_path"):
        materials = load_task(
            Path(task.name) if part == "task" else task,
            tool_contract=Path(tools.name) if part == "tools" else tools,
        )
        export_public(
            materials, Path("public") if part == "destination" else tmp_path / "public"
        )
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("change", ["invalid_type", "remote_ref", "duplicate_tool"])
def test_rejects_invalid_tool_schemas(task_files, tmp_path, change):
    task, tools = task_files
    contract = json.loads(tools.read_text())
    if change == "invalid_type":
        contract["tools"][0]["result_schema"] = {"type": "invalid"}
    elif change == "remote_ref":
        contract["tools"][0]["arguments_schema"] = {
            "$ref": "https://invalid.example/tools"
        }
    else:
        contract["tools"].append(contract["tools"][0])
    tools.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="invalid_schema"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")


@pytest.mark.parametrize("relative", ["tests/test.sh", "instruction.md"])
def test_native_task_errors_do_not_expose_host_values(task_files, tmp_path, relative):
    task, tools = task_files
    if relative == "instruction.md":
        (task / relative).write_bytes(b"\xffPRIVATE-INSTRUCTION")
    else:
        (task / relative).unlink()
    with pytest.raises(ValueError, match="missing|invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert str(task) not in str(caught.value)
    assert "PRIVATE-INSTRUCTION" not in str(caught.value)


@pytest.mark.parametrize(
    "reference", ["AGENTS.md", ".env", "public/.private/task.json"]
)
def test_public_reference_cannot_reclassify_service_files(
    task_files, tmp_path, reference
):
    task, tools = task_files
    path = task / reference
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((task / "task.json").read_bytes())
    config = task / "task.toml"
    config.write_text(
        config.read_text().replace(
            'wb_public = "task.json"', f'wb_public = "{reference}"'
        )
    )
    with pytest.raises(ValueError, match="unsafe_path"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")


@pytest.mark.parametrize("field", ["input_schema", "example", "feedback"])
def test_required_public_data_cannot_be_omitted(task_files, tmp_path, field):
    task, tools = task_files
    path = task / "task.json"
    public = json.loads(path.read_text())
    del public[field]
    path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match="invalid_schema"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")


def test_embedded_local_schema_references_work(task_files, tmp_path):
    task, tools = task_files
    path = task / "task.json"
    public = json.loads(path.read_text())
    public["input_schema"]["$defs"] = {"item": {"type": "string"}}
    public["input_schema"]["properties"]["item"] = {"$ref": "#/$defs/item"}
    path.write_text(json.dumps(public))
    package = export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert json.loads((package.root / "task.json").read_text())["example"]["input"] == {
        "item": "book"
    }


@pytest.mark.parametrize("kind", ["directory", "fifo", "parent_symlink"])
def test_nonregular_and_indirect_materials_are_rejected(task_files, tmp_path, kind):
    import os

    task, tools = task_files
    path = task / "task.json"
    if kind == "parent_symlink":
        public_dir = tmp_path / "outside-public"
        public_dir.mkdir()
        (public_dir / "task.json").write_bytes(path.read_bytes())
        (task / "public").symlink_to(public_dir, target_is_directory=True)
        config = task / "task.toml"
        config.write_text(
            config.read_text().replace(
                'wb_public = "task.json"', 'wb_public = "public/task.json"'
            )
        )
    else:
        path.unlink()
        if kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path)
    with pytest.raises(ValueError, match="unsafe_path"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")


@pytest.mark.parametrize(
    "schema",
    [{"$schema": "https://invalid.example/draft"}, {"$ref": "#/$defs/missing"}],
)
def test_schema_reference_errors_are_sanitized(task_files, tmp_path, schema):
    task, tools = task_files
    path = task / "task.json"
    public = json.loads(path.read_text())
    public["input_schema"] = schema
    path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match="invalid_schema"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")


def test_json_string_values_roundtrip_in_public_state(task_files, tmp_path):
    task, tools = task_files
    path = task / "task.json"
    public = json.loads(path.read_text())
    public["example"]["state"] = {"text": "Учебный пример", "escaped": "\ud800"}
    path.write_text(json.dumps(public))
    package = export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert json.loads((package.root / "task.json").read_text())["example"]["state"] == {
        "text": "Учебный пример",
        "escaped": "\ud800",
    }


@pytest.mark.parametrize("private_key", ["wb_cases", "wb_rubric"])
def test_private_metadata_cannot_alias_public_instruction(
    task_files, tmp_path, private_key
):
    task, tools = task_files
    config = task / "task.toml"
    original = "tests/cases.json" if private_key == "wb_cases" else "tests/rubric.json"
    config.write_text(
        config.read_text().replace(
            f'{private_key} = "{original}"', f'{private_key} = "instruction.md"'
        )
    )
    (task / "instruction.md").write_text("PRIVATE-INSTRUCTION-ALIAS")
    with pytest.raises(ValueError, match="unsafe_path"):
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert not (tmp_path / "public").exists()


def test_deep_native_metadata_has_safe_error(task_files, tmp_path):
    task, tools = task_files
    config = task / "task.toml"
    nested = "[" * 1500 + '"PRIVATE-DEEP-VALUE"' + "]" * 1500
    config.write_text(
        config.read_text().replace("[metadata]\n", f"[metadata]\ndeep = {nested}\n")
    )
    with pytest.raises(ValueError, match="invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert str(caught.value) == "invalid_schema: task.toml"
    assert not (tmp_path / "public").exists()


@pytest.mark.parametrize("target", ["#/$defs/missing", "#/title"])
def test_tool_schema_references_must_resolve_to_schemas(task_files, tmp_path, target):
    task, tools = task_files
    contract = json.loads(tools.read_text())
    contract["tools"][0]["result_schema"] = {
        "title": "PRIVATE-REF-VALUE",
        "$ref": target,
    }
    tools.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert str(caught.value) == "invalid_schema: tools.json"
    assert not (tmp_path / "public").exists()


def test_handoff_names_existing_public_materials(task_files, tmp_path):
    task, tools = task_files
    instruction = "Reserve {item} from the training stock.\n"
    (task / "instruction.md").write_text(instruction)
    package = export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    handoff = (package.root / "composer.md").read_text()
    for name in ("instruction.md", "task.json", "tools.json", "workflow.md"):
        assert name in handoff
        assert (package.root / name).is_file()
    assert "Submit workflow.json" in handoff
    assert "workflow.schema.json" in (package.root / "workflow.md").read_text()
    assert (package.root / "instruction.md").read_text() == instruction


@pytest.mark.parametrize(
    "reference", ["file:///private/expected.json", "#/$defs/missing"]
)
def test_indirect_tool_schema_references_are_checked(task_files, tmp_path, reference):
    task, tools = task_files
    contract = json.loads(tools.read_text())
    contract["tools"][0]["result_schema"] = {
        "extra": {"$ref": reference},
        "$ref": "#/extra",
    }
    tools.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="invalid_schema") as caught:
        export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert str(caught.value) == "invalid_schema: tools.json"
    assert not (tmp_path / "public").exists()


def test_recursive_local_tool_schema_is_accepted(task_files, tmp_path):
    task, tools = task_files
    contract = json.loads(tools.read_text())
    schema = {
        "extra": {"type": "object", "properties": {"next": {"$ref": "#/extra"}}},
        "$ref": "#/extra",
    }
    contract["tools"][0]["result_schema"] = schema
    tools.write_text(json.dumps(contract))
    package = export_public(load_task(task, tool_contract=tools), tmp_path / "public")
    assert (
        json.loads((package.root / "tools.json").read_text())["tools"][0][
            "result_schema"
        ]
        == schema
    )
