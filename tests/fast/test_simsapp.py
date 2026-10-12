import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from aiohttp import web
from tests.fast.test_simulator import request

from workflow_bench.evaluation import read_evidence

IDENTITY = {
    "protocol": "ui_control",
    "run_id": "run",
    "control_id": "navigation",
    "case_id": "synthetic",
    "profile": "simsapp-ui-v1",
    "profile_hash": "b" * 64,
}
KEY = "host-only-key"


def seed():
    return {
        "conversations": [
            {"id": "private-a", "display_name": "Лена", "identity_hint": "Юг"},
            {"id": "private-b", "display_name": "Лена", "identity_hint": "Север"},
        ],
        "messages": [
            {
                "id": "private-m",
                "conversation_id": "private-b",
                "direction": "incoming",
                "text": "  История\n",
            }
        ],
        "ui": {
            "screen": "chat_list",
            "active_conversation_id": None,
            "query": "",
            "focus": None,
            "drafts": {"private-a": "Чужой draft"},
        },
    }


def simulator():
    path = Path(__file__).resolve().parents[2] / "simapps/simsapp/app.py"
    spec = importlib.util.spec_from_file_location("simsapp", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SimsApp(KEY)


@pytest.fixture
def delivered(monkeypatch):
    async def prepare(self, request):
        pass

    async def eof(self):
        pass

    monkeypatch.setattr(web.Response, "prepare", prepare)
    monkeypatch.setattr(web.Response, "write_eof", eof)


async def start(app, state=None, max_calls=100):
    await app.control(
        request(
            "reset",
            {
                "identity": IDENTITY,
                "state": state or seed(),
                "profile": IDENTITY["profile"],
                "limits": {"call_timeout_sec": 1},
            },
            KEY,
        )
    )
    issued = await app.control(
        request(
            "issue",
            {
                "identity": IDENTITY,
                "actor": "control",
                "ttl_sec": 60,
                "max_calls": max_calls,
            },
            KEY,
        )
    )
    return json.loads(issued.body)["capability"]


async def call(app, capability, operation, **arguments):
    response = await app.tool(
        request(
            operation,
            {"schema_version": "1.0", "arguments": arguments},
            capability,
            control=False,
        )
    )
    return json.loads(response.body)


def nodes(node):
    # Read app annotations while keeping native AX roles in every assertion.
    yield {"label": "", "actions": [], **node, **node.get("simulation", {})}
    for child in node.get("children", []):
        yield from nodes(child)


def locator(observation, label, *, hint=None, role=None):
    node = next(
        n
        for n in nodes(observation["tree"])
        if n["label"] == label
        and (role is None or n["role"] == role)
        and (hint is None or n.get("identity", {}).get("identity_hint") == hint)
    )
    return {
        "scope": observation["scope"],
        "revision": observation["revision"],
        "ref": node["ref"],
    }


async def observe(app, capability):
    return (await call(app, capability, "ui_observe"))["result"]


async def act(
    app, capability, observation, label, action="activate", *, role=None, **extra
):
    return await call(
        app,
        capability,
        "ui_action",
        action=action,
        locator=locator(observation, label, role=role),
        **extra,
    )


async def frozen(app, tmp_path):
    await app.control(request("revoke", {"identity": IDENTITY}, KEY))
    await app.control(request("freeze", {"identity": IDENTITY, "drain_sec": 1}, KEY))
    export = request("export", {}, KEY)
    export.method = "GET"
    path = tmp_path / "evidence.json"
    path.write_bytes((await app.control(export)).body)
    return read_evidence(path, expected_identity=IDENTITY).document


def test_navigation_opens_selected_history_and_back_preserves_business_state(
    delivered, tmp_path
):
    async def check():
        app = simulator()
        capability = await start(app)
        initial = await observe(app, capability)
        assert initial["screen"] == "chat_list"
        assert "private-" not in json.dumps(initial)
        await act(app, capability, initial, "Search")
        search = await observe(app, capability)
        await act(app, capability, search, "Search", "focus")
        search = await observe(app, capability)
        await act(app, capability, search, "Search", "replace_text", text="Север")
        results = await observe(app, capability)
        assert [
            n["identity"]["identity_hint"]
            for n in nodes(results["tree"])
            if "identity" in n
        ] == ["Север"]
        await act(app, capability, results, "Лена")
        conversation = await observe(app, capability)
        assert conversation["screen"] == "conversation"
        assert [
            n["value"]
            for n in nodes(conversation["tree"])
            if n["label"] == "Message" and n["role"] == "AXStaticText"
        ] == ["  История\n"]
        await act(app, capability, conversation, "Back")
        assert (await observe(app, capability))["screen"] == "chat_list"
        facts = await frozen(app, tmp_path)
        assert facts["freeze_status"] == "complete"
        assert facts["before"]["state"] == facts["after"]["state"]
        transitions = [
            e["details"]["transition"]
            for e in facts["events"]
            if "transition" in e["details"]
        ]
        assert len(transitions) == 5
        assert [t["to_revision"] for t in transitions] == [1, 2, 3, 4, 5]
        assert any(
            c["path"] == "/ui/active_conversation_id" and c["after"] == "private-b"
            for t in transitions
            for c in t["changes"]
        )

    asyncio.run(check())


def test_frozen_ingress_rejects_fabricated_transition_chain(delivered, tmp_path):
    from workflow_bench.data import DataError

    async def check():
        app = simulator()
        capability = await start(app)
        initial = await observe(app, capability)
        await act(app, capability, initial, "Search")
        facts = await frozen(app, tmp_path)
        transition = next(
            e["details"]["transition"]
            for e in facts["events"]
            if "transition" in e["details"]
        )
        transition["changes"][0]["before"] = "conversation"
        path = tmp_path / "forged.json"
        path.write_text(json.dumps(facts))
        with pytest.raises(DataError, match="invalid_transition"):
            read_evidence(path, expected_identity=IDENTITY)

    asyncio.run(check())


def test_rejected_locators_and_actions_preserve_state_and_revision(delivered, tmp_path):
    async def check():
        app = simulator()
        capability = await start(app)
        initial = await observe(app, capability)
        await act(app, capability, initial, "Search")
        search = await observe(app, capability)
        requests = [
            (
                {"action": "activate", "locator": locator(initial, "Search")},
                "stale_locator",
            ),
            (
                {
                    "action": "activate",
                    "locator": {**locator(search, "Search"), "ref": "hidden"},
                },
                "target_unavailable",
            ),
            (
                {"action": "activate", "locator": locator(search, "Clear text")},
                "disabled",
            ),
            (
                {"action": "activate", "locator": locator(search, "Search")},
                "unsupported_action",
            ),
            (
                {
                    "action": "replace_text",
                    "locator": locator(search, "Search"),
                    "text": "Юг",
                },
                "not_focused",
            ),
            (
                {
                    "action": "replace_text",
                    "locator": locator(search, "Search"),
                    "text": "x" * 257,
                },
                "limit_exceeded",
            ),
            (
                {"action": "click", "locator": locator(search, "Search")},
                "invalid_arguments",
            ),
            (
                {
                    "action": "focus",
                    "locator": locator(search, "Search"),
                    "actor": "admin",
                },
                "invalid_arguments",
            ),
        ]
        for arguments, expected in requests:
            result = await call(app, capability, "ui_action", **arguments)
            assert result["error"] == {"code": expected, "retryable": False}
        unchanged = await observe(app, capability)
        assert unchanged == search
        facts = await frozen(app, tmp_path)
        assert facts["after"]["revision"] == 1
        assert facts["after"]["state"]["ui"]["query"] == ""
        assert (
            len([e for e in facts["events"] if e["details"]["status"] == "committed"])
            == 1
        )

    asyncio.run(check())


def test_ui_only_bypass_is_forbidden_and_retained_without_effect(delivered, tmp_path):
    async def check():
        app = simulator()
        capability = await start(app)
        denied = await call(
            app, capability, "send_message", chat_id="private-b", text="bypass"
        )
        assert denied["error"]["code"] == "forbidden"
        facts = await frozen(app, tmp_path)
        assert facts["before"] == facts["after"]
        assert "ui_only_bypass" in facts["violations"]

    asyncio.run(check())


def test_incomplete_observation_never_claims_complete_absence(delivered, tmp_path):
    async def check():
        app = simulator()
        state = seed()
        state["conversations"] = []
        state["messages"] = []
        state["ui"]["drafts"] = {}
        capability = await start(app, state)
        await app.control(
            request(
                "fault",
                {
                    "identity": IDENTITY,
                    "mode": "incomplete_observation",
                    "delay_sec": 0,
                },
                KEY,
            )
        )
        observation = await observe(app, capability)
        assert observation["coverage"]["tree"] == "incomplete"
        assert observation["coverage"]["collection"]["complete"] is False
        facts = await frozen(app, tmp_path)
        protected = next(
            e["details"]["observation"]
            for e in facts["events"]
            if "observation" in e["details"]
        )
        assert protected["coverage"] == observation["coverage"]

    asyncio.run(check())


def test_search_zero_one_many_clear_and_noop_preserve_all_candidates(
    delivered, tmp_path
):
    async def check():
        app = simulator()
        state = seed()
        state["conversations"].append(
            {"id": "private-c", "display_name": "Лена", "identity_hint": "Север"}
        )
        capability = await start(app, state)
        await act(app, capability, await observe(app, capability), "Search")
        await act(app, capability, await observe(app, capability), "Search", "focus")
        for query, expected in [
            ("никто", []),
            ("Юг", ["Юг"]),
            ("Лена", ["Юг", "Север", "Север"]),
            ("лена", []),
        ]:
            await act(
                app,
                capability,
                await observe(app, capability),
                "Search",
                "replace_text",
                text=query,
            )
            current = await observe(app, capability)
            assert [
                n["identity"]["identity_hint"]
                for n in nodes(current["tree"])
                if "identity" in n
            ] == expected
            assert current["coverage"] == {
                "tree": "complete",
                "collection": {"kind": "conversations", "complete": True},
            }
        await act(app, capability, current, "Clear text")
        clear = await observe(app, capability)
        assert len([n for n in nodes(clear["tree"]) if "identity" in n]) == 3
        assert next(n for n in nodes(clear["tree"]) if n["label"] == "Search")[
            "focused"
        ]
        result = await act(app, capability, clear, "Search", "focus")
        assert result["result"] == {
            "status": "no_effect",
            "revision": clear["revision"],
        }
        facts = await frozen(app, tmp_path)
        assert (
            facts["before"]["state"]["messages"] == facts["after"]["state"]["messages"]
        )
        assert (
            facts["before"]["state"]["ui"]["drafts"]
            == facts["after"]["state"]["ui"]["drafts"]
        )

    asyncio.run(check())


def test_fresh_instance_restores_seed_and_invalidates_old_scope_and_capability(
    delivered, tmp_path
):
    async def check():
        old = simulator()
        old_capability = await start(old)
        original = await observe(old, old_capability)
        await act(old, old_capability, original, "Search")
        await act(
            old, old_capability, await observe(old, old_capability), "Search", "focus"
        )
        await act(
            old,
            old_capability,
            await observe(old, old_capability),
            "Search",
            "replace_text",
            text="Север",
        )
        await frozen(old, tmp_path)
        fresh = simulator()
        capability = await start(fresh)
        current = await observe(fresh, capability)
        assert current["revision"] == 0 and current["screen"] == "chat_list"
        assert current["scope"] != original["scope"]
        assert (await act(fresh, capability, original, "Search"))["error"][
            "code"
        ] == "stale_locator"
        assert (await call(fresh, old_capability, "ui_observe"))["error"][
            "code"
        ] == "forbidden"
        assert (await call(old, old_capability, "ui_observe"))["error"][
            "code"
        ] == "forbidden"
        facts = await frozen(fresh, tmp_path)
        assert facts["before"] == {"revision": 0, "state": seed()}
        assert facts["before"] == facts["after"]
        assert not any("transition" in e["details"] for e in facts["events"])

    asyncio.run(check())


def test_call_limit_closes_admission_and_bounds_rejected_journal(delivered, tmp_path):
    async def check():
        app = simulator()
        capability = await start(app, max_calls=1)
        await observe(app, capability)
        assert (await call(app, capability, "ui_observe"))["error"][
            "code"
        ] == "limit_exceeded"
        assert (await call(app, capability, "ui_observe"))["error"][
            "code"
        ] == "forbidden"
        for _ in range(450):
            await call(app, capability, "ui_observe")
        facts = await frozen(app, tmp_path)
        assert facts["before"] == facts["after"]
        assert len(facts["events"]) <= 1200
        assert "request_limit_exceeded" in facts["violations"]

    asyncio.run(check())


@pytest.mark.parametrize("screen", ["search", "conversation"])
def test_initial_screens_order_and_drafts_are_observed_without_hidden_data(
    delivered, tmp_path, screen
):
    async def check():
        state = seed()
        state["conversations"].reverse()
        state["ui"].update(
            screen=screen,
            active_conversation_id="private-a" if screen == "conversation" else None,
            query="Юг" if screen == "search" else "",
            focus="search" if screen == "search" else None,
        )
        app = simulator()
        capability = await start(app, state)
        current = await observe(app, capability)
        assert current["screen"] == screen and current["revision"] == 0
        assert [
            n["identity"]["identity_hint"]
            for n in nodes(current["tree"])
            if "identity" in n
        ] == ["Юг"]
        serialized = json.dumps(current, ensure_ascii=False)
        assert "История" not in serialized
        assert ("Чужой draft" in serialized) == (screen == "conversation")
        await act(app, capability, current, "Back")
        facts = await frozen(app, tmp_path)
        assert facts["after"]["state"]["ui"]["screen"] == "chat_list"
        assert facts["after"]["state"]["ui"]["query"] == ""
        assert facts["after"]["state"]["ui"]["drafts"] == state["ui"]["drafts"]
        assert facts["after"]["state"]["conversations"] == state["conversations"]

    asyncio.run(check())


@pytest.mark.parametrize(
    "fault",
    ["over_capacity", "missing_reference", "duplicate_id", "hidden_focus", "surrogate"],
)
def test_invalid_seed_is_rejected_before_capability_or_navigation(
    delivered, tmp_path, fault
):
    async def check():
        state = seed()
        if fault == "over_capacity":
            state["conversations"] = [
                {"id": str(i), "display_name": "A", "identity_hint": None}
                for i in range(33)
            ]
        elif fault == "missing_reference":
            state["messages"][0]["conversation_id"] = "missing"
        elif fault == "duplicate_id":
            state["conversations"][1]["id"] = state["conversations"][0]["id"]
        elif fault == "hidden_focus":
            state["ui"]["focus"] = "search"
        else:
            state["conversations"][0]["display_name"] = "\ud800"
        app = simulator()
        with pytest.raises(web.HTTPBadRequest, match="invalid_control"):
            await start(app, state)
        assert (await call(app, "not-issued", "ui_observe"))["error"][
            "code"
        ] == "forbidden"
        # A rejected seed does not consume the one allowed reset.
        capability = await start(app)
        assert (await observe(app, capability))["revision"] == 0
        facts = await frozen(app, tmp_path)
        assert facts["before"] == facts["after"] == {"revision": 0, "state": seed()}

    asyncio.run(check())


def test_capacity_projection_validates_and_remains_complete_without_truncation(
    delivered, tmp_path
):
    from workflow_bench.data import read_json, validate_json

    async def check():
        state = seed()
        state["conversations"] = [
            {"id": str(i), "display_name": "A", "identity_hint": None}
            for i in range(32)
        ]
        state["messages"] = [
            {
                "id": "m" + str(i),
                "conversation_id": "0",
                "direction": "incoming",
                "text": "x" * 4096,
            }
            for i in range(100)
        ]
        state["ui"].update(
            screen="conversation", active_conversation_id="0", drafts={"1": "x" * 4096}
        )
        app = simulator()
        capability = await start(app, state)
        observation = await observe(app, capability)
        contract = read_json(
            Path(__file__).resolve().parents[2] / "simapps/simsapp/tools.json", "tools"
        )
        validate_json(observation, contract["tools"][0]["result_schema"], "observation")
        assert (
            len(
                [
                    n
                    for n in nodes(observation["tree"])
                    if n["label"] == "Message" and n["role"] == "AXStaticText"
                ]
            )
            == 100
        )
        assert observation["coverage"]["collection"]["complete"]
        await act(app, capability, observation, "Back")
        observation = await observe(app, capability)
        validate_json(observation, contract["tools"][0]["result_schema"], "observation")
        assert len([n for n in nodes(observation["tree"]) if "identity" in n]) == 32
        facts = await frozen(app, tmp_path)
        assert facts["after"]["state"]["messages"] == state["messages"]

    asyncio.run(check())


def test_ingress_rejects_unknown_response_marked_as_complete(delivered, tmp_path):
    from workflow_bench.data import DataError

    async def check():
        app = simulator()
        capability = await start(app)
        await observe(app, capability)
        facts = await frozen(app, tmp_path)
        next(e for e in facts["events"] if e["stage"] == "response")["details"][
            "status"
        ] = "unknown"
        path = tmp_path / "forged.json"
        path.write_text(json.dumps(facts))
        with pytest.raises(DataError, match="incomplete_freeze"):
            read_evidence(path, expected_identity=IDENTITY)

    asyncio.run(check())


def test_composer_reads_replaces_and_preserves_drafts_per_conversation(
    delivered, tmp_path
):
    async def check():
        state = seed()
        state["ui"].update(screen="conversation", active_conversation_id="private-b")
        state["ui"]["drafts"]["private-b"] = "Старый draft"
        app = simulator()
        capability = await start(app, state)
        initial = await observe(app, capability)
        composer = next(n for n in nodes(initial["tree"]) if n["role"] == "AXTextArea")
        assert composer["label"] == "Message" and composer["value"] == "Старый draft"
        assert not composer["focused"]
        await act(app, capability, initial, "Message", "focus", role="AXTextArea")
        focused = await observe(app, capability)
        text = "  Привет 👩🏽‍💻\ne\u0301 {{literal}}  "
        await act(
            app,
            capability,
            focused,
            "Message",
            "replace_text",
            role="AXTextArea",
            text=text,
        )
        current = await observe(app, capability)
        composer = next(n for n in nodes(current["tree"]) if n["role"] == "AXTextArea")
        assert composer["focused"] and composer["value"] == text
        assert (
            await act(
                app,
                capability,
                current,
                "Message",
                "replace_text",
                role="AXTextArea",
                text=text,
            )
        )["result"]["status"] == "no_effect"
        await act(app, capability, current, "Back")
        await act(app, capability, await observe(app, capability), "Лена")
        other = await observe(app, capability)
        assert (
            next(n for n in nodes(other["tree"]) if n["role"] == "AXTextArea")["value"]
            == "Чужой draft"
        )
        facts = await frozen(app, tmp_path)
        assert facts["after"]["state"]["ui"]["drafts"] == {
            "private-a": "Чужой draft",
            "private-b": text,
        }
        assert facts["after"]["state"]["messages"] == state["messages"]
        assert facts["after"]["state"]["conversations"] == state["conversations"]

    asyncio.run(check())


@pytest.mark.parametrize(
    "text",
    ["  Привет 👩🏽‍💻\ne\u0301 {{literal}}  ", " \t\n ", "я" * 4096],
    ids=["unicode", "whitespace", "text-limit"],
)
def test_send_creates_one_exact_message_and_clears_only_active_draft(
    delivered, tmp_path, text
):
    async def check():
        state = seed()
        state["ui"].update(screen="conversation", active_conversation_id="private-b")
        state["ui"]["drafts"]["private-b"] = "Старый draft"
        state["messages"].append(
            {
                "id": "old-equal",
                "conversation_id": "private-b",
                "direction": "outgoing",
                "text": text,
            }
        )
        app = simulator()
        capability = await start(app, state)
        await act(
            app,
            capability,
            await observe(app, capability),
            "Message",
            "focus",
            role="AXTextArea",
        )
        replaced = await act(
            app,
            capability,
            await observe(app, capability),
            "Message",
            "replace_text",
            role="AXTextArea",
            text=text,
        )
        assert "error" not in replaced
        before_send = await observe(app, capability)
        sent = await act(app, capability, before_send, "Send")
        assert sent["result"] == {
            "status": "committed",
            "revision": before_send["revision"] + 1,
        }
        current = await observe(app, capability)
        assert [
            n["value"]
            for n in nodes(current["tree"])
            if n["role"] == "AXStaticText" and n["label"] == "Message"
        ] == ["  История\n", text, text]
        composer = next(n for n in nodes(current["tree"]) if n["role"] == "AXTextArea")
        assert composer["value"] == "" and composer["focused"]
        assert not next(n for n in nodes(current["tree"]) if n["label"] == "Send")[
            "enabled"
        ]
        facts = await frozen(app, tmp_path)
        after = facts["after"]["state"]
        assert after["messages"][:-1] == state["messages"]
        message = after["messages"][-1]
        assert message["id"] not in {m["id"] for m in state["messages"]}
        assert {k: v for k, v in message.items() if k != "id"} == {
            "conversation_id": "private-b",
            "direction": "outgoing",
            "text": text,
        }
        assert after["ui"]["drafts"] == {"private-a": "Чужой draft", "private-b": ""}
        assert after["conversations"] == state["conversations"]
        effect = next(
            e
            for e in facts["events"]
            if e["call_id"] == sent["call_id"] and e["stage"] == "effect"
        )
        assert effect["details"]["message_id"] == message["id"]
        assert {c["path"] for c in effect["details"]["transition"]["changes"]} == {
            "/messages/2",
            "/ui/drafts",
        }
        assert any(
            e["details"].get("observation", {}).get("visible_message_ids")
            == ["private-m", "old-equal", message["id"]]
            for e in facts["events"]
        )

    asyncio.run(check())


def test_full_message_capacity_rejects_send_atomically(delivered, tmp_path):
    async def check():
        state = seed()
        state["messages"] = [
            {
                "id": f"m-{i}",
                "conversation_id": "private-a",
                "direction": "incoming",
                "text": "old",
            }
            for i in range(100)
        ]
        state["ui"].update(
            screen="conversation",
            active_conversation_id="private-b",
            drafts={"private-a": "Чужой draft", "private-b": "Сохранить"},
        )
        app = simulator()
        capability = await start(app, state)
        current = await observe(app, capability)
        result = await act(app, capability, current, "Send")
        assert result["error"] == {"code": "limit_exceeded", "retryable": False}
        assert await observe(app, capability) == current
        facts = await frozen(app, tmp_path)
        assert facts["before"] == facts["after"]
        assert all(e["details"]["status"] != "committed" for e in facts["events"])

    asyncio.run(check())


def test_repeated_send_is_explicit_and_never_hidden_by_dedup(delivered, tmp_path):
    async def check():
        state = seed()
        state["ui"].update(
            screen="conversation",
            active_conversation_id="private-b",
            drafts={"private-a": "Чужой draft", "private-b": "повтор"},
        )
        app = simulator()
        capability = await start(app, state)
        initial = await observe(app, capability)
        first = await act(app, capability, initial, "Send")
        assert first["result"]["revision"] == 1
        assert (await act(app, capability, initial, "Send"))["error"][
            "code"
        ] == "stale_locator"
        assert (await act(app, capability, await observe(app, capability), "Send"))[
            "error"
        ]["code"] == "disabled"
        current = await observe(app, capability)
        assert not next(n for n in nodes(current["tree"]) if n["role"] == "AXTextArea")[
            "focused"
        ]
        await act(app, capability, current, "Message", "focus", role="AXTextArea")
        await act(
            app,
            capability,
            await observe(app, capability),
            "Message",
            "replace_text",
            role="AXTextArea",
            text="повтор",
        )
        await act(app, capability, await observe(app, capability), "Send")
        facts = await frozen(app, tmp_path)
        outgoing = facts["after"]["state"]["messages"][1:]
        assert len(outgoing) == 2 and outgoing[0]["id"] != outgoing[1]["id"]
        assert [m["text"] for m in outgoing] == ["повтор", "повтор"]
        assert all(m["conversation_id"] == "private-b" for m in outgoing)
        assert facts["after"]["state"]["ui"]["drafts"]["private-a"] == "Чужой draft"

    asyncio.run(check())


def test_invalid_composer_actions_never_change_draft_or_messages(delivered, tmp_path):
    async def check():
        state = seed()
        state["ui"].update(screen="conversation", active_conversation_id="private-b")
        app = simulator()
        capability = await start(app, state)
        initial = await observe(app, capability)
        message = locator(initial, "Message", role="AXTextArea")
        send = locator(initial, "Send")
        for arguments, code in [
            (
                {"action": "replace_text", "locator": message, "text": "x"},
                "not_focused",
            ),
            ({"action": "activate", "locator": message}, "unsupported_action"),
            ({"action": "activate", "locator": send}, "disabled"),
            (
                {"action": "replace_text", "locator": message, "text": "x" * 4097},
                "limit_exceeded",
            ),
            (
                {"action": "replace_text", "locator": message, "text": "\ud800"},
                "invalid_arguments",
            ),
            ({"action": "replace_text", "locator": message}, "invalid_arguments"),
            (
                {"action": "activate", "locator": send, "text": "bypass"},
                "invalid_arguments",
            ),
            ({"action": "send", "locator": send}, "invalid_arguments"),
            (
                {"action": "activate", "locator": {**send, "ref": "hidden"}},
                "target_unavailable",
            ),
        ]:
            assert (await call(app, capability, "ui_action", **arguments))["error"] == {
                "code": code,
                "retryable": False,
            }
        assert await observe(app, capability) == initial
        await act(app, capability, initial, "Message", "focus", role="AXTextArea")
        assert (
            await act(
                app,
                capability,
                initial,
                "Message",
                "replace_text",
                role="AXTextArea",
                text="x",
            )
        )["error"]["code"] == "stale_locator"
        focused = await observe(app, capability)
        assert (
            await act(
                app,
                capability,
                focused,
                "Message",
                "replace_text",
                role="AXTextArea",
                text="",
            )
        )["result"]["status"] == "no_effect"
        await act(app, capability, focused, "Back")
        unavailable = await observe(app, capability)
        assert not any(
            n["role"] == "AXTextArea" or n["label"] == "Send"
            for n in nodes(unavailable["tree"])
        )
        assert (
            await call(
                app,
                capability,
                "ui_action",
                action="activate",
                locator={**send, "revision": unavailable["revision"]},
            )
        )["error"]["code"] == "target_unavailable"
        facts = await frozen(app, tmp_path)
        assert facts["after"]["state"]["messages"] == state["messages"]
        assert facts["after"]["state"]["conversations"] == state["conversations"]
        assert facts["after"]["state"]["ui"]["drafts"] == state["ui"]["drafts"]

    asyncio.run(check())


def test_concurrent_send_with_same_locator_commits_once(delivered, tmp_path):
    async def check():
        state = seed()
        state["ui"].update(screen="conversation", active_conversation_id="private-b")
        state["ui"]["drafts"]["private-b"] = "один"
        app = simulator()
        capability = await start(app, state)
        current = await observe(app, capability)
        responses = await asyncio.gather(
            *(act(app, capability, current, "Send") for _ in range(2))
        )
        assert sum("result" in r for r in responses) == 1
        assert [r["error"]["code"] for r in responses if "error" in r] == [
            "stale_locator"
        ]
        facts = await frozen(app, tmp_path)
        assert facts["after"]["revision"] == 1
        assert len(facts["after"]["state"]["messages"]) == 2
        assert facts["after"]["state"]["messages"][-1]["text"] == "один"
        assert facts["after"]["state"]["ui"]["drafts"] == {
            "private-a": "Чужой draft",
            "private-b": "",
        }

    asyncio.run(check())
