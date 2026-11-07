"""A single-file timeline view of one session: both channels, decisions, timings, costs and errors."""

import html
import json
from datetime import datetime
from typing import Any

COLORS = {
    "transcript": "#2563eb", "chat_message": "#7c3aed", "field_observed": "#059669", "field_skipped": "#6b7280",
    "input_requested": "#d97706", "input_closed": "#9ca3af", "chat_queued": "#d97706", "record_produced": "#dc2626",
    "error": "#dc2626", "licence_checked": "#0891b2", "opted_out": "#dc2626", "review_flagged": "#dc2626",
    "call_started": "#111827", "call_ended": "#111827", "latency": "#9ca3af", "cost": "#9ca3af",
}


def _summary(e: dict[str, Any]) -> str:
    d, t = e["data"], e["type"]
    if t == "transcript":
        return f"<b>{d['role']}</b> (call): {html.escape(d['text'])}"
    if t == "chat_message":
        return f"<b>{d['role']}</b> (chat): {html.escape(d['text'])}"
    if t == "field_observed":
        mark = "✓" if d["valid"] else "✗"
        reason = f" — {html.escape(d['reason'])}" if d.get("reason") else ""
        shown = d.get("display") or d.get("value") or d.get("raw")
        return f"{mark} <b>{d['field']}</b> via {d['source']}: {html.escape(str(shown))}{reason}"
    return html.escape(json.dumps(d, default=str))


def render_timeline(view: dict[str, Any]) -> str:
    events = view["timeline"]
    t0 = events[0]["at"] if events else 0
    rows = "".join(
        f"<tr><td class=t>+{e['at'] - t0:7.1f}s</td><td class=t>{datetime.fromtimestamp(e['at']).strftime('%H:%M:%S')}</td>"
        f"<td><span class=tag style='background:{COLORS.get(e['type'], '#6b7280')}'>{e['type']}</span></td>"
        f"<td>{_summary(e)}</td></tr>"
        for e in events
    )
    fields = "".join(
        f"<tr><td>{n}</td><td class='s-{f['status']}'>{f['status']}</td><td>{html.escape(str(f['value']))}</td>"
        f"<td>{f['source'] or ''}</td><td>{f['attempts']}</td></tr>"
        for n, f in view["fields"].items()
    )
    lat = view["latencyMs"]
    lat_txt = f"{len(lat)} turns, median {sorted(lat)[len(lat) // 2]:.0f} ms" if lat else "no voice turns"
    record = html.escape(json.dumps(view["latestRecord"], indent=2)) if view["latestRecord"] else "not produced yet"
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Session {html.escape(view['sessionId'])}</title><style>
:root{{color-scheme:light dark;--bg:#fff;--fg:#111;--mut:#6b7280;--line:#e5e7eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b0f17;--fg:#e5e7eb;--mut:#9ca3af;--line:#1f2937}}}}
body{{font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1100px;padding:16px;background:var(--bg);color:var(--fg)}}
table{{border-collapse:collapse;width:100%;margin:8px 0 24px}}td,th{{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}}
.t{{color:var(--mut);white-space:nowrap;font-variant-numeric:tabular-nums}}.tag{{color:#fff;border-radius:4px;padding:1px 6px;font-size:12px;white-space:nowrap}}
.s-valid{{color:#059669}}.s-invalid{{color:#dc2626}}.s-missing{{color:var(--mut)}}pre{{background:rgba(127,127,127,.12);padding:12px;overflow:auto;border-radius:6px}}
.wrap{{overflow-x:auto}}</style></head><body>
<h1>Session {html.escape(view['sessionId'])}</h1>
<p>Cost so far: <b>${view['costUsd']:.4f}</b> · Voice latency: {lat_txt} · Records: {len(view['records'])}
 · <a href="/api/sessions/{html.escape(view['sessionId'])}">JSON</a></p>
<h2>Fields</h2><div class=wrap><table><tr><th>field</th><th>status</th><th>value</th><th>source</th><th>attempts</th></tr>{fields}</table></div>
<h2>Latest record</h2><pre>{record}</pre>
<h2>Timeline</h2><div class=wrap><table>{rows}</table></div></body></html>"""
