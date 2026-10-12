"""Checked host-side exchange values; nested JSON trees must not be mutated."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
SUBMISSION_TRIAL_PREFIX = "wb-submission-"
REPLAY_PROJECT_PREFIX = "wb-replay-"
CONTROL_PROJECT_PREFIX = "wb-control-"
PROFILE_PROJECT_PREFIX = "wb-profile-"


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


@dataclass(frozen=True)
class WorkflowArtifact:
    path: Path
    sha256: str
    size_bytes: int
    document: dict[str, JsonValue]


@dataclass(frozen=True)
class BoundWorkflow:
    path: Path
    source_hash: str
    bound_hash: str
    replacements: tuple[str, ...]


@dataclass(frozen=True)
class E1Config:
    output_root: Path
    app_image: str
    n8n_image: str
    runner_image: str
    setup_timeout_sec: float
    submission_timeout_sec: float
    execute_timeout_sec: float
    tool_timeout_sec: float
    control_timeout_sec: float
    drain_timeout_sec: float
    verifier_timeout_sec: float
    cleanup_timeout_sec: float
    total_timeout_sec: float
    cpus: int
    memory_mb: int
    max_calls: int
    tools_port: int
    control_port: int
    broker_port: int


@dataclass(frozen=True)
class CaseData:
    id: str
    input: JsonValue
    state: JsonValue
    expected: JsonValue
