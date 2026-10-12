"""Bounded SimsApp V1 navigation, projected from one application state."""

import asyncio
import logging
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from uuid import NAMESPACE_OID, uuid5

from jsonschema.exceptions import ValidationError

from workflow_bench.contracts import JsonValue
from workflow_bench.data import read_json, schema_validator
from workflow_bench.simulator import Simulator, ToolError, serve

ROOT = Path(__file__).resolve().parent
TOOLS = read_json(ROOT / "tools.json", "tools")
STATE_SCHEMA = read_json(ROOT / "state.schema.json", "state")


class Navigation:
    tools = TOOLS
    state_schema = STATE_SCHEMA
    evidence_version = "2.0"
    identity_contract = "control_identity"
    close_on_limit = True
    actor = "control"
    fault_modes = {"drop_response", "stall_before_commit", "incomplete_observation"}
    fault_operations = {"ui_action", "ui_observe"}

    def __init__(self) -> None:
        self.state: dict[str, JsonValue] = {}

    @staticmethod
    def check_state(state: dict[str, JsonValue]) -> None:
        conversations = {c["id"] for c in state["conversations"]}
        messages = {m["id"] for m in state["messages"]}
        ui = state["ui"]
        if (
            len(conversations) != len(state["conversations"])
            or len(messages) != len(state["messages"])
            or any(m["conversation_id"] not in conversations for m in state["messages"])
            or not set(ui["drafts"]) <= conversations
        ):
            raise ValueError()
        if ui["screen"] == "conversation":
            valid = (
                ui["active_conversation_id"] in conversations
                and ui["query"] == ""
                and ui["focus"] is None
            )
        else:
            valid = ui["active_conversation_id"] is None
            if ui["screen"] == "chat_list":
                valid = valid and ui["query"] == "" and ui["focus"] is None
        if not valid:
            raise ValueError()

    @staticmethod
    def validate_arguments(operation: str, arguments: JsonValue) -> None:
        spec = next((t for t in TOOLS["tools"] if t["name"] == operation), None)
        if spec is None:
            raise ToolError("forbidden", "ui_only_bypass")
        validator = schema_validator(spec["arguments_schema"], "arguments")
        try:
            validator.validate(arguments)
        except ValidationError as failure:
            pending = [failure]
            while pending:
                error = pending.pop()
                if error.validator == "maxLength":
                    raise ToolError("limit_exceeded") from None
                pending.extend(error.context)
            raise ToolError("invalid_arguments") from None

    @staticmethod
    def forbidden_violation(operation: str) -> str | None:
        return (
            "ui_only_bypass"
            if operation not in {t["name"] for t in TOOLS["tools"]}
            else None
        )

    def _projection(
        self, revision: int, scope: str, *, incomplete: bool = False
    ) -> tuple[
        dict[str, JsonValue],
        dict[str, tuple[dict[str, JsonValue], str | None, str | None]],
        dict[str, JsonValue],
    ]:
        ui = self.state["ui"]
        targets: dict[str, tuple[dict[str, JsonValue], str | None, str | None]] = {}

        def node(
            role: str,
            label: str,
            *,
            value: str | None = None,
            actions: Sequence[str] = (),
            enabled: bool = True,
            focused: bool = False,
            children: Sequence[dict[str, JsonValue]] = (),
            identity: dict[str, JsonValue] | None = None,
            direction: str | None = None,
            target: str | None = None,
            conversation_id: str | None = None,
        ) -> dict[str, JsonValue]:
            ref = uuid5(NAMESPACE_OID, f"{scope}:{revision}:{len(targets)}").hex
            result = {
                "ref": ref,
                "role": role,
                "label": label,
                "value": value,
                "enabled": enabled,
                "focused": focused,
                "actions": list(actions),
                "children": list(children),
            }
            if identity is not None:
                result["identity"] = identity
            if direction is not None:
                result["direction"] = direction
            targets[ref] = (result, target, conversation_id)
            return result

        children, visible_conversations, visible_messages = [], [], []
        if ui["screen"] == "chat_list":
            children.append(
                node("button", "Search", actions=["activate"], target="search")
            )
        else:
            children.append(node("button", "Back", actions=["activate"], target="back"))
        if ui["screen"] == "search":
            children.extend(
                [
                    node(
                        "textbox",
                        "Search",
                        value=ui["query"],
                        actions=["focus", "replace_text"],
                        focused=ui["focus"] == "search",
                        target="query",
                    ),
                    node(
                        "button",
                        "Clear text",
                        actions=["activate"],
                        enabled=bool(ui["query"]),
                        target="clear",
                    ),
                ]
            )
        if ui["screen"] == "conversation":
            conversation = next(
                c
                for c in self.state["conversations"]
                if c["id"] == ui["active_conversation_id"]
            )
            visible_conversations.append(conversation["id"])
            children.append(
                node(
                    "heading",
                    conversation["display_name"],
                    identity={
                        k: conversation[k] for k in ("display_name", "identity_hint")
                    },
                )
            )
            history = []
            for message in self.state["messages"]:
                if message["conversation_id"] == conversation["id"]:
                    visible_messages.append(message["id"])
                    history.append(
                        node(
                            "text",
                            "Message",
                            value=message["text"],
                            direction=message["direction"],
                        )
                    )
            children.append(node("group", "History", children=history))
        else:
            buttons = []
            for conversation in self.state["conversations"]:
                if ui["query"] in conversation["display_name"] or (
                    conversation["identity_hint"] is not None
                    and ui["query"] in conversation["identity_hint"]
                ):
                    visible_conversations.append(conversation["id"])
                    buttons.append(
                        node(
                            "button",
                            conversation["display_name"],
                            actions=["activate"],
                            identity={
                                k: conversation[k]
                                for k in ("display_name", "identity_hint")
                            },
                            target="open",
                            conversation_id=conversation["id"],
                        )
                    )
            if not buttons:
                buttons.append(
                    node(
                        "text", "No results" if ui["screen"] == "search" else "No chats"
                    )
                )
            children.append(node("group", "Chats", children=buttons))
        tree = node("group", "SimsApp", children=children)
        coverage = {
            "tree": "incomplete" if incomplete else "complete",
            "collection": {
                "kind": "history"
                if ui["screen"] == "conversation"
                else "conversations",
                "complete": not incomplete,
            },
        }
        observation = {
            "origin": "control",
            "scope": scope,
            "revision": revision,
            "screen": ui["screen"],
            "coverage": coverage,
            "tree": tree,
        }
        protected = {
            "revision": revision,
            "screen": ui["screen"],
            "query": ui["query"],
            "coverage": deepcopy(coverage),
            "visible_conversation_ids": visible_conversations,
            "visible_message_ids": visible_messages,
        }
        return observation, targets, protected

    def perform(
        self,
        operation: str,
        arguments: dict[str, JsonValue],
        revision: int,
        scope: str,
        *,
        incomplete: bool = False,
    ) -> tuple[JsonValue, str | None, dict[str, JsonValue]]:
        effect = {"status": "no_effect", "message_id": None}
        observation, targets, protected = self._projection(
            revision, scope, incomplete=incomplete
        )
        if operation == "ui_observe":
            effect["observation"] = protected
            return observation, None, effect
        locator = arguments["locator"]
        error = None
        if locator["scope"] != scope or locator["revision"] != revision:
            error = "stale_locator"
        elif locator["ref"] not in targets:
            error = "target_unavailable"
        else:
            element, target, conversation_id = targets[locator["ref"]]
            if not element["enabled"]:
                error = "disabled"
            elif arguments["action"] not in element["actions"]:
                error = "unsupported_action"
            elif arguments["action"] == "replace_text" and not element["focused"]:
                error = "not_focused"
        if error:
            return None, error, effect
        ui = self.state["ui"]
        previous = dict(ui)
        if arguments["action"] == "focus":
            ui["focus"] = "search"
        elif arguments["action"] == "replace_text":
            ui["query"] = arguments["text"]
        elif target == "clear":
            ui["query"] = ""
        elif target == "search":
            ui["screen"] = "search"
        elif target == "back":
            ui.update(
                screen="chat_list", active_conversation_id=None, query="", focus=None
            )
        elif target == "open":
            ui.update(
                screen="conversation",
                active_conversation_id=conversation_id,
                query="",
                focus=None,
            )
        changes = [
            {"path": "/ui/" + key, "before": previous[key], "after": ui[key]}
            for key in ui
            if previous[key] != ui[key]
        ]
        if changes:
            effect.update(
                status="committed",
                transition={
                    "from_revision": revision,
                    "to_revision": revision + 1,
                    "changes": changes,
                },
            )
        return (
            {"status": effect["status"], "revision": revision + bool(changes)},
            None,
            effect,
        )


def SimsApp(control_key: str) -> Simulator:
    return Simulator(control_key, Navigation())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(Navigation()))
