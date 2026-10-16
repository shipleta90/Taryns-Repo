"""What the cloud model is allowed to see.

The chat assistant runs on Claude (cloud). It may read any email or calendar event, but the
text is scrubbed on the Mac mini first: SSNs, card numbers, bank/account/routing numbers and
login codes are replaced with [hidden ...], and in money-related mail (banks, brokerages, tax,
statements, balances) dollar amounts are hidden too. The cloud model never receives them.
"""
import re

from . import safety
from .domains import domain_of_address, parse_addresses

HARD_PII = {"ssn-pattern", "card-number"}

_DIGITS = r"[*xX•.#-]*\d[\d *xX•-]{2,}\d"           # 1234, ****1234, 12-3456-78, x1234
_ACCOUNT = re.compile(
    r"(?i)(\b(?:account|acct|routing|aba|member(?:ship)?|policy|loan|card|iban|ending(?: in)?|ends in|"
    r"last (?:4|four)(?: digits)?)\b(?:\s*(?:number|no\.?|num|#|id))?[\s:#]*(?:is\s+)?(?:in\s+)?)" + _DIGITS
)
_CODE = re.compile(
    r"(?i)(\b(?:verification|security|one-time|login|sign-in|confirmation)?\s*(?:code|passcode|password|pin)\b"
    r"(?:\s*(?:is|:))?\s*)(?=[A-Za-z-]*\d)[A-Za-z0-9-]{4,}"
)
_MONEY = re.compile(r"[-+]?\$\s?\d[\d,]*(?:\.\d{1,2})?|\b\d[\d,]*\.\d{2}\s?(?:USD|dollars)\b", re.IGNORECASE)
_MONEY_TOPIC = re.compile(
    r"(?i)\b(?:balance|statement|bank|banking|brokerage|credit card|debit card|loan|mortgage|tax(?:es)?|"
    r"1099|w-?2|payroll|salary|paycheck|401\(?k\)?|\bira\b|deposit|withdrawal|transfer|net worth|"
    r"portfolio|dividend|refund)\b"
)


def _sender_domain(from_header: str) -> str:
    addrs = parse_addresses(from_header)
    return domain_of_address(addrs[0]) if addrs else ""


def _money_mail(text: str, sender_domain: str) -> bool:
    return (sender_domain in safety.FINANCIAL_DOMAINS or sender_domain.endswith(".gov")
            or bool(_MONEY_TOPIC.search(text)))


def redact(text: str, money: bool = False) -> str:
    """Replace SSNs, card/account numbers and codes (and, if money=True, dollar amounts)."""
    if not text:
        return text
    text = safety._SSN.sub("[hidden SSN]", text)

    def card(m):
        digits = re.sub(r"\D", "", m.group())
        if not (13 <= len(digits) <= 19 and safety._luhn(digits)):
            return m.group()
        return "[hidden card number]" + m.group()[len(m.group().rstrip(" -")):]
    text = safety._CARD.sub(card, text)
    text = _ACCOUNT.sub(lambda m: m.group(1) + "[hidden number]", text)
    text = _CODE.sub(lambda m: m.group(1) + "[hidden code]", text)
    if money:
        text = _MONEY.sub("[hidden amount]", text)
    return text


def _scrub(m: dict, fields: tuple[str, ...]) -> dict:
    domain = _sender_domain(m.get("from", ""))
    money = _money_mail(" ".join(str(m.get(k, "")) for k in ("subject", "snippet", "body")), domain)
    out = {}
    for k in fields:
        v = m.get(k, "")
        out[k] = redact(v, money) if k in ("subject", "snippet", "body") else v
    if any(out[k] != m.get(k, "") for k in fields):
        out["redacted"] = True
    return out


def email_summary(m: dict) -> dict:
    return _scrub(m, ("id", "from", "to", "subject", "date", "snippet"))


def email_full(m: dict) -> dict:
    return _scrub(m, ("id", "from", "to", "cc", "subject", "date", "body"))


# A thread you asked Bruce to handle gets the same treatment as any other email.
email_full_for_task = email_full


def event(e: dict) -> dict:
    out = dict(e)
    text = " ".join(str(e.get(k, "")) for k in ("title", "description", "location"))
    money = _money_mail(text, "")
    for k in ("title", "description", "location"):
        if e.get(k):
            out[k] = redact(e[k], money)
    return out


def blocked_user_text(text: str) -> bool:
    """Your own chat messages may mention anything, except numbers like an SSN or card number."""
    return bool(set(safety.assess(text).reasons) & HARD_PII)
