"""Fast checks of bounded reads, strict JSON, and packaged schemas."""

from pathlib import Path

import pytest

from workflow_bench.contracts import JsonValue
from workflow_bench.data import (
    DataError,
    decode_json,
    read_bytes,
    resource_schema,
    validate_json,
)


def test_decode_json_returns_utf8_document() -> None:
    assert decode_json('{"name":"café"}'.encode(), "input.json") == {"name": "café"}


@pytest.mark.parametrize(
    "content",
    [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":1e999}', b"\xff"],
    ids=["duplicate-key", "nonfinite-constant", "nonfinite-float", "invalid-utf8"],
)
def test_decode_json_rejects_untrusted_content(content: bytes) -> None:
    with pytest.raises(DataError) as error:
        decode_json(content, "input.json")

    assert (error.value.code, error.value.relative_path) == (
        "invalid_schema",
        "input.json",
    )


def test_read_bytes_accepts_file_at_limit(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_bytes(b"1234")

    assert read_bytes(path, "input.json", limit=4) == b"1234"


def test_read_bytes_rejects_oversize_file(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_bytes(b"12345")

    with pytest.raises(DataError) as error:
        read_bytes(path, "input.json", limit=4)

    assert (error.value.code, error.value.relative_path) == ("too_large", "input.json")


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_read_bytes_rejects_nonregular_input(tmp_path: Path, kind: str) -> None:
    path = tmp_path / "input.json"
    if kind == "symlink":
        target = tmp_path / "target.json"
        target.write_bytes(b"{}")
        path.symlink_to(target)
    else:
        path.mkdir()

    with pytest.raises(DataError) as error:
        read_bytes(path, "input.json")

    assert (error.value.code, error.value.relative_path) == (
        "unsafe_file",
        "input.json",
    )


def test_validate_json_resolves_local_schema_reference() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"value": {"$ref": "#/$defs/positive"}},
        "required": ["value"],
        "$defs": {"positive": {"type": "integer", "minimum": 1}},
    }

    validate_json({"value": 2}, schema, "answer.json")
    with pytest.raises(DataError, match="^invalid_schema: answer.json$"):
        validate_json({"value": 0}, schema, "answer.json")


def test_validate_json_rejects_remote_schema_reference() -> None:
    with pytest.raises(DataError, match="^invalid_schema: answer.json$"):
        validate_json({}, {"$ref": "https://example.invalid/schema"}, "answer.json")


def test_resource_schema_loads_packaged_wire_contract() -> None:
    schema = resource_schema("wire.schema.json")

    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    assert "evaluation" in definitions
