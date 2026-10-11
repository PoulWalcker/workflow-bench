"""Load a native Task and export only its explicitly public materials."""

import hashlib
import json
import stat
import tempfile
from enum import StrEnum
from importlib.resources import files
from pathlib import Path

from harbor.models.task.config import TaskConfig
from harbor.models.task.task import Task

from workflow_bench.contracts import (
    PUBLIC_PACKAGE_FILES,
    WORKFLOW_ARTIFACT_FILE,
    CaseData,
    JsonValue,
    PublicPackage,
    TaskMaterials,
)
from workflow_bench.data import (
    MAX_JSON_BYTES,
    read_bytes,
)
from workflow_bench.data import (
    DataError as DefinitionError,
)
from workflow_bench.data import (
    decode_json as _decode,
)
from workflow_bench.data import (
    resource_schema as _schema,
)
from workflow_bench.data import (
    schema_validator as _validator,
)
from workflow_bench.data import (
    validate_json as _validate,
)

MAX_MATERIAL_BYTES = MAX_JSON_BYTES


def load_cases(
    materials: TaskMaterials, case_ids: tuple[str, ...]
) -> tuple[CaseData, ...]:
    """Select fresh cases; state and expectations remain opaque to core."""
    path = materials.private_paths[0]
    document = _decode(_read(path, "cases"), "cases")
    _validate(document, _schema("cases.schema.json"), "cases")
    by_id = {case["id"]: case for case in document["cases"]}
    if (
        len(by_id) != len(document["cases"])
        or not case_ids
        or len(set(case_ids)) != len(case_ids)
    ):
        raise DefinitionError(DefinitionErrorCode.INVALID_SCHEMA, "cases")
    if not set(case_ids) <= set(by_id):
        raise DefinitionError(DefinitionErrorCode.MISSING_CASE, "cases")
    result = []
    for case_id in case_ids:
        case = by_id[case_id]
        _validate(case["input"], materials.public_data["input_schema"], "case.input")
        result.append(CaseData(case_id, case["input"], case["state"], case["expected"]))
    return tuple(result)


class DefinitionErrorCode(StrEnum):
    MISSING = "missing"
    INVALID_SCHEMA = "invalid_schema"
    UNSAFE_PATH = "unsafe_path"
    PROFILE_MISMATCH = "profile_mismatch"
    DESTINATION_EXISTS = "destination_exists"
    IO_ERROR = "io_error"
    MISSING_CASE = "missing_case"


def _absolute_path(path: Path, label: str) -> None:
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise DefinitionError(DefinitionErrorCode.UNSAFE_PATH, label)


def _regular_file(path: Path, label: str) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise DefinitionError(DefinitionErrorCode.UNSAFE_PATH, label)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            raise DefinitionError(DefinitionErrorCode.UNSAFE_PATH, label)
    except FileNotFoundError:
        raise DefinitionError(DefinitionErrorCode.MISSING, label) from None
    except OSError:
        raise DefinitionError(DefinitionErrorCode.IO_ERROR, label) from None


def _read(path: Path, label: str) -> bytes:
    _regular_file(path, label)
    try:
        return read_bytes(path, label, limit=MAX_MATERIAL_BYTES)
    except DefinitionError as error:
        code = (
            DefinitionErrorCode.INVALID_SCHEMA
            if error.code == "too_large"
            else DefinitionErrorCode.UNSAFE_PATH
        )
        raise DefinitionError(code, label) from None
    except FileNotFoundError:
        raise DefinitionError(DefinitionErrorCode.MISSING, label) from None
    except OSError:
        raise DefinitionError(DefinitionErrorCode.IO_ERROR, label) from None


def _text(content: bytes, label: str) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeError:
        raise DefinitionError(DefinitionErrorCode.INVALID_SCHEMA, label) from None


def _task_path(root: Path, reference: str, label: str) -> Path:
    path = Path(reference)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or "\x00" in reference
    ):
        raise DefinitionError(DefinitionErrorCode.UNSAFE_PATH, label)
    return root / path


