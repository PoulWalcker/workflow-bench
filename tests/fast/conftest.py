import json
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
def public_tools_file(tmp_path: Path) -> Path:
    arguments_schema = {
        "type": "object",
        "properties": {"item": {"type": "string"}},
        "required": ["item"],
        "additionalProperties": False,
    }
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
                        "arguments_schema": arguments_schema,
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
    return tools
