import datetime as dt
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app import calcheck, hub
from app.config import Settings
from app.main import create_app
from app.todoist_client import Todoist, TodoistError
from tests.fakes import FakeLLM

TZ = ZoneInfo("America/Los_Angeles")
NOW = dt.datetime(2026, 11, 5, 9, 0, tzinfo=TZ)            # a Thursday
ALIASES = hub.parse_aliases("vc elite=Elliott")

# A synthetic Classroom guardian summary in the real layout.
SUMMARY = """Weekly summary for Elliott Cardona
Oct 30 – Nov 6, 2026
Missing from last week
American History Period 3

Workbook p 76-77
Due Nov 3

Workbook p 78 Ch 3
Classwork
Due Nov 3
Due next week
ELA 8 - Period 4

Unit Assessment
We will have an assessment in class.

Content: chapters 3-6
Due Nov 9
MATH 8

Roots worksheet
COMPLETE ALL PROBLEMS
Due Nov 10
American History Period 3
New assignments

Old classwork
Due Oct 29
Posted on Oct 27, 2026 by a teacher
"""


# --- matching ---------------------------------------------------------------------------
@pytest.mark.parametrize("title,who", [
    ("Brooks flag football practice", ["brooks"]),
    ("Snacks for Elliott's soccer game", ["elliott"]),
    ("Give gypsy flea meds", ["gypsy"]),
    ("Boys training", ["brooks", "elliott"]),
    ("VC elite practice", ["elliott"]),
    ("Phillip / Dentist cleaning", ["phillip"]),
    ("CeCe off", ["cece"]),
    ("Move the car!", []),
    ("Brookside farm visit", []),            # whole words only
])
def test_people_in_titles(title, who):
    assert hub.people_in(title, ALIASES) == who


@pytest.mark.parametrize("title,kind", [
    ("Flight: LAX to AUS", "flight"),
    ("Pierce PT", "appointment"),
    ("Phillip / Dentist cleaning", "appointment"),
    ("Taryn in Irvine", "travel"),
    ("Phillip-NYC", "travel"),
    ("Phillip work lunch", "event"),
    ("Brooks basketball game", "event"),
])
def test_kind_of(title, kind):
    people = hub.people_in(title, ALIASES)
    assert hub.kind_of(title, people, False, 1) == kind


def test_multi_day_parent_event_is_travel():
    assert hub.kind_of("Phillip conference week", ["phillip"], True, 3) == "appointment"  # "conference" wins
    assert hub.kind_of("Phillip offsite", ["phillip"], True, 3) == "travel"


def test_kitchen_title_hides_money_and_private_words():
    assert hub.kitchen_title("Pay rent - $1,162.44", []) == "Pay rent - $…"
    assert hub.kitchen_title("Botox Day Irvine", ["botox"]) == "Private"


def test_aliases_ignore_unknown_people():
    al = hub.parse_aliases("coach=Nobody; mom=Taryn")
    assert "coach" not in al and al["mom"] == ["taryn"] and al["boys"] == ["brooks", "elliott"]


# --- parsing ----------------------------------------------------------------------------
def test_classroom_summary_parsing():
    out = hub.parse_classroom_summary(SUMMARY, dt.date(2026, 11, 6))
    assert out["missing"] == [
        {"class": "American History Period 3", "title": "Workbook p 76-77", "due": "2026-11-03"},
        {"class": "American History Period 3", "title": "Workbook p 78 Ch 3", "due": "2026-11-03"}]
    assert [(i["class"], i["title"], i["due"]) for i in out["due"]] == [
        ("ELA 8 - Period 4", "Unit Assessment", "2026-11-09"), ("MATH 8", "Roots worksheet", "2026-11-10")]


def test_due_dates_cross_new_year():
    assert hub._due_date("Jan", "5", dt.date(2026, 12, 20)) == dt.date(2027, 1, 5)
    assert hub._due_date("Dec", "18", dt.date(2027, 1, 3)) == dt.date(2026, 12, 18)


@pytest.mark.parametrize("subject,status", [
    ("Your Sunbasket order is on its way", "coming"),
    ("You skipped your delivery", "skipped"),
    ("New recipes this week", "unknown"),
])
def test_sunbasket(subject, status):
    assert hub.sunbasket_status([{"id": "s1", "subject": subject, "snippet": ""}])["status"] == status


def test_sunbasket_newest_email_wins():
    emails = [{"id": "new", "subject": "You skipped next week", "snippet": ""},
              {"id": "old", "subject": "Your order is confirmed", "snippet": ""}]
    assert hub.sunbasket_status(emails)["status"] == "skipped"


