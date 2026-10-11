"""Checked host-side exchange values; nested JSON trees must not be mutated."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from harbor.models.task.task import Task

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)

# Fixed protocol roles, shared by loading, exporting and public text templates.
PUBLIC_PACKAGE_FILES: Mapping[str, str] = MappingProxyType(
    {
        "instruction": "instruction.md",
        "task": "task.json",
        "tools": "tools.json",
        "workflow_contract": "workflow.md",
        "workflow_schema": "workflow.schema.json",
        "composer": "composer.md",
    }
)
WORKFLOW_ARTIFACT_FILE = "workflow.json"


@dataclass(frozen=True)
class TaskMaterials:
    native_task: Task
    instruction: str
    public_data: dict[str, JsonValue]
    tool_contract: dict[str, JsonValue]
    private_paths: tuple[Path, ...]
    hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PublicPackage:
    root: Path
    files: tuple[tuple[str, str], ...]
