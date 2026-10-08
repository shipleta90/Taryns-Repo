import datetime as dt
from zoneinfo import ZoneInfo

from app.calendar_client import GoogleCalendar


class Call:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeSvc:
    def __init__(self, calendars, events_by_cal, list_error=None):
        self.calendars, self.events_by_cal, self.list_error = calendars, events_by_cal, list_error
        self.queried = []

    def calendarList(self):
        svc = self

        class L:
            def list(self, **kw):
                return Call({"items": svc.calendars}, svc.list_error)
        return L()

    def events(self):
        svc = self

        class E:
            def list(self, calendarId, **kw):
                svc.queried.append(calendarId)
                if calendarId == "broken":
                    return Call(error=RuntimeError("403"))
                return Call({"items": svc.events_by_cal.get(calendarId, [])})
        return E()


def cal_with(svc):
    c = GoogleCalendar.__new__(GoogleCalendar)
    c.svc, c.tz, c.tz_name = svc, ZoneInfo("America/Los_Angeles"), "America/Los_Angeles"
    return c


def ev(eid, title, start):
    return {"id": eid, "summary": title, "start": {"dateTime": start}, "end": {"dateTime": start}}


T0 = dt.datetime(2026, 10, 5, tzinfo=ZoneInfo("America/Los_Angeles"))
T1 = T0 + dt.timedelta(days=7)


def test_reads_every_selected_calendar_and_sorts_by_time():
    svc = FakeSvc(
        calendars=[{"id": "primary", "summary": "me@x.com", "selected": True},
                   {"id": "family", "summary": "Family", "selected": True},
                   {"id": "holidays", "summary": "Holidays", "selected": False},
                   {"id": "broken", "summary": "Shared", "selected": True}],
        events_by_cal={"primary": [ev("a", "Dentist", "2026-10-08T15:00:00-07:00")],
                       "family": [ev("b", "Soccer", "2026-10-06T09:00:00-07:00"),
                                  {"id": "c", "summary": "Pumpkin patch", "start": {"date": "2026-10-07"},
                                   "end": {"date": "2026-10-08"}}],
                       "holidays": [ev("h", "Columbus Day", "2026-10-12T00:00:00-07:00")]})
    out = cal_with(svc).list_events(T0, T1)
    assert [e["title"] for e in out] == ["Soccer", "Pumpkin patch", "Dentist"]
    assert out[0]["calendar"] == "Family" and out[1]["start"].endswith("(all day)")
    assert "holidays" not in svc.queried            # unticked calendars are skipped


def test_falls_back_to_main_calendar_without_list_permission():
    svc = FakeSvc([], {"primary": [ev("a", "Dentist", "2026-10-08T15:00:00-07:00")]},
                  list_error=RuntimeError("insufficient scope"))
    out = cal_with(svc).list_events(T0, T1)
    assert [e["title"] for e in out] == ["Dentist"] and svc.queried == ["primary"]
