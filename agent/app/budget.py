"""House budget: categorizing transactions, spotting recurring charges, and the down-payment math.

Pure functions, no network. Banking data never leaves the Mac mini: categorizing unknown merchants
uses the local model only (see categorize_unknown), never Claude.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import statistics
from dataclasses import dataclass

SPEND_CATEGORIES = [
    "Groceries", "Dining", "Shopping", "Subscriptions", "Transport", "Travel", "Utilities", "Housing",
    "Health", "Kids", "Insurance", "Personal care", "Entertainment", "Gifts & donations", "Fees", "Other",
]
NON_SPEND = ["Income", "Transfer"]
CATEGORIES = SPEND_CATEGORIES + NON_SPEND

# Keyword rules checked in order against the normalized merchant. First match wins.
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Transfer", ("PAYMENT THANK YOU", "AUTOPAY", "AUTOMATIC PAYMENT", "ONLINE PAYMENT", "TRANSFER",
                  "CARD PAYMENT", "CREDIT CARD PMT", "EPAY", "MOBILE PAYMENT")),
    ("Income", ("PAYROLL", "DIRECT DEP", "DIRECT DEPOSIT", "SALARY", "INTEREST PAID", "INTEREST EARNED")),
    ("Subscriptions", ("NETFLIX", "SPOTIFY", "HULU", "DISNEY", "APPLE.COM/BILL", "APPLE COM BILL", "YOUTUBE",
                       "AMAZON PRIME", "PRIME VIDEO", "PELOTON", "NYTIMES", "NEW YORK TIMES", "ADOBE", "OPENAI",
                       "CHATGPT", "ANTHROPIC", "CLAUDE.AI", "SUBSTACK", "PATREON", "AUDIBLE", "HBO", "MAX.COM",
                       "PARAMOUNT", "PEACOCK", "SIRIUSXM", "DROPBOX", "GOOGLE STORAGE", "GOOGLE ONE", "ICLOUD",
                       "MICROSOFT 365", "CANVA", "NOTION", "DUOLINGO", "CLASSPASS", "MASTERCLASS", "WSJ", "AXIOS")),
    ("Groceries", ("TRADER JOE", "WHOLE FOODS", "WHOLEFDS", "SAFEWAY", "VONS", "RALPHS", "SPROUTS", "EREWHON",
                   "GELSON", "ALBERTSONS", "KROGER", "INSTACART", "AMAZON FRESH", "COSTCO", "SMART FINAL", "ALDI")),
    ("Dining", ("DOORDASH", "UBER EATS", "UBEREATS", "GRUBHUB", "POSTMATES", "STARBUCKS", "SWEETGREEN",
                "CHIPOTLE", "RESTAURANT", "CAFE", "COFFEE", "PIZZA", "BAKERY", "BLUE BOTTLE", "TACO",
                "SUSHI", "BURGER", "KITCHEN", "GRILL")),
    ("Transport", ("UBER", "LYFT", "SHELL", "CHEVRON", "ARCO", "MOBIL", "EXXON", "76", "PARKING", "PARKMOBILE",
                   "FASTRAK", "TESLA SUPERCHARG", "CHARGEPOINT", "METRO", "DMV", "CAR WASH")),
    ("Travel", ("AIRLINE", "AIRLINES", "DELTA", "UNITED", "AMERICAN AIR", "SOUTHWEST", "JETBLUE", "ALASKA AIR",
                "HOTEL", "MARRIOTT", "HILTON", "HYATT", "AIRBNB", "VRBO", "EXPEDIA", "HERTZ", "ENTERPRISE RENT")),
    ("Utilities", ("EDISON", "SOCALGAS", "SO CAL GAS", "LADWP", "WATER", "VERIZON", "AT&T", "ATT", "T-MOBILE",
                   "SPECTRUM", "COMCAST", "XFINITY", "ELECTRIC", "PG&E")),
    ("Housing", ("RENT", "PROPERTY", "APARTMENT", "HOA", "HOME DEPOT", "LOWES")),
    ("Health", ("CVS", "WALGREENS", "PHARMACY", "DENTAL", "DENTIST", "KAISER", "MEDICAL", "CLINIC", "OPTOM",
                "DOCTOR", "HOSPITAL", "LAB CORP", "QUEST DIAG")),
    ("Insurance", ("GEICO", "STATE FARM", "ALLSTATE", "PROGRESSIVE", "INSURANCE", "LEMONADE")),
    ("Kids", ("SCHOOL", "TUITION", "CAMP", "TEAMSNAP", "DAYCARE", "CHILDCARE", "PARENTSQUARE")),
    ("Personal care", ("SALON", "BARBER", "SPA", "NAIL", "SEPHORA", "ULTA", "FITNESS", "GYM", "EQUINOX", "YOGA")),
    ("Entertainment", ("TICKETMASTER", "AMC", "CINEMA", "THEATER", "STUBHUB", "EVENTBRITE", "STEAM")),
    ("Gifts & donations", ("DONATION", "CHARITY", "GOFUNDME", "ETSY")),
    ("Fees", ("FEE", "INTEREST CHARGE", "LATE CHARGE", "OVERDRAFT")),
    ("Shopping", ("AMAZON", "AMZN", "TARGET", "WALMART", "NORDSTROM", "MACY", "ZARA", "SKIMS", "APPLE STORE",
                  "BEST BUY", "IKEA", "NIKE", "LULULEMON", "OLD NAVY", "GAP", "TJ MAXX", "MARSHALLS")),
]

_PREFIXES = re.compile(r"^(SQ \*|SQ\*|TST\* ?|PAYPAL \*|PP\*|POS |DEBIT CARD PURCHASE |PURCHASE |CHECKCARD |"
                       r"RECURRING PAYMENT |ACH |DBT |VISA |SP \*|SP\* )+")


_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
           "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
           "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"}


def normalize_merchant(description: str) -> str:
    """Stable short merchant name: 'SQ *BLUE BOTTLE COFFEE #123 LOS ANGELES CA' -> 'BLUE BOTTLE COFFEE'."""
    d = _PREFIXES.sub("", description.upper().strip())
    d = re.sub(r"[*#]", " ", d)
    words = [w for w in d.split() if not re.search(r"\d", w) and re.search(r"[A-Z]", w)]
    if len(words) > 1 and words[-1] in _STATES:
        words = words[:-1]
    return " ".join(words[:3]) or description.strip().upper()[:40]


def _matches(key: str, merchant: str) -> bool:
    return re.search(r"(?<![A-Z])" + re.escape(key) + r"(?![A-Z])", merchant) is not None


def rule_category(merchant: str, amount: float) -> str | None:
    for category, keys in RULES:
        if any(_matches(k, merchant) for k in keys):
            return category
    if amount > 0 and (_matches("DEPOSIT", merchant) or amount >= 500):
        return "Income"
    return None


# --- recurring charges ---------------------------------------------------------------------
@dataclass
class Recurring:
    merchant: str
    category: str
    monthly: float          # typical monthly cost (positive number)
    last_charged: str       # YYYY-MM-DD
    count: int

    @property
    def yearly(self) -> float:
        return round(self.monthly * 12, 2)


# Recurring charges you could cancel or renegotiate. Groceries, dining, gas and shopping repeat too,
# but they aren't subscriptions; those show up under "running hot" instead.
CANCELLABLE = {"Subscriptions", "Personal care", "Entertainment", "Utilities", "Insurance", "Fees", "Kids",
               "Other", "Uncategorized"}


def find_recurring(txns: list[dict], today: dt.date) -> list[Recurring]:
    """Cancellable charges from the same merchant roughly every month at a similar amount (within 20%)."""
    by_merchant: dict[str, list[dict]] = {}
    for t in txns:
        if t["amount"] < 0 and t["category"] in CANCELLABLE:
            by_merchant.setdefault(t["merchant"], []).append(t)
    out = []
    for merchant, ts in by_merchant.items():
        ts = sorted(ts, key=lambda t: t["posted"])
        dates = [dt.date.fromtimestamp(t["posted"]) for t in ts]
        if len(ts) < 2 or (today - dates[-1]).days > 45:
            continue  # need repeats, and it must still be active
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        amounts = [-t["amount"] for t in ts]
        med = statistics.median(amounts)
        monthly_gaps = [g for g in gaps if 24 <= g <= 37]
        if len(monthly_gaps) < max(1, len(gaps) // 2) or any(abs(a - med) > 0.2 * med for a in amounts[-3:]):
            continue
        out.append(Recurring(merchant, ts[-1]["category"], round(med, 2), dates[-1].isoformat(), len(ts)))
    return sorted(out, key=lambda r: r.monthly, reverse=True)


# --- monthly spending ----------------------------------------------------------------------
def month_key(ts: float) -> str:
    return dt.date.fromtimestamp(ts).strftime("%Y-%m")


def spending_by_category(txns: list[dict], month: str) -> dict[str, float]:
    """Money out minus refunds, per spend category, for one month (YYYY-MM)."""
    out: dict[str, float] = {}
    for t in txns:
        if month_key(t["posted"]) == month and t["category"] not in NON_SPEND:
            out[t["category"]] = round(out.get(t["category"], 0.0) - t["amount"], 2)
    return {k: v for k, v in out.items() if abs(v) >= 0.01}


def _prev_months(month: str, n: int) -> list[str]:
    y, m = map(int, month.split("-"))
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return out


def average_by_category(txns: list[dict], month: str, n: int = 6) -> tuple[dict[str, float], int]:
    """Average monthly spend per category over up to `n` full months before `month`.
    Only months that have any transactions count, so a short history isn't diluted by empty months."""
    have_data = {month_key(t["posted"]) for t in txns}
    months = [m for m in _prev_months(month, n) if m in have_data]
    if not months:
        return {}, 0
    totals: dict[str, float] = {}
    for m in months:
        for cat, amt in spending_by_category(txns, m).items():
            totals[cat] = totals.get(cat, 0.0) + amt
    return {c: round(v / len(months), 2) for c, v in totals.items() if v / len(months) >= 1}, len(months)