def _public_reference(
    root: Path, path: Path, private_paths: tuple[Path, ...], label: str
) -> None:
    relative = path.relative_to(root)
    reserved = {
        "tests",
        "solution",
        "environment",
        "credentials",
        "docs",
        "AGENTS.md",
        "CLAUDE.md",
        "Principles.md",
        "GLOSSARY.md",
        "SPEC.md",
        "ARCHITECTURE.md",
        "ROADMAP.md",
        "README.md",
        "task.toml",
    }
    if any(part.startswith(".") or part in reserved for part in relative.parts) or any(
        path == private or path.is_relative_to(private) for private in private_paths
    ):
        raise DefinitionError(DefinitionErrorCode.UNSAFE_PATH, label)


def _load_public_data(content: bytes) -> dict[str, JsonValue]:
    reference = PUBLIC_PACKAGE_FILES["task"]
    data = _decode(content, reference)
    _validate(data, _schema("task.schema.json"), reference)
    _validate(data["example"]["input"], data["input_schema"], reference)
    return data


def _load_tool_contract(
    content: bytes, *, app_image: str, profile: str
) -> dict[str, JsonValue]:
    reference = PUBLIC_PACKAGE_FILES["tools"]
    tools = _decode(content, reference)
    _validate(tools, _schema("tools.schema.json"), reference)
    names = set()
    for tool in tools["tools"]:
        if tool["name"] in names:
            raise DefinitionError(DefinitionErrorCode.INVALID_SCHEMA, reference)
        names.add(tool["name"])
        for keyword in ("arguments_schema", "result_schema"):
            _validator(tool[keyword], reference)
    if tools["app_image"] != app_image or tools["profile"] != profile:
        raise DefinitionError(DefinitionErrorCode.PROFILE_MISMATCH, reference)
    return tools


def load_task(task_path: Path, *, tool_contract: Path) -> TaskMaterials:
    """Load a single-step native Task on the trusted host, without a Trial.

    Paths must be absolute. Task files must remain stable during the call.
    Only instruction, public JSON and the explicitly supplied tool contract are
    read as content; cases/rubric paths are checked, not decoded. Tools envelope
    1.0 must match metadata's app image and profile. Embedded schemas use Draft
    2020-12 and local fragment references only. Each read is bounded to 4 MiB.
    Returned JSON trees are owned snapshots and must not be mutated by callers.
    DefinitionError carries a safe code and material reference.
    """
    _absolute_path(task_path, "task")
    _absolute_path(tool_contract, PUBLIC_PACKAGE_FILES["tools"])
    config_bytes = _read(task_path / "task.toml", "task.toml")
    instruction_bytes = _read(
        task_path / PUBLIC_PACKAGE_FILES["instruction"],
        PUBLIC_PACKAGE_FILES["instruction"],
    )
    try:
        config = TaskConfig.model_validate_toml(_text(config_bytes, "task.toml"))
    except (ValueError, RecursionError):
        raise DefinitionError(DefinitionErrorCode.INVALID_SCHEMA, "task.toml") from None
    _validate(config.metadata, _schema("metadata.schema.json"), "task.toml")
    public_path = _task_path(
        task_path, config.metadata["wb_public"], "metadata.wb_public"
    )
    private_references = {
        key: _task_path(task_path, config.metadata[key], f"metadata.{key}")
        for key in ("wb_cases", "wb_rubric")
    }
    private_paths = tuple(private_references.values())
    _public_reference(
        task_path,
        task_path / PUBLIC_PACKAGE_FILES["instruction"],
        private_paths,
        PUBLIC_PACKAGE_FILES["instruction"],
    )
    _public_reference(task_path, public_path, private_paths, "metadata.wb_public")
    if tool_contract.is_relative_to(task_path):
        _public_reference(
            task_path, tool_contract, private_paths, PUBLIC_PACKAGE_FILES["tools"]
        )
    tools_bytes = _read(tool_contract, PUBLIC_PACKAGE_FILES["tools"])
    public_bytes = _read(public_path, PUBLIC_PACKAGE_FILES["task"])
    for key, path in private_references.items():
        _regular_file(path, f"metadata.{key}")
    instruction = _text(instruction_bytes, PUBLIC_PACKAGE_FILES["instruction"])
    try:
        native = Task(task_dir=task_path)
    except FileNotFoundError:
        raise DefinitionError(DefinitionErrorCode.MISSING, "native_task") from None
    except OSError:
        raise DefinitionError(DefinitionErrorCode.IO_ERROR, "native_task") from None
    except (ValueError, RuntimeError):
        raise DefinitionError(DefinitionErrorCode.UNSAFE_PATH, "native_task") from None
    public_data = _load_public_data(public_bytes)
    tools = _load_tool_contract(
        tools_bytes,
        app_image=config.metadata["wb_app_image"],
        profile=config.metadata["wb_tool_profile"],
    )
    hashes = tuple(
        (name, hashlib.sha256(content).hexdigest())
        for name, content in (
            (PUBLIC_PACKAGE_FILES["instruction"], instruction_bytes),
            ("task.toml", config_bytes),
            (PUBLIC_PACKAGE_FILES["task"], public_bytes),
            (PUBLIC_PACKAGE_FILES["tools"], tools_bytes),
        )
    )
    return TaskMaterials(native, instruction, public_data, tools, private_paths, hashes)


