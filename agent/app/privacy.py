"""What the cloud model is allowed to see.

The chat assistant runs on Claude (cloud). Before any email or calendar data is handed to it,
it passes through these filters. Anything health, legal, financial or SSN/card-like is
withheld: the cloud model learns only that a private item exists (and, for calendar events,
when it is, so scheduling still works).
"""
from . import safety
from .domains import domain_of_address, parse_addresses

WITHHELD = "Private (health, legal or financial). Kept on the Mac mini; ask the user to open it themselves."
HARD_PII = {"ssn-pattern", "card-number"}


def _sender_domain(from_header: str) -> str:
    addrs = parse_addresses(from_header)
    return domain_of_address(addrs[0]) if addrs else ""


def email_summary(m: dict) -> dict:
    sens = safety.assess(f"{m.get('subject', '')}\n{m.get('snippet', '')}", _sender_domain(m.get("from", "")))
    if sens.sensitive:
        return {"id": m["id"], "date": m.get("date", ""), "private": True, "note": WITHHELD}
    return {k: m.get(k, "") for k in ("id", "from", "to", "subject", "date", "snippet")}


def email_full(m: dict) -> dict:
    text = f"{m.get('subject', '')}\n{m.get('body', '')}"
    if safety.assess(text, _sender_domain(m.get("from", ""))).sensitive:
        return {"id": m["id"], "date": m.get("date", ""), "private": True, "note": WITHHELD}
    return {k: m.get(k, "") for k in ("id", "from", "to", "cc", "subject", "date", "body")}


def event(e: dict) -> dict:
    text = f"{e.get('title', '')}\n{e.get('description', '')}\n{e.get('location', '')}\n{e.get('calendar', '')}"
    if safety.assess(text).sensitive:
        return {"id": e["id"], "title": "Private appointment", "start": e["start"], "end": e["end"],
                "private": True}
    return e


def blocked_user_text(text: str) -> bool:
    """Your own chat messages may mention anything, except numbers like an SSN or card number."""
    return bool(set(safety.assess(text).reasons) & HARD_PII)
