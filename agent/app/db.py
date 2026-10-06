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
