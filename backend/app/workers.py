"""Background loops: record delivery (outbox) and the inactivity sweeper. Both are restart-safe because all
their state is in the database: an undelivered record is retried on boot, and an idle session is found by query."""

import asyncio
import json
import logging
import time

import httpx

from .runtime import Hub
from .settings import Settings

log = logging.getLogger("workers")
records_log = logging.getLogger("records")


async def delivery_loop(hub: Hub, settings: Settings) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            try:
                for row in hub.store.due_deliveries(time.time()):
                    await _deliver(hub, settings, client, row)
            except Exception:
                log.exception("delivery pass failed")
            await hub.wait_delivery_wake(timeout=5)


async def _deliver(hub: Hub, settings: Settings, client: httpx.AsyncClient, row: dict) -> None:
    sid, rev = row["session_id"], row["revision"]
    body = json.loads(row["body"])
    # Uploaded documents travel as short-lived signed links, minted at delivery time.
    licence = body["fields"].get("drivingLicence", {})
    if licence.get("value"):
        licence["value"] = hub.files.signed(licence["value"], sid)
    records_log.info("RECORD %s", json.dumps(body))
    if not settings.record_webhook_url:
        hub.store.mark_delivered(sid, rev)
        return
    try:
        resp = await client.post(
            settings.record_webhook_url, json=body,
            headers={"Idempotency-Key": f"{sid}:{rev}", "X-Record-Revision": str(rev)},
        )
        resp.raise_for_status()
        hub.store.mark_delivered(sid, rev)
    except Exception as exc:
        backoff = min(600, 5 * 2 ** row["attempts"])
        log.warning("delivery of %s rev %s failed (%s); retry in %ss", sid, rev, exc, backoff)
        hub.store.mark_failed(sid, rev, repr(exc), backoff)


async def sweeper_loop(hub: Hub, settings: Settings, interval: float = 30) -> None:
    while True:
        try:
            for sid in hub.store.idle_sessions(time.time() - settings.inactivity_seconds):
                session = await hub.get(sid)
                await session.finalize_if_idle()
        except Exception:
            log.exception("sweeper pass failed")
        await asyncio.sleep(interval)
