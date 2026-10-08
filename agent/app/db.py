"""SQLite state: engaged domains, the action log (for undo), and run history."""
import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS engaged_domains (
    domain TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS engaged_addresses (
    address TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    message_id TEXT NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    action TEXT NOT NULL,          -- trash | label | skip
    reason TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    undone INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS actions_run ON actions(run_id);
CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    model TEXT NOT NULL,
    items_json TEXT NOT NULL,
    note TEXT,
    overview TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,              -- user | assistant (API roles; tool results are role=user)
    content_json TEXT NOT NULL,      -- exactly what is sent to / returned by the API (append-only)
    display_text TEXT,               -- what the person typed, for the chat screen
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_conv ON chat_messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    chat_message_id INTEGER NOT NULL,  -- assistant message that proposed it
    kind TEXT NOT NULL,                -- email | event
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | done | rejected | failed
    result TEXT,
    noted INTEGER NOT NULL DEFAULT 0,  -- outcome already reported back to the model
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS morning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    model TEXT NOT NULL,
    markdown TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS fin_accounts (
    id TEXT PRIMARY KEY,
    org TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    balance REAL,                 -- NULL for CSV-imported accounts (no balance in a statement export)
    balance_date REAL,
    source TEXT NOT NULL,         -- simplefin | csv
    is_house INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    is_condo_loan INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fin_txns (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    posted REAL NOT NULL,
    amount REAL NOT NULL,         -- money out is negative
    description TEXT NOT NULL,
    merchant TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fin_txns_posted ON fin_txns(posted);
CREATE TABLE IF NOT EXISTS fin_merchants (
    merchant TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    source TEXT NOT NULL          -- rule | local_model | user
);
CREATE TABLE IF NOT EXISTS fin_limits (
    category TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS fin_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    finished_at REAL,
    dry_run INTEGER NOT NULL,
    examined INTEGER NOT NULL DEFAULT 0,
    trashed INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
"""


class Database:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(briefings)")}
        if "overview" not in cols:  # databases created before the overview existed
            with self.conn:
                self.conn.execute("ALTER TABLE briefings ADD COLUMN overview TEXT")
        acct_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(fin_accounts)")}
        if "is_condo_loan" not in acct_cols:
            with self.conn:
                self.conn.execute("ALTER TABLE fin_accounts ADD COLUMN is_condo_loan INTEGER NOT NULL DEFAULT 0")

    # engaged senders (refreshed weekly; timestamp lives in meta so an empty set still counts)
    def replace_engaged(self, domains: Iterable[str], addresses: Iterable[str]) -> None:
        now = time.time()
        with self.conn:
            self.conn.execute("DELETE FROM engaged_domains")
            self.conn.execute("DELETE FROM engaged_addresses")
            self.conn.executemany(
                "INSERT OR IGNORE INTO engaged_domains(domain, reason, updated_at) VALUES (?,?,?)",
                [(d, "sent/starred", now) for d in domains],
            )
            self.conn.executemany(
                "INSERT OR IGNORE INTO engaged_addresses(address) VALUES (?)", [(a,) for a in addresses]
            )
            self.conn.execute(
                "INSERT INTO meta(key, value) VALUES ('engaged_refreshed_at', ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now,)
            )

    def engaged_domains(self) -> set[str]:
        return {r["domain"] for r in self.conn.execute("SELECT domain FROM engaged_domains")}

    def engaged_addresses(self) -> set[str]:
        return {r["address"] for r in self.conn.execute("SELECT address FROM engaged_addresses")}

    def engaged_age_seconds(self) -> float | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key='engaged_refreshed_at'").fetchone()
        return None if row is None else time.time() - row["value"]

    # runs
    def start_run(self, dry_run: bool) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs(started_at, dry_run) VALUES (?,?)", (time.time(), int(dry_run))
            )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, examined: int, trashed: int, error: str | None = None) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished_at=?, examined=?, trashed=?, error=? WHERE id=?",
                (time.time(), examined, trashed, error, run_id),
            )

    def last_run(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    # actions
    def log_action(self, run_id: int, message_id: str, sender: str, subject: str,
                   action: str, reason: str, dry_run: bool) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO actions(run_id, message_id, sender, subject, action, reason, dry_run, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (run_id, message_id, sender, subject, action, reason, int(dry_run), time.time()),
            )
        return int(cur.lastrowid)

    def recent_actions(self, limit: int = 100, action: str | None = None) -> list[dict]:
        sql = "SELECT * FROM actions"
        args: list = []
        if action:
            sql += " WHERE action=?"
            args.append(action)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.conn.execute(sql, args)]

    def get_action(self, action_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        return dict(row) if row else None

    def mark_undone(self, action_id: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE actions SET undone=1 WHERE id=?", (action_id,))

    # briefings
    def save_briefing(self, model: str, items: list[dict], note: str | None = None,
                      overview: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO briefings(created_at, model, items_json, note, overview) VALUES (?,?,?,?,?)",
                (time.time(), model, json.dumps(items), note, overview),
            )
        return int(cur.lastrowid)

    def latest_briefing(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        out = dict(row)
        out["items"] = json.loads(out.pop("items_json"))
        return out

    # small key/value settings
    def set_meta(self, key: str, value: float) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)"
                              " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_meta(self, key: str) -> float | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return None if row is None else float(row["value"])

    # chat (append-only: rows are never edited or deleted, see assistant.py)
    def add_chat(self, conversation_id: int, role: str, content: list, display_text: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO chat_messages(conversation_id, role, content_json, display_text, created_at)"
                " VALUES (?,?,?,?,?)",
                (conversation_id, role, json.dumps(content), display_text, time.time()),
            )
        return int(cur.lastrowid)

    def chat_history(self, conversation_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM chat_messages WHERE conversation_id=? ORDER BY id", (conversation_id,))
        return [dict(r, content=json.loads(r["content_json"])) for r in rows]

    def latest_conversation(self) -> tuple[int, float] | None:
        row = self.conn.execute(
            "SELECT conversation_id, MAX(created_at) AS t FROM chat_messages "
            "GROUP BY conversation_id ORDER BY conversation_id DESC LIMIT 1").fetchone()
        return (int(row["conversation_id"]), float(row["t"])) if row else None

    def new_conversation_id(self) -> int:
        row = self.conn.execute("SELECT MAX(conversation_id) AS m FROM chat_messages").fetchone()
        return int(row["m"] or 0) + 1

    def add_proposal(self, conversation_id: int, chat_message_id: int, kind: str, payload: dict) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO proposals(conversation_id, chat_message_id, kind, payload_json, created_at)"
                " VALUES (?,?,?,?,?)",
                (conversation_id, chat_message_id, kind, json.dumps(payload), time.time()),
            )
        return int(cur.lastrowid)

    def get_proposal(self, proposal_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        return dict(row, payload=json.loads(row["payload_json"])) if row else None

    def proposals_for(self, conversation_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE conversation_id=? ORDER BY id", (conversation_id,))
        return [dict(r, payload=json.loads(r["payload_json"])) for r in rows]

    def claim_proposal(self, proposal_id: int) -> bool:
        """Atomically move pending -> working so a double tap can't send twice."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE proposals SET status='working' WHERE id=? AND status='pending'", (proposal_id,))
        return cur.rowcount == 1

    def finish_proposal(self, proposal_id: int, status: str, result: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE proposals SET status=?, result=? WHERE id=?",
                              (status, result, proposal_id))

    def unnoted_outcomes(self, conversation_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM proposals WHERE conversation_id=? AND status IN ('done','rejected','failed')"
            " AND noted=0 ORDER BY id", (conversation_id,))
        return [dict(r, payload=json.loads(r["payload_json"])) for r in rows]

    def mark_noted(self, ids: list[int]) -> None:
        with self.conn:
            self.conn.executemany("UPDATE proposals SET noted=1 WHERE id=?", [(i,) for i in ids])

    # chief-of-staff morning briefing
    def save_morning(self, model: str, markdown: str, sources: list[dict], note: str | None = None) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO morning(created_at, model, markdown, sources_json, note) VALUES (?,?,?,?,?)",
                (time.time(), model, markdown, json.dumps(sources), note),
            )
        return int(cur.lastrowid)

    def latest_morning(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM morning ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        out = dict(row)
        out["sources"] = json.loads(out.pop("sources_json"))
        return out

    # budget (all local; never sent to the cloud model)
    def upsert_fin_account(self, a: dict, source: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO fin_accounts(id, org, name, currency, balance, balance_date, source)"
                " VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET org=excluded.org, name=excluded.name,"
                " currency=excluded.currency, balance=excluded.balance, balance_date=excluded.balance_date",
                (a["id"], a.get("org", ""), a["name"], a.get("currency", "USD"), a.get("balance"),
                 a.get("balance_date"), source))

    def fin_accounts(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM fin_accounts ORDER BY org, name")]

    def set_fin_account_flags(self, account_id: str, is_house: bool | None, hidden: bool | None,
                              is_condo_loan: bool | None = None) -> bool:
        def flag(v):
            return None if v is None else int(v)
        with self.conn:
            cur = self.conn.execute(
                "UPDATE fin_accounts SET is_house=COALESCE(?, is_house), hidden=COALESCE(?, hidden),"
                " is_condo_loan=COALESCE(?, is_condo_loan) WHERE id=?",
                (flag(is_house), flag(hidden), flag(is_condo_loan), account_id))
        return cur.rowcount == 1

    def add_fin_txns(self, txns: list[dict]) -> int:
        """Insert new transactions; ones already stored (same id) are left untouched."""
        with self.conn:
            before = self.conn.total_changes
            self.conn.executemany(
                "INSERT OR IGNORE INTO fin_txns(id, account_id, posted, amount, description, merchant)"
                " VALUES (?,?,?,?,?,?)",
                [(t["id"], t["account_id"], t["posted"], t["amount"], t["description"], t["merchant"]) for t in txns])
            return self.conn.total_changes - before

    def fin_txns(self, since: float = 0) -> list[dict]:
        """Transactions from visible accounts, with their category (Uncategorized if none yet)."""
        rows = self.conn.execute(
            "SELECT t.*, COALESCE(m.category, 'Uncategorized') AS category, a.is_house"
            " FROM fin_txns t JOIN fin_accounts a ON a.id = t.account_id"
            " LEFT JOIN fin_merchants m ON m.merchant = t.merchant"
            " WHERE a.hidden = 0 AND t.posted >= ? ORDER BY t.posted DESC", (since,))
        return [dict(r) for r in rows]

    def merchants_without_category(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT t.merchant FROM fin_txns t LEFT JOIN fin_merchants m ON m.merchant = t.merchant"
            " WHERE m.merchant IS NULL")
        return [r["merchant"] for r in rows]

    def set_merchant_category(self, merchant: str, category: str, source: str) -> None:
        """A choice you made yourself is never overwritten by rules or the model."""
        with self.conn:
            if source == "user":
                self.conn.execute(
                    "INSERT INTO fin_merchants(merchant, category, source) VALUES (?,?,?)"
                    " ON CONFLICT(merchant) DO UPDATE SET category=excluded.category, source=excluded.source",
                    (merchant, category, source))
            else:
                self.conn.execute(
                    "INSERT INTO fin_merchants(merchant, category, source) VALUES (?,?,?)"
                    " ON CONFLICT(merchant) DO UPDATE SET category=excluded.category, source=excluded.source"
                    " WHERE fin_merchants.source != 'user'", (merchant, category, source))

    def fin_limits(self) -> dict[str, float]:
        return {r["category"]: r["monthly_limit"] for r in self.conn.execute("SELECT * FROM fin_limits")}

    def set_fin_limit(self, category: str, monthly_limit: float | None) -> None:
        with self.conn:
            if not monthly_limit:
                self.conn.execute("DELETE FROM fin_limits WHERE category=?", (category,))
            else:
                self.conn.execute("INSERT INTO fin_limits(category, monthly_limit) VALUES (?,?)"
                                  " ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit",
                                  (category, monthly_limit))

    def fin_settings(self) -> dict:
        return {r["key"]: json.loads(r["value"]) for r in self.conn.execute("SELECT * FROM fin_settings")}

    def set_fin_settings(self, values: dict) -> None:
        with self.conn:
            self.conn.executemany(
                "INSERT INTO fin_settings(key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [(k, json.dumps(v)) for k, v in values.items()])