# --- fakes for a full build -----------------------------------------------------------------
def cal_ev(eid, title, start, end, all_day=False, calendar="Family"):
    return {"id": eid, "calendar_id": "fam", "title": title, "start_iso": start, "end_iso": end,
            "all_day": all_day, "calendar": calendar}


class HubCal:
    def __init__(self):
        self.events = [
            cal_ev("1", "Brooks flag football practice", "2026-11-02T15:30:00-08:00", "2026-11-02T17:30:00-08:00"),
            cal_ev("2", "Phillip-NYC", "2026-11-04", "2026-11-07", all_day=True),
            cal_ev("3", "Pierce PT", "2026-11-05T10:00:00-08:00", "2026-11-05T10:45:00-08:00"),
            cal_ev("4", "Move the car!", "2026-11-05T13:00:00-08:00", "2026-11-05T13:00:00-08:00"),
            cal_ev("5", "Veterans Day", "2026-11-11", "2026-11-12", all_day=True, calendar="Holidays in United States"),
            cal_ev("6", "Pay rent $2,000", "2026-11-06T09:00:00-08:00", "2026-11-06T09:30:00-08:00"),
            cal_ev("7", "Work standup", "2026-11-06T09:00:00-08:00", "2026-11-06T09:30:00-08:00", calendar="Work"),
        ]
        self.queries = []

    def list_events(self, start, end, limit=50):
        self.queries.append((start, end))
        return self.events


class HubGmail:
    def __init__(self):
        self.searches = []

    def search(self, query, limit):
        self.searches.append(query)
        if "sunbasket" in query:
            return [{"id": "sb", "subject": "Your Sunbasket order has shipped", "snippet": "", "date": ""}]
        if "Weekly summary for Elliott" in query:
            return [{"id": "ws", "subject": "Weekly summary for Elliott Cardona", "date": "Fri, 30 Oct 2026"}]
        if "Weekly summary for Brooks" in query:
            return []
        if "from:smmusd.org" in query:
            return [{"id": "t1", "subject": "Math 6: Week of November 2", "from": "Teacher", "date": "x"}]
        if "aeries" in query:
            return [{"id": "a1", "subject": "Brooks: missing assignment", "snippet": "", "date": "x"}]
        return []

    def read(self, message_id, body_limit=4000):
        return {"id": message_id, "body": SUMMARY}


class FakeTodoist:
    def __init__(self):
        self.closed, self.added = [], []
        self.data = {
            "p-fam": [{"id": "t1", "content": "Sign permission slip", "labels": ["Brooks"], "due": {"date": "2026-11-06"}},
                      {"id": "t2", "content": "Pack soccer bag", "labels": ["elliott"], "due": {"date": "2026-11-03"}},
                      {"id": "t3", "content": "Renew passports", "labels": [], "due": None},
                      {"id": "t4", "content": "Next month thing", "labels": ["Taryn"], "due": {"date": "2026-12-20"}}],
            "p-cece": [{"id": "c1", "content": "Pierce's diapers", "labels": [], "due": None}],
            "p-gro": [{"id": "g1", "content": "Ranch dressing", "section_id": "s-pantry"},
                      {"id": "g2", "content": "Butter", "section_id": "s-dairy"},
                      {"id": "g3", "content": "Bananas", "section_id": None}],
            "p-din": [{"id": "d1", "content": "Sheet-pan chicken", "due": {"date": "2026-11-03"}, "labels": []},
                      {"id": "d2", "content": "Sunbasket: salmon bowls", "due": {"date": "2026-11-04"}, "labels": []},
                      {"id": "d3", "content": "Last week", "due": {"date": "2026-10-28"}, "labels": []}],
        }

    def project_ids(self, names):
        ids = {"family": "p-fam", "cece": "p-cece", "groceries": "p-gro", "dinners": "p-din"}
        return {n: ids[n.lower()] for n in names if n.lower() in ids}

    def tasks(self, pid):
        return self.data[pid]

    def sections(self, pid):
        return {"s-pantry": "Pantry", "s-dairy": "Dairy & Eggs"}

    def task(self, tid):
        for pid, lst in self.data.items():
            for t in lst:
                if t["id"] == tid:
                    return {**t, "project_id": pid}
        return {"id": tid, "project_id": "p-other"}

    def close(self, tid):
        self.closed.append(tid)

    def add(self, content, project_id, labels=None, due_string="", section_id=""):
        self.added.append((content, project_id, labels, due_string))
        return {"id": "new"}


