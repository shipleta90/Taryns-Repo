"""Gmail access. `GmailClient` is the interface the rest of the app uses; `GoogleGmail` is the
real implementation. Tests use an in-memory fake.

Scope is gmail.modify: it can read, label and TRASH, but Google refuses permanent deletion
with this scope. That is a deliberate safety property: nothing here can destroy mail.
"""
from __future__ import annotations

from typing import Protocol

from .domains import engagement_domain, parse_addresses
from .mailtext import extract_text
from .triage import EngagedSet, Message

SEEN_LABEL = "Agent/Seen"
TRASHED_LABEL = "Agent/Trashed"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


class GmailClient(Protocol):
    def list_new_messages(self, lookback_days: int) -> list[Message]: ...
    def recent_messages(self, lookback_days: int, limit: int) -> list[Message]: ...
    def message_text(self, message_id: str) -> str: ...
    def build_engaged_set(self) -> EngagedSet: ...
    def trash(self, message_id: str) -> None: ...
    def untrash(self, message_id: str) -> None: ...
    def mark_seen(self, message_id: str) -> None: ...


class GoogleGmail:
    """Real Gmail API client. Requires `python -m app.auth_google` to have been run once."""

    SENT_SAMPLE = 400      # recent sent messages scanned for engaged recipients
    STARRED_SAMPLE = 200

    def __init__(self, credentials):
        from googleapiclient.discovery import build  # imported lazily so tests need no Google libs

        self.svc = build("gmail", "v1", credentials=credentials, cache_discovery=False)
        self._label_ids: dict[str, str] = {}

    # --- labels -------------------------------------------------------------------------
    def _label_id(self, name: str) -> str:
        if name in self._label_ids:
            return self._label_ids[name]
        labels = self.svc.users().labels().list(userId="me").execute().get("labels", [])
        for lab in labels:
            self._label_ids[lab["name"]] = lab["id"]
        if name not in self._label_ids:
            created = self.svc.users().labels().create(
                userId="me", body={"name": name, "labelListVisibility": "labelShow"}
            ).execute()
            self._label_ids[name] = created["id"]
        return self._label_ids[name]

    # --- reading ------------------------------------------------------------------------
    def _ids(self, query: str, limit: int) -> list[dict]:
        out: list[dict] = []
        req = self.svc.users().messages().list(userId="me", q=query, maxResults=min(limit, 100))
        while req is not None and len(out) < limit:
            resp = req.execute()
            out.extend(resp.get("messages", []))
            req = self.svc.users().messages().list_next(req, resp)
        return out[:limit]

    def _metadata(self, message_id: str, headers: list[str]) -> dict:
        return self.svc.users().messages().get(
            userId="me", id=message_id, format="metadata", metadataHeaders=headers
        ).execute()

    @staticmethod
    def _header(msg: dict, name: str) -> str:
        for h in msg.get("payload", {}).get("headers", []):
            if h["name"].lower() == name.lower():
                return h["value"]
        return ""

    def _to_message(self, ref_id: str) -> Message:
        m = self._metadata(ref_id, ["From", "Subject", "List-Unsubscribe"])
        thread = self.svc.users().threads().get(
            userId="me", id=m["threadId"], format="minimal"
        ).execute()
        replied = any("SENT" in t.get("labelIds", []) for t in thread.get("messages", []))
        return Message(
            id=m["id"],
            thread_id=m["threadId"],
            sender=self._header(m, "From"),
            subject=self._header(m, "Subject"),
            snippet=m.get("snippet", ""),
            labels=frozenset(m.get("labelIds", [])),
            has_list_unsubscribe=bool(self._header(m, "List-Unsubscribe")),
            thread_has_user_reply=replied,
        )

    def list_new_messages(self, lookback_days: int) -> list[Message]:
        # Only unseen inbox mail within the lookback window: future-forward, no backlog sweep.
        query = f'in:inbox newer_than:{lookback_days}d -label:"{SEEN_LABEL}"'
        return [self._to_message(ref["id"]) for ref in self._ids(query, limit=200)]

    def recent_messages(self, lookback_days: int, limit: int) -> list[Message]:
        """Recent inbox mail (seen or not) for the briefing. Read-only."""
        query = f"in:inbox newer_than:{lookback_days}d"
        return [self._to_message(ref["id"]) for ref in self._ids(query, limit=limit)]

    def message_text(self, message_id: str) -> str:
        """Plain-text body (quoted replies and links stripped, truncated). Read-only."""
        m = self.svc.users().messages().get(userId="me", id=message_id, format="full").execute()
        return extract_text(m.get("payload", {}))

    def build_engaged_set(self) -> EngagedSet:
        """Domains/addresses you have written to, or starred mail from."""
        engaged = EngagedSet()
        for ref in self._ids("in:sent newer_than:365d", self.SENT_SAMPLE):
            m = self._metadata(ref["id"], ["To", "Cc"])
            for header in ("To", "Cc"):
                for addr in parse_addresses(self._header(m, header)):
                    self._add(engaged, addr)
        for ref in self._ids("is:starred", self.STARRED_SAMPLE):
            m = self._metadata(ref["id"], ["From"])
            for addr in parse_addresses(self._header(m, "From")):
                self._add(engaged, addr)
        return engaged

    @staticmethod
    def _add(engaged: EngagedSet, addr: str) -> None:
        engaged.addresses.add(addr)
        if (domain := engagement_domain(addr)):
            engaged.domains.add(domain)

    # --- acting (all reversible) ---------------------------------------------------------
    def trash(self, message_id: str) -> None:
        self.svc.users().messages().modify(
            userId="me", id=message_id,
            body={"addLabelIds": [self._label_id(TRASHED_LABEL), self._label_id(SEEN_LABEL)]},
        ).execute()
        self.svc.users().messages().trash(userId="me", id=message_id).execute()

    def untrash(self, message_id: str) -> None:
        self.svc.users().messages().untrash(userId="me", id=message_id).execute()
        self.svc.users().messages().modify(
            userId="me", id=message_id,
            body={"removeLabelIds": [self._label_id(TRASHED_LABEL)],
                  "addLabelIds": ["INBOX"]},
        ).execute()

    def mark_seen(self, message_id: str) -> None:
        self.svc.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": [self._label_id(SEEN_LABEL)]}
        ).execute()
