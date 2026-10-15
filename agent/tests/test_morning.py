import json

import httpx
import pytest

from app import morning
from app.db import Database
from app.slack_client import SlackClient, SlackError
from tests.test_assistant import FakeClaude, Resp

FULL = "\n".join(f"## {i}. {t}\n- **x** y [Source](https://e.com/{i})" for i, t in enumerate(
    ["World News Radar", "AI & Agentic Operations Breakthroughs", "Process Automation & Tooling Pulse",
     "The Strategic Play", "Newsletter Digest", "Axios: What Matters", "Slack: What You Missed"], 1))


def final(text, citations=()):
    return Resp([{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q"}},
                 {"type": "text", "text": text, "citations": list(citations)}], "end_turn")


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.sqlite3")


def test_build_saves_markdown_sources_and_uses_web_tools(db):
    cites = [{"url": "https://a.com/1", "title": "A"}, {"url": "https://a.com/1", "title": "dup"},
             {"url": "javascript:alert(1)", "title": "bad"}]
    claude = FakeClaude([final(FULL, cites)])
    out = morning.build(claude, db, "claude-opus-5-5", "medium", "America/Los_Angeles", "ops consultant",
                        {"axios": [{"subject": "Pro Rata"}], "slack": "not connected"})
    kw = claude.last_kwargs
    assert {t["type"] for t in kw["tools"]} == {"web_search_20260209", "web_fetch_20260209"}
    prompt = kw["messages"][0]["content"]
    assert "About the reader: ops consultant" in prompt and "<axios>" in prompt and "not connected" in prompt
    assert out["sources"] == [{"title": "A", "url": "https://a.com/1"}] and out["note"] is None
    assert db.latest_morning()["markdown"] == FULL


def test_pause_turn_resends_the_turn_unchanged(db):
    paused = Resp([{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {}}], "pause_turn")
    claude = FakeClaude([paused, final(FULL)])
    morning.build(claude, db, "m", "medium", "America/Los_Angeles")
    second = claude.calls[1]
    assert len(second) == 2 and second[1] == {"role": "assistant", "content": paused.blocks}


def test_missing_sections_are_flagged(db):
    out = morning.build(FakeClaude([final("## 1. World News Radar\n- a")]), db, "m", "medium", "UTC")
    assert "The Strategic Play" in out["note"] and "Slack" in out["note"]


def test_refusal_and_empty_raise(db):
    with pytest.raises(RuntimeError):
        morning.build(FakeClaude([Resp([], "refusal")]), db, "m", "medium", "UTC")
    with pytest.raises(RuntimeError):
        morning.build(FakeClaude([final("")]), db, "m", "medium", "UTC")
    assert db.latest_morning() is None


class Mail:
    def __init__(self, by_query, fail=False):
        self.by_query, self.fail = by_query, fail

    def search(self, query, limit):
        if self.fail:
            raise RuntimeError("token expired")
        return [{"id": m["id"]} for m in self.by_query.get(query, [])][:limit]

    def read(self, mid, body_limit=4000):
        for msgs in self.by_query.values():
            for m in msgs:
                if m["id"] == mid:
                    return m


def test_gather_newsletters_axios_and_privacy_filter():
    mail = Mail({
        morning.NEWSLETTER_QUERY: [{"id": "n1", "from": "One Useful Thing", "subject": "Agents", "date": "d", "body": "ideas"},
                                   {"id": "n2", "from": "x", "subject": "s", "date": "d", "body": "SSN 123-45-6789"}],
        morning.AXIOS_QUERY: [],
    })
    data = morning.gather(lambda: mail, lambda: None)
    assert [n["subject"] for n in data["newsletters"]] == ["Agents"]
    assert data["axios"].startswith("empty") and data["slack"].startswith("not connected")


def test_slack_falls_back_to_notification_emails():
    mail = Mail({morning.SLACK_EMAIL_QUERY: [
        {"id": "s1", "from": "Slack", "subject": "[Slack] Notifications from Women Defining AI",
         "date": "d", "body": "Ana mentioned you in #events"}]})
    data = morning.gather(lambda: mail, lambda: None)
    assert data["slack"]["emails"][0]["body"] == "Ana mentioned you in #events"


def test_gather_sources_fail_independently():
    class BrokenSlack:
        def recent(self):
            raise SlackError("Slack said: invalid_auth")
    data = morning.gather(lambda: Mail({}, fail=True), lambda: BrokenSlack())
    assert data["newsletters"].startswith("not available") and "invalid_auth" in data["slack"]


def slack_transport(responses):
    def handler(req):
        method = req.url.path.rsplit("/", 1)[-1]
        body = responses[method](dict(req.url.params)) if callable(responses[method]) else responses[method]
        return httpx.Response(200, json=body)
    return httpx.MockTransport(handler)


def test_slack_ranks_mentions_first_and_skips_noise():
    history = {
        "C1": [{"ts": "1.000100", "user": "U2", "text": "general chat", "reply_count": 3},
               {"ts": "2.000200", "user": "U3", "text": "hey <@ME> can you share your deck?"},
               {"ts": "3.0", "user": "ME", "text": "my own post", "reply_count": 50},
               {"ts": "4.0", "subtype": "channel_join", "user": "U4", "text": "joined"}],
        "C2": "error",
    }

    def hist(params):
        h = history[params["channel"]]
        return {"ok": False, "error": "not_in_channel"} if h == "error" else {"ok": True, "messages": h}

    client = SlackClient("xoxp-test", transport=slack_transport({
        "auth.test": {"ok": True, "user_id": "ME", "team": "Women Defining AI", "url": "https://wdai.slack.com/"},
        "users.conversations": {"ok": True, "channels": [{"id": "C1", "name": "general"}, {"id": "C2", "name": "x"}]},
        "conversations.history": hist,
        "users.info": lambda p: {"ok": True, "user": {"real_name": f"Name {p['user']}", "profile": {}}},
    }))
    out = client.recent()
    assert out["workspace"] == "Women Defining AI" and out["channels_checked"] == 2
    texts = [m["text"] for m in out["messages"]]
    assert texts == ["hey <@ME> can you share your deck?", "general chat"]
    assert out["messages"][0]["mentions_you"] and out["messages"][0]["author"] == "Name U3"
    assert out["messages"][0]["link"] == "https://wdai.slack.com/archives/C1/p2000200"


def test_slack_auth_error_is_reported():
    client = SlackClient("xoxp-bad", transport=slack_transport({"auth.test": {"ok": False, "error": "invalid_auth"}}))
    with pytest.raises(SlackError, match="invalid_auth"):
        client.recent()