class Sources:
    def __init__(self, todoist=None, broken_calendar=False):
        self._cal, self._gmail, self._todoist, self.broken = HubCal(), HubGmail(), todoist, broken_calendar

    def calendar(self):
        if self.broken:
            raise RuntimeError("Google sign-in expired")
        return self._cal

    def gmail(self):
        return self._gmail

    def todoist(self):
        return self._todoist


def cfg():
    return hub.HubConfig(aliases=ALIASES, hide_words=[], skip_calendars=("Work",))


def test_build_week():
    out = hub.build(Sources(FakeTodoist()), cfg(), now=NOW)
    assert out["week_start"] == "2026-11-02" and out["today"] == "2026-11-05" and not out["errors"]
    days = {d["date"]: [e["title"] for e in d["events"]] for d in out["days"]}
    assert days["2026-11-02"] == ["Brooks flag football practice"]
    # all-day trip spans Wed-Fri (end date is exclusive), shown first on each day
    assert days["2026-11-04"][0] == days["2026-11-06"][0] == "Phillip-NYC" and "Phillip-NYC" not in days["2026-11-07"]
    assert "Pay rent $…" in days["2026-11-06"] and "Work standup" not in days["2026-11-06"]
    assert [t["title"] for t in out["banner"]["travel"]] == ["Phillip-NYC"]
    assert [a["title"] for a in out["banner"]["appointments_today"]] == ["Pierce PT"]
    untagged = [e["title"] for e in out["untagged"]]
    assert "Move the car!" in untagged and "Veterans Day" not in untagged     # holidays never flagged
    assert out["sunbasket"]["status"] == "coming"


def test_build_homework():
    out = hub.build(Sources(FakeTodoist()), cfg(), now=NOW)
    e = out["homework"]["elliott"]
    assert len(e["missing"]) == 2 and [i["title"] for i in e["due"]] == ["Unit Assessment", "Roots worksheet"]
    b = out["homework"]["brooks"]
    assert b["missing"] == [] and [u["subject"] for u in b["updates"]] == [
        "Math 6: Week of November 2", "Aeries: Brooks: missing assignment"]


def test_build_todoist():
    out = hub.build(Sources(FakeTodoist()), cfg(), now=NOW)
    assert [t["content"] for t in out["tasks"]["brooks"]] == ["Sign permission slip"]
    assert out["tasks"]["elliott"][0]["overdue"] is True
    assert [t["content"] for t in out["tasks"]["family"]] == ["Renew passports"]
    assert out["tasks"]["taryn"] == []                       # due after this week: hidden
    assert [t["content"] for t in out["tasks"]["cece"]] == ["Pierce's diapers"]
    assert [g["section"] for g in out["groceries"]] == ["Dairy & Eggs", "Pantry", "Other"]
    assert out["dinners"]["2026-11-04"][0]["sunbasket"] is True and "2026-10-28" not in out["dinners"]


def test_each_source_fails_on_its_own():
    out = hub.build(Sources(None, broken_calendar=True), cfg(), now=NOW)
    assert "calendar" in out["errors"] and "todoist" in out["errors"]
    assert "set-todoist-token" in out["errors"]["todoist"]
    assert out["sunbasket"]["status"] == "coming" and out["homework"]["elliott"]["due"]


def test_next_week_offset():
    out = hub.build(Sources(FakeTodoist()), cfg(), offset=1, now=NOW)
    assert out["week_start"] == "2026-11-09"
    assert hub.build(Sources(FakeTodoist()), cfg(), offset=7, now=NOW)["week_start"] == "2026-11-09"  # capped


# --- API ------------------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path):
    s = Settings(token="agent-secret", dry_run=True, max_trash_per_run=1, lookback_hours=24, triage_at="",
                 data_dir=tmp_path, morning_at="", followup_check_minutes=0, budget_sync_at="",
                 hub_token="hub-secret", hub_aliases="vc elite=Elliott")
    todo = FakeTodoist()
    app = create_app(s, gmail=HubGmail(), calendar=HubCal(), llm=FakeLLM(), todoist=todo)
    with TestClient(app) as c:
        yield c, todo


HUB = {"Authorization": "Bearer hub-secret"}


def test_hub_token_opens_hub_only(api):
    c, _ = api
    assert c.get("/api/hub").status_code == 401
    r = c.get("/api/hub", headers=HUB)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert c.get("/api/hub", headers={"Authorization": "Bearer agent-secret"}).status_code == 200
    for path in ("/api/status", "/api/chat", "/api/budget", "/api/morning", "/api/actions"):
        assert c.get(path, headers=HUB).status_code == 401, path


