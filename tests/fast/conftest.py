import json
import shutil
from pathlib import Path

import pytest


@pytest.fixture
def config_data() -> dict:
    return {
        "app_image": "sha256:" + "a" * 64,
        "n8n_image": "sha256:" + "b" * 64,
        "runner_image": "sha256:" + "c" * 64,
        "setup_timeout_sec": 90,
        "submission_timeout_sec": 20,
        "execute_timeout_sec": 45,
        "tool_timeout_sec": 5,
        "control_timeout_sec": 10,
        "drain_timeout_sec": 10,
        "verifier_timeout_sec": 30,
        "cleanup_timeout_sec": 25,
        "total_timeout_sec": 360,
        "cpus": 1,
        "memory_mb": 1024,
        "max_calls": 8,
        "tools_port": 8080,
        "control_port": 8081,
        "broker_port": 5679,
    }


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


@pytest.fixture
def workflow_file(tmp_path: Path) -> Path:
    """Independent native fixture with Code and HTTP nodes for profile checks."""
    workflow = {
        "id": "syntheticReserve",
        "name": "Synthetic reservation",
        "nodes": [
            {
                "id": "start",
                "name": "Start",
                "type": "n8n-nodes-base.manualTrigger",
                "typeVersion": 1,
                "parameters": {},
                "position": [0, 0],
            },
            {
                "id": "input",
                "name": "BenchInput",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "parameters": {
                    "assignments": {
                        "assignments": [
                            {
                                "id": "bench",
                                "name": "bench",
                                "type": "object",
                                "value": '{"input":{},"tools":{}}',
                            }
                        ]
                    },
                    "options": {},
                },
                "position": [200, 0],
            },
            {
                "id": "prepare",
                "name": "Prepare reservation",
                "type": "n8n-nodes-base.code",
                "typeVersion": 2,
                "parameters": {
                    "mode": "runOnceForAllItems",
                    "language": "javaScript",
                    "jsCode": "return [{json: {schema_version: '1.0', "
                    "arguments: $input.first().json.bench.input}}];",
                },
                "position": [400, 0],
            },
            {
                "id": "reserve",
                "name": "Reserve item",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4.2,
                "parameters": {
                    "method": "POST",
                    "url": "={{$('BenchInput').first().json.bench.tools.base_url "
                    "+ '/tools/reserve'}}",
                    "sendHeaders": True,
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "Authorization",
                                "value": "={{'Bearer ' + $('BenchInput').first()"
                                ".json.bench.tools.capability}}",
                            }
                        ]
                    },
                    "sendBody": True,
                    "specifyBody": "json",
                    "jsonBody": "={{JSON.stringify($json)}}",
                    "options": {
                        "timeout": 5000,
                        "response": {"response": {"responseFormat": "json"}},
                    },
                },
                "position": [600, 0],
            },
            {
                "id": "result",
                "name": "BenchResult",
                "type": "n8n-nodes-base.set",
                "typeVersion": 3.4,
                "parameters": {
                    "assignments": {
                        "assignments": [
                            {
                                "id": "status",
                                "name": "status",
                                "type": "string",
                                "value": "completed",
                            },
                            {
                                "id": "reason",
                                "name": "reason_code",
                                "type": "string",
                                "value": "",
                            },
                            {
                                "id": "result",
                                "name": "result",
                                "type": "object",
                                "value": "={{$json}}",
                            },
                        ]
                    },
                    "options": {},
                },
                "position": [800, 0],
            },
        ],
        "connections": {
            source: {"main": [[{"node": target, "type": "main", "index": 0}]]}
            for source, target in (
                ("Start", "BenchInput"),
                ("BenchInput", "Prepare reservation"),
                ("Prepare reservation", "Reserve item"),
                ("Reserve item", "BenchResult"),
            )
        },
        "settings": {"executionOrder": "v1"},
    }
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow))
    return path


@pytest.fixture
def rubric_data() -> dict:
    return {
        "scoring_policy": {
            "version": "case-pass-v1",
            "case_count": 5,
            "points_per_pass": 2,
            "critical_cap": 3,
            "critical_codes": ["unexpected_reservation", "repeated_reservation"],
        },
        "success_policy": "all-required-v1",
        "criteria": [{"id": "reservation", "required": True}],
    }


@pytest.fixture
def native_task_files(task_files, workflow_file, rubric_data) -> tuple[Path, Path]:
    """Complete the existing Definition fixture for generic Experiment tests."""
    task, tools = task_files
    (task / "tests/cases.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "purpose": "development",
                "cases": [
                    {
                        "id": case_id,
                        "input": {"item": item},
                        "state": {"stock": [item]},
                        "expected": {"reserved": item},
                    }
                    for case_id, item in (
                        ("fresh", "pen"),
                        ("second", "pencil"),
                        ("third", "notebook"),
                        ("fourth", "ruler"),
                        ("fifth", "eraser"),
                    )
                ],
            }
        )
    )
    (task / "tests/rubric.json").write_text(json.dumps(rubric_data))
    shutil.copyfile(workflow_file, task / "solution/workflow.json")
    return task, tools