def export_public(materials: TaskMaterials, destination: Path) -> PublicPackage:
    """Publish the allowlisted snapshot and return relative names/SHA-256 hashes.

    Destination must be absolute, absent, with an existing parent. Caller must
    exclusively control its name during this call; concurrent publishers are
    not supported. Exporter owns only a temporary sibling until the final rename;
    caller owns the completed directory. Existing destinations are preserved.
    No source Task files are reread. Installed contracts are located independently
    of cwd. On failure only the exporter's temporary directory is cleaned up.
    """
    _absolute_path(destination, "destination")
    if destination.exists() or destination.is_symlink():
        raise DefinitionError(DefinitionErrorCode.DESTINATION_EXISTS, "destination")
    payloads = {
        PUBLIC_PACKAGE_FILES["instruction"]: materials.instruction.encode("utf-8"),
        PUBLIC_PACKAGE_FILES["task"]: json.dumps(materials.public_data).encode("utf-8"),
        PUBLIC_PACKAGE_FILES["tools"]: json.dumps(materials.tool_contract).encode(
            "utf-8"
        ),
    }
    try:
        resources = files("workflow_bench").joinpath("resources")
        for name in PUBLIC_PACKAGE_FILES.values():
            if name in payloads:
                continue
            content = resources.joinpath(name).read_bytes()
            if name.endswith(".md"):
                # Render only trusted package texts, never Task-owned instructions.
                content = (
                    content.decode("utf-8")
                    .format_map(
                        dict(PUBLIC_PACKAGE_FILES, artifact=WORKFLOW_ARTIFACT_FILE)
                    )
                    .encode("utf-8")
                )
            payloads[name] = content
        with tempfile.TemporaryDirectory(
            dir=destination.parent, prefix=".wb-public-"
        ) as tmp:
            staging = Path(tmp) / "package"
            staging.mkdir()
            for name, content in payloads.items():
                (staging / name).write_bytes(content)
            if destination.exists() or destination.is_symlink():
                raise DefinitionError(
                    DefinitionErrorCode.DESTINATION_EXISTS, "destination"
                )
            staging.rename(destination)
    except OSError:
        raise DefinitionError(DefinitionErrorCode.IO_ERROR, "destination") from None
    return PublicPackage(
        destination,
        tuple(
            (name, hashlib.sha256(content).hexdigest())
            for name, content in payloads.items()
        ),
    )
