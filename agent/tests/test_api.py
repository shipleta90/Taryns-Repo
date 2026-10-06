import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.scheduler import seconds_until
from tests.fakes import FakeGmail, FakeLLM, promo

AUTH = {"Authorization": "Bearer secret"}


@pytest.fixture
def client(tmp_path):
    s = Settings(token="secret", dry_run=False, max_trash_per_run=25, lookback_days=2,
                 triage_at="", data_dir=tmp_path)
    app = create_app(s, gmail=FakeGmail([promo(1)]), llm=FakeLLM())
    with TestClient(app) as c:
        yield c


def test_requires_token(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/status", headers=AUTH).status_code == 200
    assert client.get("/api/health").json() == {"ok": True}


def test_refuses_to_start_without_token(tmp_path):
    s = Settings(token="", dry_run=True, max_trash_per_run=1, lookback_days=1, triage_at="", data_dir=tmp_path)
    with pytest.raises(RuntimeError):
        create_app(s)


def test_run_then_undo(client):
    r = client.post("/api/triage/run", json={"dry_run": False}, headers=AUTH)
    assert r.status_code == 200 and r.json()["trashed"] == 1
    acts = client.get("/api/actions", headers=AUTH).json()
    assert acts[0]["action"] == "trash"
    assert client.post(f"/api/actions/{acts[0]['id']}/undo", headers=AUTH).status_code == 200
    assert client.post(f"/api/actions/{acts[0]['id']}/undo", headers=AUTH).status_code == 400
    assert client.post("/api/actions/999/undo", headers=AUTH).status_code == 404


def test_static_app_served(client):
    assert "Inbox" in client.get("/").text
    assert client.get("/sw.js").status_code == 200
    assert client.get("/static/manifest.webmanifest").status_code == 200


def test_seconds_until():
    now = dt.datetime(2026, 1, 1, 1, 0)
    assert seconds_until("02:30", now) == 5400
    assert seconds_until("00:30", now) == 23.5 * 3600


def test_briefing_endpoints(client):
    import time
    assert client.get("/api/briefing").status_code == 401
    assert client.get("/api/briefing", headers=AUTH).json()["briefing"] is None
    assert client.post("/api/briefing/run", headers=AUTH).status_code == 202
    for _ in range(50):
        res = client.get("/api/briefing", headers=AUTH).json()
        if res["briefing"] and not res["running"]:
            break
        time.sleep(0.05)
    assert res["briefing"] is not None and res["error"] is None


def test_chat_without_api_key_explains_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("app.secrets.anthropic_key", lambda: None)
    s = Settings(token="secret", dry_run=True, max_trash_per_run=1, lookback_days=1, triage_at="",
                 data_dir=tmp_path, briefing_at="")
    with TestClient(create_app(s, gmail=FakeGmail([]), llm=FakeLLM())) as c:
        assert "set-anthropic-key" in c.get("/api/chat", headers=AUTH).json()["setup"]
        assert c.post("/api/chat", json={"text": "hi"}, headers=AUTH).status_code == 409


def test_chat_and_approval_endpoints(tmp_path):
    from tests.test_assistant import FakeCal, FakeClaude, FakeMail, text, tool
    s = Settings(token="secret", dry_run=True, max_trash_per_run=1, lookback_days=1, triage_at="",
                 data_dir=tmp_path, briefing_at="")
    mail = FakeMail()
    claude = FakeClaude([tool("propose_email", {"to": ["a@b.com"], "subject": "s", "body": "b",
                                                "reply_to_message_id": ""}), text("Waiting for your approval.")])
    with TestClient(create_app(s, gmail=mail, llm=FakeLLM(), calendar=FakeCal(), claude=claude)) as c:
        assert c.post("/api/chat", json={"text": "hi"}).status_code == 401
        r = c.post("/api/chat", json={"text": "email a"}, headers=AUTH).json()
        assert r["reply"] == "Waiting for your approval."
        card = [i for i in r["items"] if i["type"] == "proposal"][0]
        assert card["status"] == "pending" and mail.sent == []
        assert c.post(f"/api/proposals/{card['id']}/approve", json={"mode": "send"}, headers=AUTH).status_code == 200
        assert c.post(f"/api/proposals/{card['id']}/approve", json={"mode": "send"}, headers=AUTH).status_code == 409
        assert len(mail.sent) == 1
        assert c.post("/api/proposals/999/reject", headers=AUTH).status_code == 404