def test_hub_page_served_without_caching(api):
    c, _ = api
    page = c.get("/hub")
    assert "Cardona Family" in page.text and page.headers["cache-control"] == "no-store"
    assert "/static/hub.js?v=" in page.text


def test_check_off_only_hub_tasks(api):
    c, todo = api
    assert c.post("/api/hub/tasks/g1/close", headers=HUB).status_code == 200
    assert c.post("/api/hub/tasks/elsewhere/close", headers=HUB).status_code == 403
    assert todo.closed == ["g1"]


def test_add_grocery(api):
    c, todo = api
    assert c.post("/api/hub/groceries", json={"item": "  more   butter "}, headers=HUB).status_code == 200
    assert todo.added == [("more butter", "p-gro", None, "")]
    assert c.post("/api/hub/groceries", json={"item": "  "}, headers=HUB).status_code == 400


def test_hub_token_must_differ(tmp_path):
    s = Settings(token="same", dry_run=True, max_trash_per_run=1, lookback_hours=24, triage_at="",
                 data_dir=tmp_path, hub_token="same")
    with pytest.raises(RuntimeError):
        create_app(s)


def test_nothing_is_written_to_the_database(api, tmp_path):
    c, _ = api
    import sqlite3
    before = sqlite3.connect(tmp_path / "agent.sqlite3").execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    tables = [r[0] for r in sqlite3.connect(tmp_path / "agent.sqlite3").execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    counts = lambda: {t: sqlite3.connect(tmp_path / "agent.sqlite3").execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                      for t in tables}
    snapshot = counts()
    c.get("/api/hub", headers=HUB)
    c.get("/api/hub?week=1", headers=HUB)
    assert counts() == snapshot and before


# --- Todoist client ---------------------------------------------------------------------------
def test_todoist_client_pagination_and_close():
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, dict(req.url.params)))
        if req.url.path.endswith("/projects"):
            if "cursor" not in req.url.params:
                return httpx.Response(200, json={"results": [{"id": "1", "name": "Family"}], "next_cursor": "c2"})
            return httpx.Response(200, json={"results": [{"id": "2", "name": "Groceries"}], "next_cursor": None})
        if req.url.path.endswith("/close"):
            return httpx.Response(204)
        if req.method == "POST":
            return httpx.Response(200, json={"id": "9"})
        return httpx.Response(200, json=[])
    t = Todoist("tok", httpx.Client(base_url="https://api.todoist.com/api/v1", transport=httpx.MockTransport(handler)))
    assert t.project_ids(["family", "Groceries", "Dinners"]) == {"family": "1", "Groceries": "2"}
    t.close("42")
    t.add("Butter", "2", labels=["Taryn"], due_string="friday")
    assert ("POST", "/api/v1/tasks/42/close", {}) in calls


def test_todoist_bad_token_message():
    t = Todoist("tok", httpx.Client(base_url="https://x", transport=httpx.MockTransport(lambda r: httpx.Response(401))))
    with pytest.raises(TodoistError, match="set-todoist-token"):
        t.projects()


# --- calendar check -----------------------------------------------------------------------------
def test_calendar_check_query_is_targeted():
    q = calcheck.build_query(["coach@club.org"])
    assert q.startswith("newer_than:1d ") and "-category:promotions" in q and "-from:classroom.google.com" in q
    assert "from:smmusd.org" in q and "from:smprep.org" in q and "from:coach@club.org" in q
    assert "subject:(" in q and "practice" in q


class CheckGmail:
    def __init__(self):
        self.queries = []

    def search(self, q, n):
        self.queries.append((q, n))
        return [{"id": "m1", "from": "coach@club.org", "to": "t", "subject": "Practice moved to 5pm",
                 "date": "today", "snippet": "Card 4111 1111 1111 1111"}]


def test_calendar_check_note(tmp_path):
    from app.db import Database
    db = Database(tmp_path / "t.sqlite3")
    db.set_meta_text(calcheck.META_SENDERS, "club.org")
    g, cal = CheckGmail(), HubCal()
    s = Settings(token="t", dry_run=True, max_trash_per_run=1, lookback_hours=24, triage_at="", data_dir=tmp_path)
    note = calcheck.gather_note(g, cal, s, db, now=NOW)
    assert "from:club.org" in g.queries[0][0]
    start, end = cal.queries[0]
    assert (end - start).days == 31
    assert "Practice moved to 5pm" in note and "4111 1111" not in note        # card numbers are scrubbed
    assert '"calendar_id": "fam"' in note and "Brooks flag football practice" in note
    assert "Calendar check: all caught up." in note
