"""Regressions found in the recorded demo: a rejected licence stuck behind an optional card, an optional field
that couldn't be skipped by voice, and the agent hanging up with required fields still missing."""

import asyncio

import pytest

from app.files import FileStore
from app.runtime import Hub
from app.settings import Settings
from app.store import Store

from test_resilience import FakeLink, _never_called


@pytest.fixture
def hub(tmp_path):
    store = Store(tmp_path / "t.db")
    return Hub(store, _never_called, FileStore(Settings(), store))


def run(coro):
    return asyncio.run(coro)


def test_required_reupload_preempts_open_optional_card(hub):
    async def go():
        s = await hub.get("demo-1")
        await s.call_started(FakeLink())
        # Fast-forward to the demo's state: only the optional phone card is open.
        async with s.lock:
            if s.state.pending:
                await s._close(s.state.pending["id"])
            s.emit("chat_queued", {"fields": ["alternatePhone"], "front": True})
            await s._advance()
        assert s.state.pending["field"] == "alternatePhone"
        # The licence check rejects the upload: it must come back first, not after the optional card.
        async with s.lock:
            s.emit("chat_queued", {"fields": ["drivingLicence"], "front": True})
            await s._advance()
        assert s.state.pending["field"] == "drivingLicence"
        assert "alternatePhone" in s.state.chat_queue  # asked again afterwards

    run(go())


def test_optional_field_can_be_skipped_by_voice(hub):
    async def go():
        s = await hub.get("demo-2")
        await s.call_started(FakeLink())
        res = await s.voice_save_field("alternatePhone", "skip")
        assert res["ok"] and res["skipped"] == "alternatePhone"
        assert s.state.resolve("alternatePhone").status == "skipped"
        # A required field can't be "skipped" that way: it goes through validation and fails.
        res = await s.voice_save_field("ifscCode", "skip")
        assert res["ok"] is False

    run(go())


def test_agent_cannot_hang_up_with_required_fields_missing(hub):
    async def go():
        s = await hub.get("demo-3")
        await s.call_started(FakeLink())
        refusal = s.voice_may_hang_up(caller_wants_to_leave=False)
        assert refusal and "drivingLicence" in refusal["error"]
        assert s.voice_may_hang_up(caller_wants_to_leave=True) is None  # the caller's choice wins
        await s.opt_out("call", "changed mind")
        assert s.voice_may_hang_up(caller_wants_to_leave=False) is None

    run(go())
