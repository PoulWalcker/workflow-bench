"""Bounded callers share strict JSON decoding and local schema validation."""

import json
import math
import stat
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.protocols import Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable
from referencing.jsonschema import DRAFT202012

from workflow_bench.contracts import JsonValue

_DRAFT_URI = "https://json-schema.org/draft/2020-12/schema"


class DataError(ValueError):
    """Safe code and relative reference, without source data."""

    def __init__(self, code: str, relative_path: str) -> None:
        self.code = str(code)
        self.relative_path = relative_path
        super().__init__(f"{code}: {relative_path}")


def _unique_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite_number")
    return number


def _reject_constant(value: str) -> JsonValue:
    raise ValueError("nonfinite_number")


def decode_json(content: bytes, relative_path: str) -> JsonValue:
    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (ValueError, RecursionError):
        raise DataError("invalid_schema", relative_path) from None


def _no_remote(uri: str) -> Resource:
    raise NoSuchResource(ref=uri)


def schema_validator(
    schema: dict[str, JsonValue] | bool, relative_path: str
) -> Validator:
    try:
        Draft202012Validator.check_schema(schema)
        root = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = Registry(retrieve=_no_remote)
        pending = [(root, registry.resolver_with_root(root))]
        visited = set()
        while pending:
            resource, resolver = pending.pop()
            contents = resource.contents
            if id(contents) in visited:
                continue
            visited.add(id(contents))
            if isinstance(contents, dict):
                if contents.get("$schema", _DRAFT_URI) != _DRAFT_URI:
                    raise ValueError("unsupported_draft")
                for keyword in ("$ref", "$dynamicRef"):
                    if keyword in contents:
                        reference = contents[keyword]
                        if not reference.startswith("#"):
                            raise ValueError("nonlocal_ref")
                        resolved = resolver.lookup(reference)
                        Draft202012Validator.check_schema(resolved.contents)
                        # A reference may target a schema under an extension keyword.
                        pending.append(
                            (
                                Resource.from_contents(
                                    resolved.contents, default_specification=DRAFT202012
                                ),
                                resolved.resolver,
                            )
                        )
            pending.extend(
                (child, resolver.in_subresource(child))
                for child in resource.subresources()
            )
        return Draft202012Validator(schema, registry=registry)
    except (SchemaError, ValidationError, Unresolvable, ValueError, RecursionError):
        raise DataError("invalid_schema", relative_path) from None


def validate_json(
    data: JsonValue, schema: dict[str, JsonValue] | bool, relative_path: str
) -> None:
    """Validate data against a local schema; failures raise a safe DataError."""
    validator = schema_validator(schema, relative_path)
    try:
        validator.validate(data)
    except (ValidationError, Unresolvable, RecursionError):
        raise DataError("invalid_schema", relative_path) from None


def resource_schema(name: str) -> dict[str, JsonValue]:
    """Return a JSON Schema packaged with this distribution."""
    return json.loads(files("workflow_bench").joinpath("resources", name).read_bytes())


MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024


def read_bytes(path: Path, label: str, *, limit: int = MAX_JSON_BYTES) -> bytes:
    """Read a bounded regular trusted input; reject symlinks and invalid JSON."""
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise DataError("unsafe_file", label)
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise DataError("too_large", label)
    return content


def read_json(path: Path, label: str) -> JsonValue:
    return decode_json(read_bytes(path, label), label)


def validate_contract(name: str, data: JsonValue) -> None:
    schema = resource_schema("wire.schema.json")
    validate_json(data, {**schema, "$ref": f"#/$defs/{name}"}, name)
