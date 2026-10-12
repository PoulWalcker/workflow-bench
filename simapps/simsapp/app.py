"""Bounded SimsApp V1 navigation, projected from one application state."""

import asyncio
import logging
from copy import deepcopy
from pathlib import Path
from uuid import NAMESPACE_OID, uuid4, uuid5

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
                and ui["focus"] in {None, "composer"}
            )
        else:
            valid = ui["active_conversation_id"] is None
            if ui["screen"] == "chat_list":
                valid = valid and ui["query"] == "" and ui["focus"] is None
            else:
                valid = valid and ui["focus"] in {None, "search"}
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

        candidates = [
            conversation
            for conversation in self.state["conversations"]
            if ui["query"] in conversation["display_name"]
            or (
                conversation["identity_hint"] is not None
                and ui["query"] in conversation["identity_hint"]
            )
        ]
        template = "chat-list"
        if ui["screen"] == "conversation":
            template = "conversation"
        elif ui["screen"] == "search":
            template = (
                "search-focused"
                if not ui["query"]
                else "results-many"
                if candidates
                else "results-zero"
            )
        captured = read_json(
            ROOT / "fixtures/trees" / f"{template}.json", "ax_template"
        )
        tree = captured["tree"]
        visible_conversations, visible_messages = [], []

        def at(*indices: int) -> dict[str, JsonValue]:
            element = tree
            for index in indices:
                element = element["children"][index]
            return element

        def bind(
            element: dict[str, JsonValue],
            label: str,
            actions: list[str],
            target: str | None = None,
            conversation_id: str | None = None,
            **metadata: JsonValue,
        ) -> None:
            element["simulation"] = {
                "label": label,
                "actions": actions,
                "provenance": "RECONSTRUCTED",
                **metadata,
            }
            bindings[id(element)] = (target, conversation_id)

        bindings: dict[int, tuple[str | None, str | None]] = {}
        fragments: dict[str, dict[str, JsonValue]] = {}

        def fragment(name: str) -> dict[str, JsonValue]:
            if name not in fragments:
                fragments[name] = read_json(
                    ROOT / "fixtures/fragments" / f"{name}.json", "ax_fragment"
                )
            return deepcopy(fragments[name])

        def contact_row(
            conversation: dict[str, JsonValue], name: str, *, interactive: bool
        ) -> dict[str, JsonValue]:
            row = fragment(name)
            display_name, hint = (
                conversation["display_name"],
                conversation["identity_hint"],
            )
            text = display_name + (f" [{hint}]" if hint is not None else "")
            if interactive and name != "single-result":
                latest = next(
                    (
                        message
                        for message in reversed(self.state["messages"])
                        if message["conversation_id"] == conversation["id"]
                    ),
                    None,
                )
                if latest is not None:
                    text += ": " + latest["text"]
            row["description"] = row["value"] = text
            if interactive:
                bind(
                    row,
                    display_name,
                    ["activate"],
                    "open",
                    conversation["id"],
                    identity={
                        k: conversation[k] for k in ("display_name", "identity_hint")
                    },
                )
            return row

        if template == "chat-list":
            bind(at(0, 0, 0, 1, 3), "Search", ["activate"], "search")
            collection = at(0, 0, 0, 2)
            original = collection["children"]
            collection["children"] = (
                original[:1]
                + [contact_row(c, "chat-row", interactive=True) for c in candidates]
                + original[11:]
            )
        elif template == "conversation":
            conversation = next(
                c
                for c in self.state["conversations"]
                if c["id"] == ui["active_conversation_id"]
            )
            visible_conversations.append(conversation["id"])
            collection = at(0, 0, 0, 1, 0, 0, 0)
            original = collection["children"]
            collection["children"] = [
                contact_row(
                    c,
                    "selected-chat-row"
                    if c["id"] == conversation["id"]
                    else "chat-row",
                    interactive=False,
                )
                for c in self.state["conversations"]
            ] + original[13:]
            for index, header in enumerate(at(0, 0, 0, 1, 1, 0)["children"]):
                header["description"] = conversation["display_name"]
                if index == 0:
                    bind(
                        header,
                        conversation["display_name"],
                        [],
                        identity={
                            k: conversation[k]
                            for k in ("display_name", "identity_hint")
                        },
                    )
            history = at(0, 0, 0, 1, 1, 1, 0)
            original = history["children"]
            # Observed message composites include a wrapped first message and date headings.
            patterns = [
                original[:1],
                original[1:2],
                original[2:5],
                original[5:7],
                original[7:9],
                original[9:11],
            ]
            history["children"] = []
            for message in self.state["messages"]:
                if message["conversation_id"] != conversation["id"]:
                    continue
                chunk = deepcopy(patterns[len(visible_messages) % len(patterns)])
                leaf = chunk[-1]
                if leaf["role"] == "AXGroup":
                    leaf = leaf["children"][0]
                leaf["description"] = message["text"]
                bind(
                    leaf,
                    "Message",
                    [],
                    value=message["text"],
                    direction=message["direction"],
                )
                history["children"].extend(chunk)
                visible_messages.append(message["id"])
            composer = at(0, 0, 0, 1, 1, 1, 2)
            composer["focused"] = ui["focus"] == "composer"
            draft = ui["drafts"].get(conversation["id"], "")
            bind(
                composer,
                "Message",
                ["focus", "replace_text"],
                "composer",
                conversation["id"],
                value=draft,
            )
            send = at(1, 4, 0, 17)
            send["enabled"] = bool(draft)
            bind(send, "Send", ["activate"], "send", conversation["id"])
            back = at(1, 6, 0, 6)
            back["enabled"] = True
            bind(back, "Back", ["activate"], "back")
        else:
            search = at(0, 0, 0, 1, 0, 1, 3)
            search["focused"] = ui["focus"] == "search"
            if ui["query"]:
                search["value"] = ui["query"]
            bind(search, "Search", ["focus", "replace_text"], "query")
            clear = at(0, 0, 0, 1, 0, 1, 4)
            clear["enabled"] = int(bool(ui["query"]))
            bind(clear, "Clear text", ["activate"], "clear")
            back = at(1, 6, 0, 6)
            back["enabled"] = True
            bind(back, "Back", ["activate"], "back")
            background = at(0, 0, 0, 1, 0, 0, 1)
            original = background["children"]
            background["children"] = (
                original[:2]
                + [
                    contact_row(c, "chat-row", interactive=not ui["query"])
                    for c in self.state["conversations"]
                ]
                + original[11:]
            )
            if template == "results-many":
                results = at(0, 0, 0, 1, 0, 0, 0)
                original = results["children"]
                # Retain the observed category headings; unmodelled categories are empty.
                results["children"] = (
                    original[:1]
                    + [
                        contact_row(c, "single-result", interactive=True)
                        for c in candidates
                    ]
                    + [original[4], original[6]]
                )
            # Captured underlying conversation is not an active SimsApp conversation.
            for header in at(0, 0, 0, 1, 1, 0)["children"]:
                header["description"] = ""
                if "value" in header:
                    header["value"] = ""
            at(0, 0, 0, 1, 1, 1, 0)["children"] = []
        if template != "conversation":
            visible_conversations.extend(c["id"] for c in candidates)

        def reference(element: dict[str, JsonValue], path: str) -> None:
            ref = uuid5(NAMESPACE_OID, f"{scope}:{revision}:{template}:{path}").hex
            element["ref"] = ref
            target, conversation_id = bindings.get(id(element), (None, None))
            targets[ref] = (element, target, conversation_id)
            for index, child in enumerate(element.get("children", [])):
                reference(child, f"{path}/{index}")

        reference(tree, "")
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
            "template": template,
            "truncated": captured["truncated"],
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
            if (
                target == "query"
                and arguments["action"] == "replace_text"
                and len(arguments["text"])
                > STATE_SCHEMA["properties"]["ui"]["properties"]["query"]["maxLength"]
            ):
                error = "limit_exceeded"
            elif not element.get("enabled", True):
                error = "disabled"
            elif arguments["action"] not in element.get("simulation", {}).get(
                "actions", []
            ):
                error = "unsupported_action"
            elif arguments["action"] == "replace_text" and not element.get(
                "focused", False
            ):
                error = "not_focused"
        if error:
            return None, error, effect
        ui = self.state["ui"]
        previous = deepcopy(ui)
        message = None
        if arguments["action"] == "focus":
            ui["focus"] = "composer" if target == "composer" else "search"
        elif arguments["action"] == "replace_text":
            if target == "composer":
                if ui["drafts"].get(conversation_id, "") != arguments["text"]:
                    ui["drafts"][conversation_id] = arguments["text"]
            else:
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
        elif target == "send":
            if (
                len(self.state["messages"])
                >= STATE_SCHEMA["properties"]["messages"]["maxItems"]
            ):
                return None, "limit_exceeded", effect
            message = {
                "id": uuid4().hex,
                "conversation_id": conversation_id,
                "direction": "outgoing",
                "text": ui["drafts"][conversation_id],
            }
            self.state["messages"].append(message)
            ui["drafts"][conversation_id] = ""
            effect["message_id"] = message["id"]
        changes = [
            {"path": "/ui/" + key, "before": previous[key], "after": deepcopy(ui[key])}
            for key in ui
            if previous[key] != ui[key]
        ]
        if message is not None:
            changes.append(
                {
                    "path": f"/messages/{len(self.state['messages']) - 1}",
                    "before": None,
                    "after": message,
                }
            )
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
