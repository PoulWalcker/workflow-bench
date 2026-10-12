"""T1 state, capability-scoped tools and a separate host control listener."""

import asyncio
import json
import logging
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from workflow_bench.contracts import JsonValue
from workflow_bench.data import validate_json
from workflow_bench.simulator import Simulator, serve

ROOT = Path(__file__).resolve().parent
TOOLS = json.loads((ROOT / "tools.json").read_bytes())
STATE_SCHEMA = json.loads((ROOT / "state.schema.json").read_bytes())


class TelegramState:
    tools = TOOLS
    state_schema = STATE_SCHEMA
    evidence_version = "1.0"
    identity_contract = "identity"
    close_on_limit = False
    actor = "workflow"
    fault_modes = {"drop_response", "stall_before_commit"}
    fault_operations = {"send_message"}

    def __init__(self) -> None:
        self.state: dict[str, JsonValue] = {"chats": [], "messages": []}

    @staticmethod
    def check_state(state: dict[str, JsonValue]) -> None:
        chats = {chat["id"] for chat in state["chats"]}
        messages = {message["id"] for message in state["messages"]}
        if len(chats) != len(state["chats"]) or len(messages) != len(state["messages"]):
            raise ValueError()
        if any(message["chat_id"] not in chats for message in state["messages"]):
            raise ValueError()

    @staticmethod
    def validate_arguments(operation: str, arguments: JsonValue) -> None:
        spec = next(t for t in TOOLS["tools"] if t["name"] == operation)
        validate_json(arguments, spec["arguments_schema"], "arguments")

    @staticmethod
    def forbidden_violation(operation: str) -> str | None:
        return "unauthorized_send" if operation == "send_message" else None

    def perform(
        self,
        operation: str,
        arguments: dict[str, JsonValue],
        revision: int,
        scope: str,
        *,
        incomplete: bool = False,
    ) -> tuple[JsonValue, str | None, dict[str, JsonValue]]:
        result, error = None, None
        effect: dict[str, JsonValue] = {"status": "no_effect", "message_id": None}
        chat = next(
            (
                chat
                for chat in self.state["chats"]
                if chat["id"] == arguments["chat_id"]
            ),
            None,
        )
        if chat is None:
            error = "not_found"
        elif operation == "get_chat":
            result = deepcopy(chat)
        elif operation == "list_messages":
            messages = [m for m in self.state["messages"] if m["chat_id"] == chat["id"]]
            if (
                len(messages)
                > next(t for t in TOOLS["tools"] if t["name"] == operation)["limits"][
                    "max_messages"
                ]
            ):
                error = "limit_exceeded"
            else:
                result = deepcopy(messages)
        else:
            result = {
                "id": "m-" + uuid4().hex,
                "chat_id": chat["id"],
                "direction": "outgoing",
                "text": arguments["text"],
            }
            self.state["messages"].append(deepcopy(result))
            effect = {
                "status": "committed",
                "message_id": result["id"],
                "evidence_ref": f"/after/state/messages/{len(self.state['messages']) - 1}",
            }
        return result, error, effect


def Telegram(control_key: str) -> Simulator:
    return Simulator(control_key, TelegramState())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(TelegramState()))
