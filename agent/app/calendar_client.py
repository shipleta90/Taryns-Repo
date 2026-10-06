"""Google Calendar access (primary calendar). Reads run immediately; creating an event only
happens after you approve it in the app (see assistant.py)."""
from __future__ import annotations

import datetime as dt
from typing import Protocol
from zoneinfo import ZoneInfo


class CalendarClient(Protocol):
    def list_events(self, start: dt.datetime, end: dt.datetime, limit: int = 50) -> list[dict]: ...
    def create_event(self, title: str, start: dt.datetime, end: dt.datetime, location: str,
                     description: str, attendees: list[str]) -> dict: ...


def _fmt(when: dict, tz: ZoneInfo) -> str:
    if "dateTime" in when:
        return dt.datetime.fromisoformat(when["dateTime"]).astimezone(tz).strftime("%a %b %-d, %-I:%M %p")
    return dt.date.fromisoformat(when["date"]).strftime("%a %b %-d") + " (all day)"


class GoogleCalendar:
    def __init__(self, credentials, timezone: str):
        from googleapiclient.discovery import build  # lazy: tests need no Google libs

        self.svc = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self.tz = ZoneInfo(timezone)
        self.tz_name = timezone

    def list_events(self, start: dt.datetime, end: dt.datetime, limit: int = 50) -> list[dict]:
        resp = self.svc.events().list(
            calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(),
            singleEvents=True, orderBy="startTime", maxResults=limit,
        ).execute()
        out = []
        for ev in resp.get("items", []):
            if ev.get("status") == "cancelled":
                continue
            out.append({
                "id": ev["id"],
                "title": ev.get("summary", "(no title)"),
                "start": _fmt(ev["start"], self.tz),
                "end": _fmt(ev["end"], self.tz),
                "location": ev.get("location", ""),
                "description": (ev.get("description") or "")[:500],
            })
        return out

    def create_event(self, title, start, end, location, description, attendees) -> dict:
        body = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": self.tz_name},
            "end": {"dateTime": end.isoformat(), "timeZone": self.tz_name},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        if attendees:
            body["attendees"] = [{"email": a} for a in attendees]
        ev = self.svc.events().insert(
            calendarId="primary", body=body, sendUpdates="all" if attendees else "none"
        ).execute()
        return {"id": ev["id"], "link": ev.get("htmlLink", "")}
