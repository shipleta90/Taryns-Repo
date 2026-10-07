import base64
import datetime as dt
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import budget, budget_service
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.simplefin import SimpleFINClient, SimpleFINError, claim
from tests.fakes import FakeGmail, FakeLLM

TODAY = dt.date(2026, 10, 20)


def ts(y, m, d):
    return dt.datetime(y, m, d, 12).timestamp()


def tx(merchant, amount, y, m, d, category="Other", house=0):
    return {"merchant": merchant, "amount": amount, "posted": ts(y, m, d), "category": category, "is_house": house}


# ---- rules -------------------------------------------------------------------------------
@pytest.mark.parametrize("desc,amount,expected", [
    ("SQ *BLUE BOTTLE COFFEE #123 LOS ANGELES CA", -6, "Dining"),
    ("NETFLIX.COM 866-579-7172 CA", -15.49, "Subscriptions"),
    ("TRADER JOE S #021 SANTA MONICA CA", -80, "Groceries"),
    ("AMZN Mktp US*2K4L19Z82", -30, "Shopping"),
    ("PAYMENT THANK YOU - WEB", 500, "Transfer"),
    ("PARENTSQUARE INC", -10, "Kids"),          # 'RENT' must not match inside PARENTSQUARE
    ("ACME CORP PAYROLL", 4000, "Income"),
    ("SPAGHETTI HOUSE", -40, None),             # 'SPA' must not match inside SPAGHETTI
])
def test_rules(desc, amount, expected):
    assert budget.rule_category(budget.normalize_merchant(desc), amount) == expected


def test_same_merchant_normalizes_the_same_across_stores():
    a = budget.normalize_merchant("TRADER JOE S #021 SANTA MONICA CA")
    b = budget.normalize_merchant("TRADER JOE S #155 LOS ANGELES CA")
    assert a == b == "TRADER JOE S"


# ---- recurring / running hot -------------------------------------------------------------
def test_find_recurring_monthly_and_ignores_one_offs_and_stale():
    txns = [tx("NETFLIX.COM", -15.49, 2026, m, 3, "Subscriptions") for m in (7, 8, 9, 10)]
    txns += [tx("GYM", -80, 2026, m, 15, "Personal care") for m in (4, 5, 6)]       # stopped in June
    txns += [tx("IKEA", -300, 2026, 9, 1, "Shopping")]
    txns += [tx("PAYMENT THANK YOU", -900, 2026, m, 5, "Transfer") for m in (8, 9, 10)]
    txns += [tx("TRADER JOE S", -150, 2026, m, 6, "Groceries") for m in (7, 8, 9, 10)]   # not a "cut"
    rec = budget.find_recurring(txns, TODAY)
    assert [r.merchant for r in rec] == ["NETFLIX.COM"]
    assert rec[0].monthly == 15.49 and rec[0].yearly == 185.88


def test_running_hot_flags_category_over_its_usual_pace():
    txns = [tx("DOORDASH", -200, 2026, m, 10, "Dining") for m in (7, 8, 9)]
    txns += [tx("DOORDASH", -250, 2026, 10, 5, "Dining"), tx("DOORDASH", -100, 2026, 10, 12, "Dining")]
    hot = budget.running_hot(txns, TODAY)
    assert hot[0]["category"] == "Dining" and hot[0]["usual"] == 200 and hot[0]["projected"] > 500


def test_refunds_reduce_spending_and_transfers_dont_count():
    txns = [tx("TARGET", -100, 2026, 10, 2, "Shopping"), tx("TARGET", 30, 2026, 10, 4, "Shopping"),
            tx("PAYMENT THANK YOU", -1000, 2026, 10, 5, "Transfer")]
    assert budget.spending_by_category(txns, "2026-10") == {"Shopping": 70.0}


