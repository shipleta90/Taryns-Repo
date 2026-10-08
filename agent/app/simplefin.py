"""SimpleFIN Bridge: a read-only feed of balances and transactions (it cannot move money).

One-time setup: create a Setup Token at bridge.simplefin.org, then run
    python -m app.secrets set-simplefin
which exchanges it for an Access URL kept in the macOS Keychain.
"""
from __future__ import annotations

import base64
import datetime as dt
from urllib.parse import urlsplit, urlunsplit

import httpx

CHUNK_DAYS = 60   # SimpleFIN limits how much history one request may cover


class SimpleFINError(RuntimeError):
    pass


def claim(setup_token: str, transport: httpx.BaseTransport | None = None) -> str:
    """Exchange a one-time Setup Token for the long-lived Access URL."""
    try:
        claim_url = base64.b64decode(setup_token.strip()).decode()
    except Exception as exc:
        raise SimpleFINError("That doesn't look like a SimpleFIN Setup Token.") from exc
    if not claim_url.startswith("https://"):
        raise SimpleFINError("That doesn't look like a SimpleFIN Setup Token.")
    with httpx.Client(timeout=30.0, transport=transport) as c:
        resp = c.post(claim_url)
    if resp.status_code != 200 or not resp.text.startswith("https://"):
        raise SimpleFINError(f"Claiming the token failed ({resp.status_code}). Tokens work once; make a new one.")
    return resp.text.strip()


class SimpleFINClient:
    def __init__(self, access_url: str, transport: httpx.BaseTransport | None = None):
        parts = urlsplit(access_url)
        if parts.scheme != "https" or not parts.username:
            raise SimpleFINError("Invalid SimpleFIN Access URL.")
        self._auth = (parts.username, parts.password or "")
        netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
        self._base = urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))
        self._http = httpx.Client(timeout=60.0, transport=transport)

    def _accounts(self, start: dt.datetime, end: dt.datetime) -> dict:
        try:
            resp = self._http.get(f"{self._base}/accounts", auth=self._auth,
                                  params={"start-date": int(start.timestamp()), "end-date": int(end.timestamp())})
        except httpx.HTTPError as exc:
            raise SimpleFINError(f"Couldn't reach SimpleFIN: {exc}") from exc
        if resp.status_code == 403:
            raise SimpleFINError("SimpleFIN refused access (403). Reconnect with a new Setup Token.")
        if resp.status_code != 200:
            raise SimpleFINError(f"SimpleFIN error {resp.status_code}")
        return resp.json()

    def fetch(self, days: int) -> dict:
        """Accounts with balances, plus transactions from the last `days` days (fetched in chunks).
        Returns {"accounts": [...], "transactions": [...], "errors": [...]} with money out negative."""
        end = dt.datetime.now(dt.timezone.utc)
        accounts: dict[str, dict] = {}
        txns: dict[str, dict] = {}
        errors: list[str] = []
        start_all = end - dt.timedelta(days=days)
        chunk_end = end
        while chunk_end > start_all:
            chunk_start = max(start_all, chunk_end - dt.timedelta(days=CHUNK_DAYS))
            data = self._accounts(chunk_start, chunk_end)
            errors += [str(e) for e in data.get("errors", [])]
            for a in data.get("accounts", []):
                acc_id = f"sf:{a['id']}"
                accounts.setdefault(acc_id, {
                    "id": acc_id, "org": (a.get("org") or {}).get("name", ""), "name": a.get("name", ""),
                    "currency": a.get("currency", "USD"), "balance": float(a.get("balance") or 0),
                    "balance_date": float(a.get("balance-date") or 0),
                })
                for t in a.get("transactions", []):
                    if t.get("pending"):
                        continue  # wait until it posts, so amounts don't change under us
                    tid = f"{acc_id}:{t['id']}"
                    txns[tid] = {"id": tid, "account_id": acc_id, "posted": float(t["posted"]),
                                 "amount": float(t["amount"]),
                                 "description": t.get("payee") or t.get("description") or t.get("memo") or ""}
            chunk_end = chunk_start
        return {"accounts": list(accounts.values()), "transactions": list(txns.values()),
                "errors": sorted(set(errors))}
