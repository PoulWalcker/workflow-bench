"""Blindly reference fidelity through the existing UI and Evidence interfaces."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from tests.fast.test_simsapp import delivered as delivered
from tests.fast.test_simsapp import observe, simulator, start

FIXTURES = Path(__file__).resolve().parents[2] / "simapps/simsapp/fixtures"


def at(node, path):
    for index in path:
        node = node["children"][index]
    return node


def ax_only(node):
    return {
        key: [ax_only(child) for child in value] if key == "children" else value
        for key, value in node.items()
        if key not in {"ref", "simulation"}
    }


def test_chat_list_retains_native_ancestors_menus_and_observed_row_shape(delivered):
    async def check():
        app = simulator()
        capability = await start(app)
        current = await observe(app, capability)
        reference = json.loads((FIXTURES / "trees/chat-list.json").read_text())["tree"]
        assert current["tree"]["role"] == "AXApplication"
        # Menus/window chrome are independently captured, not synthesized controls.
        assert ax_only(current["tree"]["children"][1]) == reference["children"][1]
        for path in [[], [0], [0, 0], [0, 0, 0], [0, 0, 0, 2]]:
            actual = ax_only(at(current["tree"], path))
            expected = deepcopy(at(reference, path))
            actual.pop("children", None)
            expected.pop("children", None)
            assert actual == expected
        rows = at(current["tree"], [0, 0, 0, 2])["children"]
        bound = [row for row in rows if row.get("simulation", {}).get("actions")]
        assert len(bound) == 2
        fragment = json.loads((FIXTURES / "fragments/chat-row.json").read_text())
        for row in bound:
            actual = ax_only(row)
            for slot in ["description", "value"]:
                actual[slot] = fragment[slot]
            assert actual == fragment
        assert current["truncated"] is False
        assert current["template"] == "chat-list"

    asyncio.run(check())


def test_search_uses_native_field_and_zero_one_many_result_fragments(delivered):
    from tests.fast.test_simsapp import call, seed

    async def check():
        state = seed()
        state["conversations"] = [
            {
                "id": "private-a",
                "display_name": "Alice Morgan",
                "identity_hint": "South",
            },
            {
                "id": "private-b",
                "display_name": "Alice Morgan",
                "identity_hint": "North",
            },
        ]
        app = simulator()
        capability = await start(app, state)

        async def action(label, action="activate", **extra):
            observation = await observe(app, capability)

            def find(node):
                if node.get("simulation", {}).get("label") == label:
                    return node
                for child in node.get("children", []):
                    match = find(child)
                    if match is not None:
                        return match
                return None

            node = find(observation["tree"])
            return await call(
                app,
                capability,
                "ui_action",
                action=action,
                locator={
                    "scope": observation["scope"],
                    "revision": observation["revision"],
                    "ref": node["ref"],
                },
                **extra,
            )

        await action("Search")
        search = await observe(app, capability)
        assert search["template"] == "search-focused"
        field = at(search["tree"], [0, 0, 0, 1, 0, 1, 3])
        assert field["role"] == "AXStaticText" and field["subrole"] == "AXSearchField"
        assert "value" not in field and field["focused"] is False
        await action("Search", "focus")
        for query, names, template in [
            ("Nobody", [], "results-zero"),
            ("North", ["Alice Morgan [North]"], "results-many"),
            ("Alice", ["Alice Morgan [South]", "Alice Morgan [North]"], "results-many"),
        ]:
            await action("Search", "replace_text", text=query)
            current = await observe(app, capability)
            assert current["template"] == template
            group = at(current["tree"], [0, 0, 0, 1, 0, 0, 0])
            candidates = [
                n for n in group["children"] if n.get("simulation", {}).get("actions")
            ]
            assert [n["description"] for n in candidates] == names
            fragment = json.loads(
                (FIXTURES / "fragments/single-result.json").read_text()
            )
            for candidate in candidates:
                actual = ax_only(candidate)
                actual["description"] = fragment["description"]
                actual["value"] = fragment["value"]
                assert actual == fragment
            if not names:
                baseline = json.loads(
                    (FIXTURES / "trees/results-zero.json").read_text()
                )["tree"]
                assert ax_only(group) == at(baseline, [0, 0, 0, 1, 0, 0, 0])
            assert at(current["tree"], [0, 0, 0, 1, 0, 1, 3])["value"] == query

    asyncio.run(check())


def test_conversation_binds_exact_history_draft_and_reconstructed_menu_send(
    delivered, tmp_path
):
    from tests.fast.test_simsapp import act, frozen, nodes, seed

    async def check():
        state = seed()
        app = simulator()
        capability = await start(app, state)
        await act(app, capability, await observe(app, capability), "Search")
        await act(app, capability, await observe(app, capability), "Search", "focus")
        await act(
            app,
            capability,
            await observe(app, capability),
            "Search",
            "replace_text",
            text="Север",
        )
        await act(app, capability, await observe(app, capability), "Лена")
        current = await observe(app, capability)
        assert current["template"] == "conversation"
        history = at(current["tree"], [0, 0, 0, 1, 1, 1, 0])
        assert history["role"] == "AXGroup"
        messages = [n for n in nodes(history) if n.get("direction")]
        assert [n["description"] for n in messages] == ["  История\n"]
        # Empty AX value stays empty; the message body is its AX description.
        assert messages[0]["simulation"]["provenance"] == "RECONSTRUCTED"
        composer = at(current["tree"], [0, 0, 0, 1, 1, 1, 2])
        reference = json.loads((FIXTURES / "fragments/composer.json").read_text())
        expected = deepcopy(reference)
        expected["focused"] = False
        assert ax_only(composer) == expected
        await act(app, capability, current, "Message", "focus", role="AXTextArea")
        text = "  Hello 👩🏽‍💻\ne\u0301  "
        await act(
            app,
            capability,
            await observe(app, capability),
            "Message",
            "replace_text",
            role="AXTextArea",
            text=text,
        )
        ready = await observe(app, capability)
        send = at(ready["tree"], [1, 4, 0, 17])
        assert send["role"] == "AXMenuItem" and send["enabled"] is True
        send_reference = json.loads(
            (FIXTURES / "fragments/send-menu-item.json").read_text()
        )
        assert ax_only(send) == send_reference
        assert send["simulation"]["provenance"] == "RECONSTRUCTED"
        await act(app, capability, ready, "Send")
        assert (await act(app, capability, ready, "Send"))["error"][
            "code"
        ] == "stale_locator"
        after = await observe(app, capability)
        assert [
            n["description"] for n in nodes(after["tree"]) if n.get("direction")
        ] == ["  История\n", text]
        facts = await frozen(app, tmp_path)
        assert facts["after"]["state"]["messages"][-1]["conversation_id"] == "private-b"
        assert facts["after"]["state"]["messages"][-1]["text"] == text
        assert facts["after"]["state"]["ui"]["drafts"] == {
            "private-a": "Чужой draft",
            "private-b": "",
        }

    asyncio.run(check())


def test_chat_preview_tracks_current_message_after_send(delivered):
    from tests.fast.test_simsapp import act, nodes, seed

    async def check():
        state = seed()
        state["ui"].update(screen="conversation", active_conversation_id="private-b")
        state["ui"]["drafts"]["private-b"] = "New exact preview"
        app = simulator()
        capability = await start(app, state)
        await act(app, capability, await observe(app, capability), "Send")
        await act(app, capability, await observe(app, capability), "Back")
        current = await observe(app, capability)
        row = next(
            n
            for n in nodes(current["tree"])
            if n.get("identity", {}).get("identity_hint") == "Север"
        )
        assert row["description"] == "Лена [Север]: New exact preview"
        assert row["value"] == row["description"]

    asyncio.run(check())


@pytest.mark.parametrize("count", [0, 1, 6, 9, 100])
def test_variable_history_reuses_observed_composites_and_keeps_empty_values(
    delivered, tmp_path, count
):
    from tests.fast.test_simsapp import frozen, nodes, seed

    async def check():
        state = seed()
        state["messages"] = [
            {
                "id": f"private-message-{i}",
                "conversation_id": "private-b",
                "direction": "incoming" if i % 2 == 0 else "outgoing",
                "text": f"Exact message {i}",
            }
            for i in range(count)
        ]
        state["ui"].update(screen="conversation", active_conversation_id="private-b")
        app = simulator()
        capability = await start(app, state)
        current = await observe(app, capability)
        history = at(current["tree"], [0, 0, 0, 1, 1, 1, 0])
        messages = [n for n in nodes(history) if n.get("direction")]
        assert [n["description"] for n in messages] == [
            f"Exact message {i}" for i in range(count)
        ]
        # No invented message values: the first wrapper omits AXValue; later leaves keep "".
        if count:
            assert "value" not in at(history, [0, 0])
        if count > 1:
            assert at(history, [1])["value"] == ""
        reference = json.loads((FIXTURES / "trees/conversation.json").read_text())[
            "tree"
        ]
        source = at(reference, [0, 0, 0, 1, 1, 1, 0])
        if count == 6:
            expected = deepcopy(source)
            # These are the six observed message positions, independently read from the reference.
            for i, path in enumerate([[0, 0], [1], [4], [6], [8], [10]]):
                at(expected, path)["description"] = f"Exact message {i}"
            assert json.dumps(ax_only(history), sort_keys=True) == json.dumps(
                expected, sort_keys=True
            )
        assert len(list(nodes(current["tree"]))) <= 640
        facts = await frozen(app, tmp_path)
        assert facts["before"] == facts["after"]
        protected = next(
            e["details"]["observation"]
            for e in facts["events"]
            if "observation" in e["details"]
        )
        assert protected["visible_message_ids"] == [m["id"] for m in state["messages"]]

    asyncio.run(check())


def test_wrong_contact_and_unmodelled_ax_controls_do_not_retarget_send(
    delivered, tmp_path
):
    from tests.fast.test_simsapp import act, call, frozen, locator, seed

    async def check():
        state = seed()
        state["ui"]["drafts"]["private-b"] = "Keep other draft"
        app = simulator()
        capability = await start(app, state)
        initial = await observe(app, capability)
        await call(
            app,
            capability,
            "ui_action",
            action="activate",
            locator=locator(initial, "Лена", hint="Юг"),
        )
        current = await observe(app, capability)
        for path in [[0, 0, 0, 1, 1, 1, 4], [0, 0, 0, 1, 0, 0, 0, 1]]:
            # Voice message and a background row exist in AX, but have no simulator action.
            target = at(current["tree"], path)
            result = await call(
                app,
                capability,
                "ui_action",
                action="activate",
                locator={
                    "scope": current["scope"],
                    "revision": current["revision"],
                    "ref": target["ref"],
                },
            )
            assert result["error"]["code"] == "unsupported_action"
        assert await observe(app, capability) == current
        await act(app, capability, current, "Send")
        facts = await frozen(app, tmp_path)
        assert facts["after"]["state"]["messages"][:-1] == state["messages"]
        assert facts["after"]["state"]["messages"][-1]["conversation_id"] == "private-a"
        assert facts["after"]["state"]["messages"][-1]["text"] == "Чужой draft"
        assert (
            facts["after"]["state"]["ui"]["drafts"]["private-b"] == "Keep other draft"
        )

    asyncio.run(check())