# ---- goal --------------------------------------------------------------------------------
def test_goal_status_math():
    g = budget.goal_status({"target_price": 1_000_000, "down_pct": 0.2, "closing_pct": 0.03,
                            "target_date": "2027-05-01"}, house_balance=130_000, house_net_90d=30_000,
                           today=dt.date(2026, 11, 1))
    assert g["goal"] == 230_000 and g["remaining"] == 100_000
    assert 5.8 < g["months_left"] < 6.0
    assert round(g["needed_per_month"]) in range(16_700, 17_300)
    assert g["saving_per_month"] == 10_000 and g["on_track"] is False and g["gap_per_month"] > 6000


def test_goal_needs_a_price():
    assert budget.goal_status({}, 0, None, TODAY) is None


# ---- CSV ---------------------------------------------------------------------------------
def test_chase_style_csv_negative_purchases():
    text = ("Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
            "10/01/2026,10/02/2026,NETFLIX.COM,Entertainment,Sale,-15.49,\n"
            "10/03/2026,10/04/2026,Payment Thank You-Mobile,,Payment,500.00,\n")
    rows = budget.parse_statement_csv(text, "csv:chase")
    assert [r["amount"] for r in rows] == [-15.49, 500.0]


def test_amex_style_csv_positive_purchases_are_flipped():
    text = ("Date,Description,Amount\n"
            "10/01/2026,SPOTIFY USA,11.99\n10/02/2026,WHOLEFDS SMO 10234,84.10\n"
            "10/05/2026,AUTOPAY PAYMENT - THANK YOU,-400.00\n")
    rows = budget.parse_statement_csv(text, "csv:amex")
    assert [r["amount"] for r in rows] == [-11.99, -84.10, 400.0]


def test_debit_credit_columns_and_duplicate_rows_kept():
    text = ("Posted Date,Payee,Debit,Credit\n2026-10-01,COFFEE,4.50,\n2026-10-01,COFFEE,4.50,\n"
            "2026-10-02,REFUND,,10.00\n")
    rows = budget.parse_statement_csv(text, "csv:x")
    assert [r["amount"] for r in rows] == [-4.5, -4.5, 10.0]
    assert len({r["id"] for r in rows}) == 3
    assert rows == budget.parse_statement_csv(text, "csv:x")   # stable ids: re-import doesn't duplicate


def test_bad_csv_is_explained():
    with pytest.raises(ValueError, match="columns"):
        budget.parse_statement_csv("foo,bar\n1,2\n", "csv:x")


# ---- SimpleFIN ---------------------------------------------------------------------------
ACCESS = "https://user:pass@bridge.example.org/simplefin"


def sf_transport(calls, status=200):
    def handler(req):
        calls.append(req)
        if status != 200:
            return httpx.Response(status)
        assert req.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={"errors": ["Chase needs re-auth"], "accounts": [{
            "org": {"name": "Chase"}, "id": "A1", "name": "Savings", "currency": "USD",
            "balance": "1234.56", "balance-date": 1760000000,
            "transactions": [{"id": "t1", "posted": 1760000000, "amount": "-12.50", "description": "NETFLIX.COM"},
                             {"id": "t2", "posted": 1760000100, "amount": "-5", "description": "X", "pending": True}],
        }]})
    return httpx.MockTransport(handler)


def test_simplefin_fetch_chunks_and_skips_pending():
    calls = []
    data = SimpleFINClient(ACCESS, transport=sf_transport(calls)).fetch(days=180)
    assert len(calls) == 3                                  # 180 days in 60-day chunks
    assert "user" not in str(calls[0].url)                  # credentials go in the header, not the URL
    assert data["accounts"][0] == {"id": "sf:A1", "org": "Chase", "name": "Savings", "currency": "USD",
                                   "balance": 1234.56, "balance_date": 1760000000.0}
    assert [t["id"] for t in data["transactions"]] == ["sf:A1:t1"] and data["transactions"][0]["amount"] == -12.5
    assert data["errors"] == ["Chase needs re-auth"]


