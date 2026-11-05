"""Google Calendar access (every calendar ticked in Google Calendar). Reads run immediately;
creating, changing or removing an event only happens after you approve it in the app
(see assistant.py)."""
from __future__ import annotations

import datetime as dt
from typing import Protocol
from zoneinfo import ZoneInfo


class CalendarClient(Protocol):
    def list_events(self, start: dt.datetime, end: dt.datetime, limit: int = 50) -> list[dict]: ...
    def create_event(self, title: str, start: dt.datetime, end: dt.datetime, location: str,
                     description: str, attendees: list[str], calendar_id: str = "primary") -> dict: ...
    def create_all_day_event(self, title: str, first_day: dt.date, last_day: dt.date, location: str,
                             description: str, calendar_id: str = "primary") -> dict: ...
    def update_event(self, calendar_id: str, event_id: str, changes: dict) -> dict: ...
    def delete_event(self, calendar_id: str, event_id: str) -> None: ...
    def calendar_id(self, name: str) -> str | None: ...


def _fmt(when: dict, tz: ZoneInfo) -> str:
    if "dateTime" in when:
        return dt.datetime.fromisoformat(when["dateTime"]).astimezone(tz).strftime("%a %b %-d, %-I:%M %p")
    return dt.date.fromisoformat(when["date"]).strftime("%a %b %-d") + " (all day)"


def _iso(when: dict, tz: ZoneInfo) -> str:
    """Machine-readable start/end: local ISO datetime, or YYYY-MM-DD for all-day events."""
    if "dateTime" in when:
        return dt.datetime.fromisoformat(when["dateTime"]).astimezone(tz).isoformat()
    return when["date"]


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
                    "calendar_id": cal["id"],
                    "title": ev.get("summary", "(no title)"),
                    "start": _fmt(ev["start"], self.tz),
                    "end": _fmt(ev["end"], self.tz),
                    "start_iso": _iso(ev["start"], self.tz),
                    "end_iso": _iso(ev["end"], self.tz),
                    "all_day": "dateTime" not in ev["start"],
                    "calendar": cal["name"],
                    "location": ev.get("location", ""),
                    "description": (ev.get("description") or "")[:500],
                }))
        found.sort(key=lambda pair: pair[0])
        return [e for _, e in found[:limit]]

    def create_event(self, title, start, end, location, description, attendees,
                     calendar_id: str = "primary") -> dict:
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
            calendarId=calendar_id, body=body, sendUpdates="all" if attendees else "none"
        ).execute()
        return {"id": ev["id"], "link": ev.get("htmlLink", "")}

    def create_all_day_event(self, title: str, first_day: dt.date, last_day: dt.date, location: str,
                             description: str, calendar_id: str = "primary") -> dict:
        body = {"summary": title, "start": {"date": first_day.isoformat()},
                "end": {"date": (last_day + dt.timedelta(days=1)).isoformat()}}   # Google's end is exclusive
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        ev = self.svc.events().insert(calendarId=calendar_id, body=body, sendUpdates="none").execute()
        return {"id": ev["id"], "link": ev.get("htmlLink", "")}

    def update_event(self, calendar_id: str, event_id: str, changes: dict) -> dict:
        """changes may hold title, start, end (datetimes), location. Only those fields change."""
        body: dict = {}
        if changes.get("title"):
            body["summary"] = changes["title"]
        if changes.get("location"):
            body["location"] = changes["location"]
        for key in ("start", "end"):
            if changes.get(key):
                body[key] = {"dateTime": changes[key].isoformat(), "timeZone": self.tz_name}
        if not body:
            raise ValueError("nothing to change")
        ev = self.svc.events().patch(calendarId=calendar_id, eventId=event_id, body=body,
                                     sendUpdates="none").execute()
        return {"id": ev["id"], "link": ev.get("htmlLink", "")}

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.svc.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="none").execute()
