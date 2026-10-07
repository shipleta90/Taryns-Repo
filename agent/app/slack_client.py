"""Read-only Slack access with your own user token (a personal Slack app in the workspace).

Collects the last day's messages from channels you're a member of and ranks them so the
briefing can say what you missed: mentions of you first, then busy threads and popular posts.
"""
from __future__ import annotations

import time

import httpx


class SlackError(RuntimeError):
    pass


class SlackClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url="https://slack.com/api/", timeout=30.0, transport=transport,
                                  headers={"Authorization": f"Bearer {token}"})
        self._names: dict[str, str] = {}

    def _get(self, method: str, **params) -> dict:
        try:
            data = self._http.get(method, params=params).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SlackError(f"Slack request failed: {exc}") from exc
        if not data.get("ok"):
            raise SlackError(f"Slack said: {data.get('error', 'unknown error')}")
        return data

    def _name(self, user_id: str) -> str:
        if user_id not in self._names:
            try:
                u = self._get("users.info", user=user_id)["user"]
                self._names[user_id] = u.get("profile", {}).get("display_name") or u.get("real_name") or user_id
            except SlackError:
                self._names[user_id] = "someone"
        return self._names[user_id]

    def recent(self, hours: int = 24, max_channels: int = 40, top: int = 40) -> dict:
        me = self._get("auth.test")
        my_id, team, base = me["user_id"], me.get("team", "Slack"), me.get("url", "").rstrip("/")
        oldest = time.time() - hours * 3600

        channels, cursor = [], ""
        while len(channels) < max_channels:
            page = self._get("users.conversations", types="public_channel,private_channel",
                             exclude_archived="true", limit=200, cursor=cursor)
            channels += page.get("channels", [])
            cursor = page.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break

        scored = []
        for ch in channels[:max_channels]:
            try:
                msgs = self._get("conversations.history", channel=ch["id"], oldest=f"{oldest:.6f}",
                                 limit=100).get("messages", [])
            except SlackError:
                continue  # one unreadable channel shouldn't stop the rest
            for m in msgs:
                if m.get("subtype") or not m.get("text") or m.get("user") == my_id:
                    continue
                mentioned = f"<@{my_id}>" in m["text"]
                score = (10 if mentioned else 0) + 2 * m.get("reply_count", 0) + \
                    sum(r.get("count", 0) for r in m.get("reactions", []))
                scored.append((score, ch, m, mentioned))
        scored.sort(key=lambda t: t[0], reverse=True)

        items = []
        for score, ch, m, mentioned in scored[:top]:
            items.append({
                "channel": ch.get("name", ch["id"]),
                "author": self._name(m.get("user", "")),
                "text": m["text"][:1200],
                "replies": m.get("reply_count", 0),
                "mentions_you": mentioned,
                "link": f"{base}/archives/{ch['id']}/p{m['ts'].replace('.', '')}" if base else "",
            })
        return {"workspace": team, "channels_checked": min(len(channels), max_channels), "messages": items}
