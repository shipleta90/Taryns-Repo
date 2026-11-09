"""Cardona Family Hub: the week at a glance, color-coded by person.

Everything here is computed LIVE on each request from Google Calendar, Gmail and Todoist, and
nothing is written to disk or the database. Each source fails on its own: if Todoist is down,
the calendar still shows and the Todoist sections say "unavailable".
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
import re
from functools import lru_cache
from pathlib import Path
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

log = logging.getLogger("agent.hub")

# --- people ------------------------------------------------------------------------------
# Order = order of the task columns. Colors are chosen to be distinct for color-blind viewers
# too (each also has its initial on every chip).
PEOPLE = [
    {"key": "taryn", "name": "Taryn", "color": "#7c3aed", "role": "parent"},
    {"key": "phillip", "name": "Phillip", "color": "#2563eb", "role": "parent"},
    {"key": "brooks", "name": "Brooks", "color": "#16a34a", "role": "kid"},
    {"key": "elliott", "name": "Elliott", "color": "#ea580c", "role": "kid"},
    {"key": "pierce", "name": "Pierce", "color": "#ca8a04", "role": "kid"},
    {"key": "cece", "name": "Cece", "color": "#0d9488", "role": "nanny"},
    {"key": "gypsy", "name": "Gypsy", "color": "#92400e", "role": "dog"},
]
FAMILY = {"key": "family", "name": "Family", "color": "#6b7280", "role": "family"}
BY_KEY = {p["key"]: p for p in PEOPLE}
PARENTS = {"taryn", "phillip"}
KIDS = {"brooks", "elliott", "pierce"}   # their task columns show today only

# Group words that mean several people. Extra ones come from HUB_ALIASES in .env.
DEFAULT_ALIASES = {"boys": ["brooks", "elliott"], "kids": ["brooks", "elliott", "pierce"],
                   "vc elite": ["brooks"]}          # Brooks's team

# Adult things that show as "Private" on the kitchen screen (HUB_HIDE replaces this list).
# Matched at the start of a word, any case: "pay" hides "Pay numb nuts", not "display".
DEFAULT_HIDE = ("pay, numb nuts, bill, rent, mortgage, tax, invoice, interview, recruiter, botox, facial, "
                "filler, function health, blood test, lab work, therapist, counseling, obgyn, gyn, mammogram, "
                "dermatolog, lawyer, attorney, divorce, mediation, court, date night")


def parse_hide(raw: str | None) -> list[str]:
    raw = DEFAULT_HIDE if raw is None else raw
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def parse_aliases(raw: str) -> dict[str, list[str]]:
    """HUB_ALIASES="vc elite=Elliott; mom=Taryn; boys=Brooks+Elliott" -> {"vc elite": ["elliott"], ...}"""
    out = dict(DEFAULT_ALIASES)
    for part in (raw or "").split(";"):
        word, _, who = part.partition("=")
        keys = [w.strip().lower() for w in who.split("+") if w.strip().lower() in BY_KEY]
        if word.strip() and keys:
            out[word.strip().lower()] = keys
    return out


def people_in(title: str, aliases: dict[str, list[str]]) -> list[str]:
    """Person keys named in an event title, in PEOPLE order. Matches whole words in any case and
    position: "Brooks flag football", "Snacks for Elliott's game", "Give gypsy flea meds"."""
    low = (title or "").lower()
    found = {p["key"] for p in PEOPLE if re.search(rf"\b{p['key']}\b", low)}
    for word, keys in aliases.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            found.update(keys)
    return [p["key"] for p in PEOPLE if p["key"] in found]


# --- what kind of event --------------------------------------------------------------------
_APPT = re.compile(
    r"(?i)\b(dentist|dental|doctor|dr\.?|pediatric\w*|ortho\w*|appt|appointment|pt|physical therapy|therapy|"
    r"conference|check-?up|vet|groom\w*|haircut|facial|botox|health test|clinic|eye exam|optometr\w*|"
    r"allerg\w*|vaccin\w*|flu shot|blood|x-?ray|physical)\b")
_FLIGHT = re.compile(r"(?i)^\s*(flight\b|✈)|\bflight:")
_TRAVEL_WORD = re.compile(r"(?i)\b(trip|travel\w*|away|out of town)\b")
_TRAVEL_PLACE = re.compile(r"\b(?:in|to)\s+[A-Z][A-Za-z]")          # "Taryn in Irvine" (place capitalized)
_TRAVEL_DASH = re.compile(r"(?i)^\s*(taryn|phillip)\s*[-–]\s*[a-z][a-z .]{1,30}$")   # "Phillip-NYC"


def kind_of(title: str, people: list[str], all_day: bool, days: int) -> str:
    title = title or ""
    if _FLIGHT.search(title):
        return "flight"
    if _APPT.search(title):
        return "appointment"
    if set(people) & PARENTS and (_TRAVEL_WORD.search(title) or _TRAVEL_PLACE.search(title)
                                  or _TRAVEL_DASH.search(title) or (all_day and days > 1)):
        return "travel"
    return "event"


# --- quote of the day ---------------------------------------------------------------------
# A fixed, family-approved list (app/data/quotes.json). Quotes come in sets ("buddhist",
# "brene") and the days alternate between them: one day a Buddhist teacher, the next Brené
# Brown. Each set is shuffled once with a fixed seed, so every quote in a set shows once before
# any repeats. Same quote all day, on every screen.
_QUOTES_FILE = Path(__file__).parent / "data" / "quotes.json"


@lru_cache(maxsize=1)
def _quote_sets() -> list[list[dict]]:
    try:
        items = json.loads(_QUOTES_FILE.read_text())
    except Exception as exc:
        log.warning("quotes unavailable: %s", exc)
        return []
    sets: dict[str, list[dict]] = {}
    for q in items:
        if q.get("text"):
            sets.setdefault(q.get("set") or "all", []).append({"text": q["text"], "by": q.get("by", "")})
    out = []
    for name, qs in sets.items():          # file order: the first set shows on even days
        random.Random(f"20261109-{name}").shuffle(qs)
        out.append(qs)
    return out


def quote_of_the_day(day: dt.date) -> dict | None:
    sets = _quote_sets()
    if not sets:
        return None
    n = day.toordinal()
    qs = sets[n % len(sets)]
    return qs[(n // len(sets)) % len(qs)]


# --- privacy on a shared kitchen screen ----------------------------------------------------
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d{1,2})?")


def kitchen_title(title: str, hide_words: list[str]) -> str:
    """Hide dollar amounts always; replace the whole title with "Private" if it contains a word
    from HUB_HIDE (the kids and Cece can see this screen)."""
    low = (title or "").lower()
    if any(w and re.search(rf"\b{re.escape(w)}", low) for w in hide_words):
        return "Private"
    return _MONEY.sub("$…", title or "").strip()


# --- Sunbasket -----------------------------------------------------------------------------
SUNBASKET_QUERY = "from:sunbasket.com newer_than:14d"
_SB_SKIP = re.compile(r"(?i)\bskip(ped)?\b")
_SB_COMING = re.compile(r"(?i)(shipped|on its way|out for delivery|arriv|delivered|order (is )?confirmed|"
                        r"order confirmation|your (box|order|delivery)|get ready|is coming)")


def sunbasket_status(emails: list[dict]) -> dict:
    """Newest Sunbasket email decides: skipped, coming (2 dinners), or unknown."""
    for m in emails:   # Gmail returns newest first
        text = f"{m.get('subject', '')} {m.get('snippet', '')}"
        if _SB_SKIP.search(text):
            return {"status": "skipped", "text": "No Sunbasket this week", "email_id": m.get("id")}
        if _SB_COMING.search(text):
            return {"status": "coming", "text": "📦 Sunbasket arriving Monday (2 dinners)", "email_id": m.get("id")}
    return {"status": "unknown", "text": "Sunbasket: no info (no recent Sunbasket email)", "email_id": None}


# --- homework ------------------------------------------------------------------------------
KID_SCHOOLS = {
    "brooks": {"school": "Lincoln Middle School", "domain": "smmusd.org"},
    "elliott": {"school": "Saint Monica Prep", "domain": "smprep.org"},
}
AERIES_QUERY = "(from:aeries.net OR from:aeries.com) newer_than:7d"
_DUE = re.compile(r"^Due ([A-Z][a-z]{2}) (\d{1,2})$")
_NEW_SECTION = re.compile(r"^New (assignments?|announcements?|material)$")
_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                       "Nov", "Dec"], 1)}


def _due_date(mon: str, day: str, ref: dt.date) -> dt.date | None:
    if mon not in _MONTHS:
        return None
    try:
        d = dt.date(ref.year, _MONTHS[mon], int(day))
    except ValueError:
        return None
    if d < ref - dt.timedelta(days=180):     # "Jan 5" in a December summary is next year
        d = d.replace(year=ref.year + 1)
    elif d > ref + dt.timedelta(days=180):
        d = d.replace(year=ref.year - 1)
    return d


def _parse_block(lines: list[str], ref: dt.date) -> list[dict]:
    """Classroom summary block: 'Class\\n\\nTitle\\n(details...)\\nDue Oct 29\\n\\nTitle...\\nNext class'."""
    items, cls, title = [], "", None
    prev_blank, after_due = True, True
    for i, raw in enumerate(lines):
        t = raw.strip()
        if not t:
            prev_blank = True
            continue
        m = _DUE.match(t)
        if m:
            if title:
                due = _due_date(m.group(1), m.group(2), ref)
                items.append({"class": cls, "title": title[:160], "due": due.isoformat() if due else None})
            title, after_due, prev_blank = None, True, False
            continue
        next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
        if after_due and next_blank and title is None:
            cls = t[:80]
        elif prev_blank and title is None:
            title = t
        prev_blank = after_due = False
    return items


def parse_classroom_summary(body: str, ref: dt.date) -> dict:
    """Google Classroom guardian 'Weekly summary': the 'Missing from last week' and 'Due next week'
    blocks (the per-class detail after them is skipped)."""
    lines = (body or "").splitlines()
    out = {"missing": [], "due": []}

    def block(start_label: str, stop_labels: tuple[str, ...]) -> list[str]:
        try:
            i = next(k for k, l in enumerate(lines) if l.strip() == start_label)
        except StopIteration:
            return []
        seg = []
        for k in range(i + 1, len(lines)):
            t = lines[k].strip()
            if t in stop_labels:
                break
            if k + 1 < len(lines) and _NEW_SECTION.match(lines[k + 1].strip()):
                break   # a class header that starts the per-class detail
            if _NEW_SECTION.match(t) or t.startswith("Don't see a class?"):
                break
            seg.append(lines[k])
        return seg

    out["missing"] = _parse_block(block("Missing from last week", ("Due next week",)), ref)
    out["due"] = _parse_block(block("Due next week", ("Missing from last week",)), ref)
    return out


# --- dates -------------------------------------------------------------------------------
def week_start(today: dt.date, offset: int = 0) -> dt.date:
    return today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)


def _parse_iso(s: str, tz: ZoneInfo) -> tuple[dt.date, dt.datetime | None]:
    if len(s) == 10:
        return dt.date.fromisoformat(s), None
    when = dt.datetime.fromisoformat(s).astimezone(tz)
    return when.date(), when


def _time_label(when: dt.datetime | None) -> str:
    if when is None:
        return "All day"
    return when.strftime("%-I:%M %p").replace(":00 ", " ").lower().replace(" ", "")


def gmail_link(message_id: str | None) -> str | None:
    return f"https://mail.google.com/mail/u/0/#all/{message_id}" if message_id else None


# --- the build -----------------------------------------------------------------------------
@dataclass
class HubConfig:
    timezone: str = "America/Los_Angeles"
    aliases: dict = field(default_factory=lambda: dict(DEFAULT_ALIASES))
    hide_words: list = field(default_factory=list)
    projects: dict = field(default_factory=lambda: {
        "family": "Family", "cece": "Cece", "groceries": "Groceries", "dinners": "Dinners"})
    skip_calendars: tuple = ()      # calendar names never shown (e.g. a work calendar)


def _events(calendar, start: dt.date, cfg: HubConfig, tz: ZoneInfo) -> tuple[list[dict], list[dict]]:
    """(per-day buckets for the 7 days, all events) for the week starting at `start`."""
    t0 = dt.datetime.combine(start, dt.time.min, tz)
    t1 = t0 + dt.timedelta(days=7)
    days = [{"date": (start + dt.timedelta(days=i)).isoformat(), "events": []} for i in range(7)]
    flat = []
    skip = {c.lower() for c in cfg.skip_calendars}
    for e in calendar.list_events(t0, t1, limit=250):
        if e.get("calendar", "").lower() in skip:
            continue
        s_day, s_when = _parse_iso(e["start_iso"], tz)
        e_day, _ = _parse_iso(e["end_iso"], tz)
        if e.get("all_day"):
            e_day -= dt.timedelta(days=1)          # all-day end dates are exclusive
        span = max(1, (e_day - s_day).days + 1)
        title = e.get("title", "")
        people = people_in(title, cfg.aliases)
        holiday = "holiday" in e.get("calendar", "").lower()
        shown = kitchen_title(title, cfg.hide_words)
        private = shown == "Private"
        item = {
            "id": e.get("id"), "title": shown, "private": private,
            "people": people or ["family"], "untagged": not people and not holiday and not private,
            "kind": "holiday" if holiday else ("event" if private else kind_of(title, people, bool(e.get("all_day")), span)),
            "all_day": bool(e.get("all_day")), "time": _time_label(s_when),
            "start": s_day.isoformat(), "end": e_day.isoformat(), "days": span,
            "sort": s_when.isoformat() if s_when else s_day.isoformat(),
        }
        flat.append(item)
        for d in days:
            if s_day.isoformat() <= d["date"] <= e_day.isoformat():
                d["events"].append(item)
    for d in days:   # all-day first, then by time
        d["events"].sort(key=lambda x: (not x["all_day"], x["sort"]))
    return days, flat


def _banner(flat: list[dict], today: dt.date) -> dict:
    travel = [e for e in flat if e["kind"] in ("travel", "flight") and e["end"] >= today.isoformat()]
    appts_today = [e for e in flat if e["kind"] == "appointment" and e["start"] <= today.isoformat() <= e["end"]]
    return {"travel": travel, "appointments_today": appts_today}


def _homework(gmail, today: dt.date) -> dict:
    out = {}
    aeries = []
    try:
        aeries = gmail.search(AERIES_QUERY, 10)
    except Exception as exc:
        log.warning("aeries search failed: %s", exc)
    for kid, info in KID_SCHOOLS.items():
        name = BY_KEY[kid]["name"]
        entry = {"school": info["school"], "summary_date": None, "missing": [], "due": [], "updates": []}
        found = gmail.search(f'from:classroom.google.com subject:"Weekly summary for {name}" newer_than:8d', 1)
        if found:
            full = gmail.read(found[0]["id"], body_limit=40000)
            ref = today
            parsed = parse_classroom_summary(full.get("body", ""), ref)
            entry["summary_date"] = found[0].get("date")
            entry["summary_link"] = gmail_link(found[0]["id"])
            entry["missing"] = parsed["missing"]
            entry["due"] = sorted([i for i in parsed["due"] if not i["due"] or i["due"] >= today.isoformat()],
                                  key=lambda i: i["due"] or "9999")
        for m in gmail.search(f"from:{info['domain']} newer_than:7d -from:me", 8):
            entry["updates"].append({"subject": m.get("subject", "")[:140], "from": m.get("from", "")[:80],
                                     "date": m.get("date", ""), "link": gmail_link(m.get("id"))})
        for m in aeries:
            if re.search(rf"\b{kid}\b", f"{m.get('subject', '')} {m.get('snippet', '')}".lower()):
                entry["updates"].append({"subject": "Aeries: " + m.get("subject", "")[:130], "from": "Aeries",
                                         "date": m.get("date", ""), "link": gmail_link(m.get("id"))})
        out[kid] = entry
    return out


def _person_for_task(task: dict, default: str) -> str:
    labels = [l.lower() for l in task.get("labels") or []]
    for p in PEOPLE:
        if p["key"] in labels:
            return p["key"]
    return default


def _due(task: dict) -> str | None:
    due = task.get("due") or {}
    return (due.get("date") or "")[:10] or None


def _todoist(todoist, cfg: HubConfig, start: dt.date, today: dt.date) -> dict:
    end = (start + dt.timedelta(days=6)).isoformat()
    ids = todoist.project_ids(list(cfg.projects.values()))
    missing = [n for n in cfg.projects.values() if n not in ids]
    tasks: dict[str, list] = {p["key"]: [] for p in PEOPLE}
    tasks["family"] = []
    for proj_key in ("family", "cece"):
        pid = ids.get(cfg.projects[proj_key])
        if not pid:
            continue
        for t in todoist.tasks(pid):
            due = _due(t)
            if due and due > end:
                continue        # later than this week: not shown yet
            who = _person_for_task(t, "cece" if proj_key == "cece" else "family")
            if who in KIDS and due and due > today.isoformat():
                continue        # kids see only today's tasks (plus missed ones, so repeats keep coming)
            tasks[who].append({"id": t["id"], "content": t.get("content", "")[:200], "due": due,
                               "overdue": bool(due and due < today.isoformat())})
    for lst in tasks.values():
        lst.sort(key=lambda t: (t["due"] is None, t["due"] or ""))

    groceries: list[dict] = []
    gid = ids.get(cfg.projects["groceries"])
    if gid:
        names = todoist.sections(gid)
        groups: dict[str, list] = {}
        for t in todoist.tasks(gid):
            groups.setdefault(names.get(t.get("section_id") or "", "") or "Other", []).append(
                {"id": t["id"], "content": t.get("content", "")[:120]})
        order = ["Produce", "Meat & Seafood", "Dairy & Eggs", "Bakery", "Pantry", "Pantry/Dry Goods", "Frozen",
                 "Household", "Other"]
        groceries = [{"section": s, "items": groups[s]}
                     for s in sorted(groups, key=lambda s: (order.index(s) if s in order else len(order) - 1, s))]

    dinners: dict[str, list] = {}
    did = ids.get(cfg.projects["dinners"])
    if did:
        for t in todoist.tasks(did):
            due = _due(t)
            if due and start.isoformat() <= due <= end:
                text = t.get("content", "")
                sun = "sunbasket" in text.lower() or "sunbasket" in [l.lower() for l in t.get("labels") or []]
                dinners.setdefault(due, []).append({"id": t["id"], "content": text[:140], "sunbasket": sun})
    return {"tasks": tasks, "groceries": groceries, "dinners": dinners, "missing_projects": missing}


def build(sources, cfg: HubConfig, offset: int = 0, now: dt.datetime | None = None,
          from_today: bool = False) -> dict:
    """sources: object with calendar(), gmail(), todoist() factories (each may raise).
    from_today: the 7 days starting today (the small-screen "Today" view) instead of Mon-Sun."""
    tz = ZoneInfo(cfg.timezone)
    now = now or dt.datetime.now(tz)
    today = now.date()
    start = today if from_today else week_start(today, max(0, min(int(offset), 1)))
    out: dict = {
        "generated_at": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "week_start": start.isoformat(),
        "offset": max(0, min(int(offset), 1)),
        "people": PEOPLE + [FAMILY],
        "quote": quote_of_the_day(today),
        "days": [{"date": (start + dt.timedelta(days=i)).isoformat(), "events": []} for i in range(7)],
        "banner": {"travel": [], "appointments_today": []},
        "untagged": [],
        "sunbasket": {"status": "unknown", "text": "Sunbasket: no info"},
        "homework": {},
        "tasks": {}, "groceries": [], "dinners": {}, "missing_projects": [],
        "errors": {},
    }

    def attempt(name, fn):
        try:
            fn()
        except Exception as exc:  # each source fails on its own
            log.warning("hub %s failed: %s", name, exc)
            out["errors"][name] = str(exc)[:200]

    def calendar_part():
        days, flat = _events(sources.calendar(), start, cfg, tz)
        out["days"] = days
        out["banner"] = _banner(flat, today)
        out["untagged"] = [e for e in flat if e["untagged"]]

    def gmail_part():
        g = sources.gmail()
        out["sunbasket"] = sunbasket_status(g.search(SUNBASKET_QUERY, 10))

    def homework_part():
        out["homework"] = _homework(sources.gmail(), today)

    def todoist_part():
        t = sources.todoist()
        if t is None:
            raise RuntimeError("Todoist isn't connected yet. On the Mac mini run: "
                               "python -m app.secrets set-todoist-token")
        out.update(_todoist(t, cfg, start, today))

    attempt("calendar", calendar_part)
    attempt("sunbasket", gmail_part)
    attempt("homework", homework_part)
    attempt("todoist", todoist_part)
    return out
