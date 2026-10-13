import json
from pathlib import Path

import pytest


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