def test_simplefin_403_is_explained():
    with pytest.raises(SimpleFINError, match="403"):
        SimpleFINClient(ACCESS, transport=sf_transport([], status=403)).fetch(days=10)


def test_claim_setup_token():
    token = base64.b64encode(b"https://bridge.example.org/claim/abc").decode()
    t = httpx.MockTransport(lambda req: httpx.Response(200, text=ACCESS))
    assert claim(token, transport=t) == ACCESS
    with pytest.raises(SimpleFINError):
        claim("not-a-token")


# ---- service -----------------------------------------------------------------------------
class FakeSF:
    def __init__(self, accounts, txns):
        self.data = {"accounts": accounts, "transactions": txns, "errors": []}
        self.days = []

    def fetch(self, days):
        self.days.append(days)
        return self.data


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "b.sqlite3")


def sf_data():
    accounts = [{"id": "sf:sav", "org": "Ally", "name": "House fund", "balance": 50_000, "balance_date": 0},
                {"id": "sf:card", "org": "Amex", "name": "Gold", "balance": -800, "balance_date": 0}]
    now = dt.datetime.now()
    txns = [{"id": "sf:card:1", "account_id": "sf:card", "posted": now.timestamp(), "amount": -40.0,
             "description": "SPAGHETTI HOUSE"},
            {"id": "sf:card:2", "account_id": "sf:card", "posted": now.timestamp(), "amount": -15.49,
             "description": "NETFLIX.COM"},
            {"id": "sf:sav:1", "account_id": "sf:sav", "posted": now.timestamp(), "amount": 3000.0,
             "description": "TRANSFER FROM CHECKING"}]
    return accounts, txns


def test_sync_categorizes_with_rules_then_local_model_and_keeps_user_choices(db):
    llm = FakeLLM({"SPAGHETTI HOUSE": {"categories": {"SPAGHETTI HOUSE": "Dining"}}})
    sf = FakeSF(*sf_data())
    out = budget_service.sync(sf, db, llm)
    assert sf.days == [budget_service.INITIAL_DAYS] and out["new_transactions"] == 3
    cats = {t["merchant"]: t["category"] for t in db.fin_txns()}
    assert cats == {"SPAGHETTI HOUSE": "Dining", "NETFLIX.COM": "Subscriptions", "TRANSFER FROM CHECKING": "Transfer"}
    system, user = llm.prompts[0]
    assert "SPAGHETTI HOUSE" in user and "40" not in user          # only merchant names, no amounts
    db.set_merchant_category("NETFLIX.COM", "Entertainment", "user")
    budget_service.sync(sf, db, llm)
    assert sf.days[-1] == budget_service.DAILY_DAYS
    db.set_merchant_category("NETFLIX.COM", "Subscriptions", "rule")   # rules never override you
    assert {t["merchant"]: t["category"] for t in db.fin_txns()}["NETFLIX.COM"] == "Entertainment"


def test_model_offline_leaves_items_uncategorized(db):
    budget_service.sync(FakeSF(*sf_data()), db, FakeLLM(fail=True))
    s = budget_service.summary(db)
    assert s["uncategorized"] == ["SPAGHETTI HOUSE"]


def test_summary_goal_uses_house_accounts_and_hidden_accounts_drop_out(db):
    budget_service.sync(FakeSF(*sf_data()), db, FakeLLM())
    db.set_fin_settings({"target_price": 500_000})
    assert budget_service.summary(db)["goal"]["saved"] == 0
    db.set_fin_account_flags("sf:sav", True, None)
    g = budget_service.summary(db)["goal"]
    assert g["saved"] == 50_000 and g["saving_per_month"] == 1000.0     # 3000 in over 90 days
    db.set_fin_account_flags("sf:card", None, True)
    assert all(c["category"] != "Subscriptions" for c in budget_service.summary(db)["categories"])


