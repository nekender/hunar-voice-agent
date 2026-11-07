"""End-to-end over the real FastAPI app: chat socket, uploads, records, restarts."""

import asyncio
import json

from fastapi.testclient import TestClient

from conftest import JPEG, VALID_AADHAAR

ANSWERS = {
    "experienceYears": 2,
    "preferredShift": "night",
    "serviceArea": "HSR Layout, Bengaluru",
    "hasTwoWheeler": True,
    "fullName": "Ravi Kumar",
    "aadhaarNumber": VALID_AADHAAR,
    "ifscCode": "sbin0001234",
    "vehicleType": "petrol_bike",
    "alternatePhone": None,  # optional: skipped
}


def recv_until(ws, type_):
    while True:
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg


def test_chat_only_session_completes_once_and_survives_restart(make_app):
    app = make_app()
    sid = "test-chat-only"
    with TestClient(app) as client:
        with client.websocket_connect(f"/chat?sessionId={sid}&fresh=1") as ws:
            card = recv_until(ws, "inputRequest")
            assert card["field"] == "_mode"
            ws.send_json({"type": "inputResponse", "requestId": card["id"], "field": "_mode", "value": True})

            seen = []
            while True:
                msg = ws.receive_json()
                if msg["type"] == "record":
                    record = msg["record"]
                    break
                if msg["type"] != "inputRequest":
                    continue
                field = msg["field"]
                seen.append(field)
                if field == "ifscCode" and seen.count(field) == 1:
                    ws.send_json({"type": "inputResponse", "requestId": msg["id"], "field": field, "value": "BAD"})
                    err = recv_until(ws, "inputError")
                    assert "IFSC" in err["message"]
                if field == "drivingLicence":
                    url = client.post(f"/sessions/{sid}/files", files={"file": ("dl.jpg", JPEG, "image/jpeg")}).json()["url"]
                    value = url
                else:
                    value = ANSWERS[field]
                ws.send_json({"type": "inputResponse", "requestId": msg["id"], "field": field, "value": value})

    # no API key -> licence is "unchecked" -> a human must look at it
    assert record["outcome"] == "needsReview"
    assert record["revision"] == 1
    assert record["fields"]["ifscCode"] == {**record["fields"]["ifscCode"], "value": "SBIN0001234", "attempts": 2}
    assert record["fields"]["alternatePhone"]["status"] == "skipped"
    assert record["fields"]["aadhaarNumber"]["value"].startswith("XXXX XXXX")
    assert seen[:4] == ["experienceYears", "preferredShift", "serviceArea", "hasTwoWheeler"]

    # restart: state is rebuilt, reconnecting does not produce a second record
    app = make_app()
    with TestClient(app) as client:
        with client.websocket_connect(f"/chat?sessionId={sid}&fresh=1") as ws:
            replayed = recv_until(ws, "record")["record"]
            assert replayed["revision"] == 1
        view = client.get(f"/api/sessions/{sid}").json()
        assert [r["revision"] for r in view["records"]] == [1]
        assert view["fields"]["ifscCode"]["value"] == "SBIN0001234"
        client.post(f"/api/sessions/{sid}/end")
        assert len(client.get(f"/api/sessions/{sid}").json()["records"]) == 1


def test_partial_then_user_returns_and_new_revision(make_app):
    app = make_app()
    with TestClient(app) as client:
        sid = client.post("/api/sessions").json()["sessionId"]
        for field in ["experienceYears", "preferredShift", "serviceArea"]:
            assert client.post(f"/api/sessions/{sid}/inputs", json={"field": field, "value": ANSWERS[field]}).json()["ok"]
        rec1 = client.post(f"/api/sessions/{sid}/end").json()
        assert rec1["outcome"] == "partial" and rec1["revision"] == 1
        assert client.post(f"/api/sessions/{sid}/end").json()["revision"] == 1  # unchanged -> no new revision

        for field in ["hasTwoWheeler", "fullName", "aadhaarNumber", "ifscCode", "vehicleType"]:
            client.post(f"/api/sessions/{sid}/inputs", json={"field": field, "value": ANSWERS[field]})
        url = client.post(f"/sessions/{sid}/files", files={"file": ("dl.jpg", JPEG, "image/jpeg")}).json()["url"]
        client.post(f"/api/sessions/{sid}/inputs", json={"field": "drivingLicence", "value": url})
        rec2 = client.post(f"/api/sessions/{sid}/end").json()
        assert rec2["revision"] == 2 and rec2["supersedes"] == 1
        assert rec2["outcome"] == "needsReview"


def test_opt_out_from_chat(make_app):
    app = make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/chat?sessionId=test-optout&fresh=1") as ws:
            recv_until(ws, "inputRequest")
            ws.send_json({"type": "optOut"})
            rec = recv_until(ws, "record")["record"]
    assert rec["outcome"] == "optedOut"


def test_upload_rejects_non_images_and_links_are_signed(make_app):
    app = make_app()
    with TestClient(app) as client:
        r = client.post("/sessions/abcd/files", files={"file": ("x.jpg", b"MZ\x90\x00 not an image", "image/jpeg")})
        assert r.status_code == 415
        url = client.post("/sessions/abcd/files", files={"file": ("dl.jpg", JPEG, "image/jpeg")}).json()["url"]
        path = url.split("testserver", 1)[1]
        assert client.get(path).status_code == 403  # unsigned links don't serve the ID document


def test_upload_from_another_session_is_rejected(make_app):
    app = make_app()
    with TestClient(app) as client:
        other = client.post("/sessions/other-session/files", files={"file": ("dl.jpg", JPEG, "image/jpeg")}).json()["url"]
        sid = client.post("/api/sessions").json()["sessionId"]
        res = client.post(f"/api/sessions/{sid}/inputs", json={"field": "drivingLicence", "value": other}).json()
        assert res["ok"] is False


def test_delivery_is_idempotent_with_stub_sink(make_app, monkeypatch):
    app = make_app()
    with TestClient(app) as client:
        store = app.state.hub.store
        store.ensure_session("s-del")
        store.insert_record("s-del", "partial", "fp1", lambda rev: {"sessionId": "s-del", "revision": rev, "fields": {}})
        assert client.post("/sink/records", json={"sessionId": "s-del", "revision": 1}, headers={"Idempotency-Key": "s-del:1"}).status_code == 201
        assert client.post("/sink/records", json={"sessionId": "s-del", "revision": 1}, headers={"Idempotency-Key": "s-del:1"}).json()["duplicate"]
        # same fingerprint -> no second revision
        assert store.insert_record("s-del", "partial", "fp1", lambda rev: {}) is None
        assert len(store.records("s-del")) == 1