def running_hot(txns: list[dict], today: dt.date) -> list[dict]:
    """Categories on pace to beat their 3-month average by 15% and at least $50 this month
    (from day 10 on; before that, only categories already over their average)."""
    month = today.strftime("%Y-%m")
    now = spending_by_category(txns, month)
    history = [spending_by_category(txns, m) for m in _prev_months(month, 3)]
    history = [h for h in history if h]
    if not history:
        return []
    days_in_month = (dt.date(today.year + today.month // 12, today.month % 12 + 1, 1) - dt.timedelta(days=1)).day
    # Projecting from the first few days is noise; until day 10, only flag what's already over.
    pace = days_in_month / today.day if today.day >= 10 else 1.0
    out = []
    for cat, spent in now.items():
        avg = sum(h.get(cat, 0.0) for h in history) / len(history)
        projected = spent * pace
        if avg > 0 and projected > 1.15 * avg and projected - avg >= 50:
            out.append({"category": cat, "spent": spent, "projected": round(projected, 2),
                        "usual": round(avg, 2), "over_by": round(projected - avg, 2)})
    return sorted(out, key=lambda r: r["over_by"], reverse=True)


# --- the down-payment goal -----------------------------------------------------------------
def months_between(today: dt.date, target: dt.date) -> float:
    return max((target - today).days / 30.44, 0.0)


def condo_proceeds(settings: dict, loan_balance: float | None) -> dict | None:
    """Cash from selling the condo: sale price - selling costs - remaining mortgage.
    None if no sale price is set (then the plain "cash from sale" number is used instead)."""
    price = float(settings.get("condo_price") or 0)
    if price <= 0:
        return None
    cost_pct = float(settings.get("condo_cost_pct", 0.06))
    loan = abs(float(loan_balance if loan_balance is not None else settings.get("condo_loan_balance") or 0))
    costs = round(price * cost_pct, 2)
    return {"price": price, "costs": costs, "cost_pct": cost_pct, "loan": round(loan, 2),
            "net": round(max(price - costs - loan, 0.0), 2)}


def goal_status(settings: dict, house_balance: float, house_net_90d: float | None, today: dt.date,
                condo: dict | None = None) -> dict | None:
    price = float(settings.get("target_price") or 0)
    if price <= 0:
        return None
    down_pct = float(settings.get("down_pct", 0.20))
    closing_pct = float(settings.get("closing_pct", 0.03))
    cushion = float(settings.get("cushion") or 0)
    borrow = max(float(settings.get("borrow_amount") or 0), 0.0)     # e.g. a securities-backed line of credit
    borrow_rate = float(settings.get("borrow_rate") or 0)
    # Net cash from selling the condo: calculated if a sale price is set, else the number you typed.
    sale = condo["net"] if condo else max(float(settings.get("sale_proceeds") or 0), 0.0)
    target = dt.date.fromisoformat(settings.get("target_date") or "2027-05-01")
    goal = round(price * (down_pct + closing_pct) + cushion, 2)
    funded = house_balance + borrow + sale
    remaining = max(goal - funded, 0.0)
    months = months_between(today, target)
    needed = round(remaining / months, 2) if months >= 0.5 else round(remaining, 2)
    saving = round(house_net_90d / 3, 2) if house_net_90d is not None else None
    projected = round(funded + (saving or 0) * months, 2)
    return {
        "goal": goal, "down_payment": round(price * down_pct, 2), "closing_costs": round(price * closing_pct, 2),
        "cushion": cushion, "saved": round(house_balance, 2), "remaining": round(remaining, 2),
        "borrow": round(borrow, 2), "borrow_rate": borrow_rate, "sale_proceeds": round(sale, 2), "condo": condo,
        "borrow_monthly_interest": round(borrow * borrow_rate / 12, 2),
        "percent": round(min(funded / goal, 1.0) * 100, 1) if goal else 0.0,
        "months_left": round(months, 1), "target_date": target.isoformat(), "needed_per_month": needed,
        "saving_per_month": saving, "projected_at_target": projected,
        "on_track": None if saving is None else saving >= needed,
        "gap_per_month": None if saving is None else round(max(needed - saving, 0), 2),
    }


# --- CSV statement import ------------------------------------------------------------------
_DATE_COLS = ("transaction date", "trans. date", "date", "posted date", "posting date", "post date")
_DESC_COLS = ("description", "merchant", "payee", "name", "details", "transaction description")


def _parse_date(s: str) -> dt.date:
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d %b %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date {s!r}")


def _money(s: str) -> float:
    s = (s or "").strip().replace("$", "").replace(",", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return float(s) if s else 0.0


def parse_statement_csv(text: str, account_id: str) -> list[dict]:
    """Read a card/bank CSV export (Chase, Amex, Citi, BofA, Capital One, Apple Card style).
    Returns transactions with money OUT as negative numbers, whatever the file's convention."""
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    if not rows:
        raise ValueError("the file has no rows")
    cols = {c.lower().strip(): c for c in rows[0].keys() if c}
    date_c = next((cols[c] for c in _DATE_COLS if c in cols), None)
    desc_c = next((cols[c] for c in _DESC_COLS if c in cols), None)
    amt_c = cols.get("amount") or cols.get("amount (usd)")
    debit_c, credit_c = cols.get("debit"), cols.get("credit")
    if not date_c or not desc_c or not (amt_c or debit_c):
        raise ValueError("couldn't find date, description and amount columns in this CSV")

    parsed = []
    for r in rows:
        if not (r.get(date_c) or "").strip():
            continue
        if amt_c:
            amount = _money(r[amt_c])
        else:
            amount = _money(r.get(credit_c, "")) - abs(_money(r.get(debit_c, "")))
        parsed.append([_parse_date(r[date_c]), r[desc_c].strip(), amount])

    if amt_c:
        # Cards like Amex list purchases as positive numbers. If most rows are positive and the
        # positive rows aren't payments, flip so money out is negative.
        purchases = [p for p in parsed if "PAYMENT" not in p[1].upper()]
        if purchases and sum(1 for p in purchases if p[2] > 0) / len(purchases) > 0.7:
            for p in parsed:
                p[2] = -p[2]

    out, seen = [], {}
    for day, desc, amount in parsed:
        key = f"{account_id}|{day}|{desc}|{amount:.2f}"
        seen[key] = seen.get(key, 0) + 1       # same charge twice on one day stays two rows
        tid = hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:20]
        out.append({"id": f"csv:{tid}", "account_id": account_id,
                    "posted": dt.datetime.combine(day, dt.time(12)).timestamp(),
                    "amount": round(amount, 2), "description": desc})
    return out