def test_limits_status(db):
    budget_service.sync(FakeSF(*sf_data()), db, FakeLLM())
    db.set_fin_limit("Subscriptions", 16)
    row = next(c for c in budget_service.summary(db)["categories"] if c["category"] == "Subscriptions")
    assert row["status"] == "near" and row["percent"] == 97
    db.set_fin_limit("Subscriptions", 10)
    assert next(c for c in budget_service.summary(db)["categories"] if c["category"] == "Subscriptions")["status"] == "over"


def test_csv_import_twice_does_not_duplicate(db):
    text = "Date,Description,Amount\n10/01/2026,SPOTIFY USA,11.99\n10/02/2026,WHOLEFDS SMO,84.10\n"
    first = budget_service.import_csv(db, None, "Amex Gold", text)
    again = budget_service.import_csv(db, None, "Amex Gold", text)
    assert first["new_transactions"] == 2 and again["new_transactions"] == 0
    assert first["account_id"] == "csv:amex-gold"


# ---- API ---------------------------------------------------------------------------------
def test_budget_api(tmp_path):
    s = Settings(token="secret", dry_run=True, max_trash_per_run=1, lookback_days=1, triage_at="",
                 data_dir=tmp_path, briefing_at="", morning_at="", budget_sync_at="")
    auth = {"Authorization": "Bearer secret"}
    with TestClient(create_app(s, gmail=FakeGmail([]), llm=FakeLLM(), simplefin=FakeSF(*sf_data()))) as c:
        assert c.get("/api/budget").status_code == 401
        assert c.post("/api/budget/sync", headers=auth).status_code == 202
        import time
        for _ in range(50):
            d = c.get("/api/budget", headers=auth).json()
            if d["accounts"] and not d["running"]:
                break
            time.sleep(0.05)
        assert d["connected"] and len(d["accounts"]) == 2
        d = c.post("/api/budget/settings", json={"target_price": 900000, "target_date": "2027-05-01"}, headers=auth).json()
        assert d["goal"]["goal"] == 900000 * 0.23
        assert c.post("/api/budget/settings", json={"down_pct": 20}, headers=auth).status_code == 400
        assert c.post("/api/budget/accounts/sf:sav", json={"is_house": True}, headers=auth).json()["goal"]["saved"] == 50000
        assert c.post("/api/budget/accounts/nope", json={"hidden": True}, headers=auth).status_code == 404
        assert c.post("/api/budget/limits", json={"category": "Dining", "monthly_limit": 300}, headers=auth).status_code == 200
        assert c.post("/api/budget/limits", json={"category": "Bogus", "monthly_limit": 1}, headers=auth).status_code == 400
        r = c.post("/api/budget/import", json={"account_name": "Amex", "csv": "nope"}, headers=auth)
        assert r.status_code == 400
        month = dt.date.today().strftime("%Y-%m")
        assert c.get(f"/api/budget/transactions?month={month}", headers=auth).status_code == 200


def test_running_hot_waits_for_enough_of_the_month():
    txns = [tx("DOORDASH", -200, 2026, m, 10, "Dining") for m in (7, 8, 9)]
    txns += [tx("DOORDASH", -150, 2026, 10, 2, "Dining")]
    assert budget.running_hot(txns, dt.date(2026, 10, 5)) == []          # early month: not over yet
    txns += [tx("DOORDASH", -120, 2026, 10, 4, "Dining")]
    assert budget.running_hot(txns, dt.date(2026, 10, 5))[0]["projected"] == 270   # already over: flagged


def test_planned_borrowing_counts_toward_goal_separately():
    g = budget.goal_status({"target_price": 1_000_000, "borrow_amount": 50_000, "borrow_rate": 0.06,
                            "target_date": "2027-05-01"}, house_balance=130_000, house_net_90d=None,
                           today=dt.date(2026, 11, 1))
    assert g["saved"] == 130_000 and g["borrow"] == 50_000
    assert g["remaining"] == 50_000 and g["borrow_monthly_interest"] == 250.0
    assert g["projected_at_target"] == 180_000
