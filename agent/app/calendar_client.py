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


def _sort_key(when: dict, tz: ZoneInfo) -> dt.datetime:
    if "dateTime" in when:
        return dt.datetime.fromisoformat(when["dateTime"]).astimezone(tz)
    return dt.datetime.combine(dt.date.fromisoformat(when["date"]), dt.time.min, tz)


class GoogleCalendar:
    def __init__(self, credentials, timezone: str):
        from googleapiclient.discovery import build  # lazy: tests need no Google libs

        self.svc = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self.tz = ZoneInfo(timezone)
        self.tz_name = timezone

    def _calendars(self) -> list[dict]:
        """Every calendar ticked in Google Calendar's sidebar (family, shared, school...), not just
        your main one. Needs the calendarlist.readonly permission; without it, only the main calendar."""
        try:
            items = self.svc.calendarList().list(minAccessRole="reader").execute().get("items", [])
        except Exception:
            return [{"id": "primary", "name": "Main"}]
        cals = [{"id": c["id"], "name": c.get("summaryOverride") or c.get("summary", "")}
                for c in items if c.get("selected") and not c.get("hidden")]
        return cals or [{"id": "primary", "name": "Main"}]

    def list_events(self, start: dt.datetime, end: dt.datetime, limit: int = 100) -> list[dict]:
        found = []
        for cal in self._calendars():
            try:
                resp = self.svc.events().list(
                    calendarId=cal["id"], timeMin=start.isoformat(), timeMax=end.isoformat(),
                    singleEvents=True, orderBy="startTime", maxResults=limit,
                ).execute()
            except Exception:  # a shared calendar we can't read shouldn't hide all the others
                continue
            for ev in resp.get("items", []):
                if ev.get("status") == "cancelled":
                    continue
                found.append((_sort_key(ev["start"], self.tz), {
                    "id": ev["id"],
                    "title": ev.get("summary", "(no title)"),
                    "start": _fmt(ev["start"], self.tz),
                    "end": _fmt(ev["end"], self.tz),
                    "calendar": cal["name"],
                    "location": ev.get("location", ""),
                    "description": (ev.get("description") or "")[:500],
                }))
        found.sort(key=lambda pair: pair[0])
        return [e for _, e in found[:limit]]

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
