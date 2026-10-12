import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

IDENTITY = {
    "run_id": "run",
    "attempt_id": "attempt",
    "replay_id": "replay",
    "artifact_hash": "a" * 64,
    "case_id": "fresh",
    "profile_hash": "b" * 64,
    "profile": "t1-api-v1",
}


def simulator():
    path = Path(__file__).resolve().parents[2] / "simapps/telegram/app.py"
    spec = importlib.util.spec_from_file_location("telegram_simulator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Telegram("host-only-key")


def request(operation: str, data: dict, key: str, *, control: bool = True):
    async def read():
        return json.dumps(data).encode()

    return SimpleNamespace(
        headers={"Authorization": "Bearer " + key},
        method="POST",
        match_info={"operation" if control else "name": operation},
        read=read,
        transport=SimpleNamespace(abort=lambda: None),
    )


async def reset(app):
    await app.control(
        request(
            "reset",
            {
                "identity": IDENTITY,
                "state": {
                    "chats": [{"id": "42", "display_name": "Anna"}],
                    "messages": [],
                },
                "profile": IDENTITY["profile"],
                "limits": {"call_timeout_sec": 1},
            },
            "host-only-key",
        )
    )
    response = await app.control(
        request(
            "issue",
            {
                "identity": IDENTITY,
                "actor": "workflow",
                "ttl_sec": 60,
                "max_calls": 8,
            },
            "host-only-key",
        )
    )
    return json.loads(response.body)["capability"]


def test_lost_response_after_commit_is_a_fact_not_an_automatic_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def delivered(self, request):
        return None

    async def eof(self):
        pass

    monkeypatch.setattr(web.Response, "prepare", delivered)
    monkeypatch.setattr(web.Response, "write_eof", eof)

    async def check():
        app = simulator()
        capability = await reset(app)
        await app.control(
            request(
                "fault",
                {"identity": IDENTITY, "mode": "drop_response", "delay_sec": 0},
                "host-only-key",
            )
        )
        await app.tool(
            request(
                "send_message",
                {
                    "schema_version": "1.0",
                    "arguments": {"chat_id": "42", "text": "exact"},
                },
                capability,
                control=False,
            )
        )
        await app.control(
            request("freeze", {"identity": IDENTITY, "drain_sec": 1}, "host-only-key")
        )
        exported = request("export", {}, "host-only-key")
        exported.method = "GET"
        facts = json.loads((await app.control(exported)).body)
        assert facts["after"]["revision"] == 1
        assert len(facts["after"]["state"]["messages"]) == 1
        assert [e["stage"] for e in facts["events"]] == [
            "accepted",
            "effect",
            "response",
        ]
        assert facts["events"][1]["details"]["status"] == "committed"
        assert facts["events"][2]["details"]["status"] == "failed"

    asyncio.run(check())


def test_drain_deadline_seals_pending_operation_without_late_commit() -> None:
    async def check():
        app = simulator()
        capability = await reset(app)
        await app.control(
            request(
                "fault",
                {"identity": IDENTITY, "mode": "stall_before_commit", "delay_sec": 0.1},
                "host-only-key",
            )
        )
        started = asyncio.Event()
        tool = request(
            "send_message",
            {"schema_version": "1.0", "arguments": {"chat_id": "42", "text": "late"}},
            capability,
            control=False,
        )
        read = tool.read

        async def reading():
            body = await read()
            started.set()
            return body

        tool.read = reading
        pending = asyncio.create_task(app.tool(tool))
        await started.wait()
        await app.control(
            request(
                "freeze", {"identity": IDENTITY, "drain_sec": 0.01}, "host-only-key"
            )
        )
        exported = request("export", {}, "host-only-key")
        exported.method = "GET"
        before = json.loads((await app.control(exported)).body)
        assert before["freeze_status"] == "incomplete"
        assert before["pending_call_ids"]
        assert before["after"]["revision"] == 0
        await pending
        after = json.loads((await app.control(exported)).body)
        assert after == before and after["after"]["state"]["messages"] == []

    asyncio.run(check())


def test_rejected_request_flood_keeps_bounded_frozen_effects(tmp_path, monkeypatch):
    from workflow_bench.evaluation import read_evidence

    async def delivered(self, request):
        return None

    async def eof(self):
        pass

    monkeypatch.setattr(web.Response, "prepare", delivered)
    monkeypatch.setattr(web.Response, "write_eof", eof)

    async def check():
        app = simulator()
        capability = await reset(app)
        await app.tool(
            request(
                "send_message",
                {
                    "schema_version": "1.0",
                    "arguments": {"chat_id": "42", "text": "wrong"},
                },
                capability,
                control=False,
            )
        )
        for _ in range(1000):
            await app.tool(request("send_message", {}, "invalid", control=False))
        await app.control(
            request("freeze", {"identity": IDENTITY, "drain_sec": 1}, "host-only-key")
        )
        exported = request("export", {}, "host-only-key")
        exported.method = "GET"
        content = (await app.control(exported)).body
        assert len(content) < 512 * 1024
        path = tmp_path / "evidence.json"
        path.write_bytes(content)
        facts = read_evidence(path, expected_identity=IDENTITY).document
        assert facts["freeze_status"] == "complete"
        assert facts["after"]["state"]["messages"][0]["text"] == "wrong"
        assert "request_limit_exceeded" in facts["violations"]
        assert "unauthorized_send" in facts["violations"]
        assert (
            len([e for e in facts["events"] if e["details"]["status"] == "committed"])
            == 1
        )

    asyncio.run(check())


def test_slow_body_does_not_block_freeze_or_commit_after_it(monkeypatch):
    async def delivered(self, request):
        return None

    async def eof(self):
        pass

    monkeypatch.setattr(web.Response, "prepare", delivered)
    monkeypatch.setattr(web.Response, "write_eof", eof)

    async def check():
        app = simulator()
        capability = await reset(app)
        reading, release = asyncio.Event(), asyncio.Event()
        tool = request(
            "send_message",
            {"schema_version": "1.0", "arguments": {"chat_id": "42", "text": "late"}},
            capability,
            control=False,
        )
        read = tool.read

        async def slow_read():
            reading.set()
            await release.wait()
            return await read()

        tool.read = slow_read
        pending = asyncio.create_task(app.tool(tool))
        await reading.wait()
        try:
            frozen = await asyncio.wait_for(
                app.control(
                    request(
                        "freeze",
                        {"identity": IDENTITY, "drain_sec": 0.01},
                        "host-only-key",
                    )
                ),
                timeout=0.5,
            )
            assert json.loads(frozen.body)["freeze_status"] == "complete"
        finally:
            release.set()
            await pending
        exported = request("export", {}, "host-only-key")
        exported.method = "GET"
        facts = json.loads((await app.control(exported)).body)
        assert facts["after"]["revision"] == 0 and facts["events"] == []

    asyncio.run(check())


def test_expired_send_after_journal_limit_retains_unauthorized_evidence(monkeypatch):
    async def delivered(self, request):
        return None

    async def eof(self):
        pass

    monkeypatch.setattr(web.Response, "prepare", delivered)
    monkeypatch.setattr(web.Response, "write_eof", eof)

    async def check():
        app = simulator()
        capability = await reset(app)
        for _ in range(1000):
            await app.tool(request("get_chat", {}, "invalid", control=False))
        monkeypatch.setattr("time.monotonic", lambda: 1e20)
        response = await app.tool(
            request("send_message", {}, capability, control=False)
        )
        assert json.loads(response.body)["error"]["code"] == "forbidden"
        await app.control(
            request("freeze", {"identity": IDENTITY, "drain_sec": 1}, "host-only-key")
        )
        exported = request("export", {}, "host-only-key")
        exported.method = "GET"
        assert (
            "unauthorized_send"
            in json.loads((await app.control(exported)).body)["violations"]
        )

    asyncio.run(check())


def test_slow_response_freezes_committed_effect_without_late_journal_changes(
    tmp_path, monkeypatch
):
    from workflow_bench.evaluation import read_evidence

    async def check():
        writing, release = asyncio.Event(), asyncio.Event()

        async def prepare(self, request):
            writing.set()
            await release.wait()

        async def eof(self):
            pass

        monkeypatch.setattr(web.Response, "prepare", prepare)
        monkeypatch.setattr(web.Response, "write_eof", eof)
        app = simulator()
        capability = await reset(app)
        pending = asyncio.create_task(
            app.tool(
                request(
                    "send_message",
                    {
                        "schema_version": "1.0",
                        "arguments": {"chat_id": "42", "text": "committed"},
                    },
                    capability,
                    control=False,
                )
            )
        )
        await writing.wait()
        try:
            await asyncio.wait_for(
                app.control(
                    request(
                        "freeze",
                        {"identity": IDENTITY, "drain_sec": 0.01},
                        "host-only-key",
                    )
                ),
                timeout=0.5,
            )
            exported = request("export", {}, "host-only-key")
            exported.method = "GET"
            content = (await app.control(exported)).body
            path = tmp_path / "evidence.json"
            path.write_bytes(content)
            facts = read_evidence(path, expected_identity=IDENTITY).document
            assert facts["freeze_status"] == "incomplete"
            assert facts["events"][1]["details"]["status"] == "committed"
            assert facts["events"][2]["details"]["status"] == "unknown"
        finally:
            release.set()
            await pending
        assert (await app.control(exported)).body == content

    asyncio.run(check())
