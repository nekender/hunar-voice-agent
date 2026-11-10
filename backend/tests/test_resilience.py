"""A database failure during a call must not leave the session stuck "on a call"."""

import asyncio

import pytest

from app.files import FileStore
from app.runtime import Hub
from app.settings import Settings
from app.store import Store


class FakeLink:
    call_id = "c_test"

    def __init__(self):
        self.notes: list[str] = []

    async def notify(self, text: str) -> None:
        self.notes.append(text)

    async def hangup(self, reason: str) -> None:
        pass


async def _never_called(session_id: str, url: str) -> dict:
    raise AssertionError("no licence checks in this test")


@pytest.fixture
def hub(tmp_path):
    store = Store(tmp_path / "t.db")
    return Hub(store, _never_called, FileStore(Settings(), store))


def test_bookkeeping_write_failure_does_not_raise(hub, monkeypatch):
    async def run():
        session = await hub.get("resil-1")
        link = FakeLink()
        await session.call_started(link)

        def broken(*args, **kwargs):
            raise ConnectionError("database went away")

        monkeypatch.setattr(hub.store, "append", broken)
        session.record_transcript("user", "I have two years of experience")  # must not raise
        session.record_cost(0.01, {"kind": "live"})
        session.record_latency(1200)

        # Recording the call end fails too; the bridge falls back to detaching the call.
        with pytest.raises(ConnectionError):
            await session.call_ended(link, 30, "error")
        session.detach_call(link)
        assert session.call is None and session.state.active_call is None
        assert not session.connected  # so the inactivity sweeper can close it

    asyncio.run(run())
