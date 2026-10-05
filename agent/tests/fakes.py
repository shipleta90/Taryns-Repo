from app.triage import EngagedSet, Message


class FakeGmail:
    def __init__(self, messages, engaged=None):
        self.messages = list(messages)
        self.engaged = engaged or EngagedSet()
        self.trashed: list[str] = []
        self.seen: list[str] = []
        self.restored: list[str] = []
        self.engaged_builds = 0

    def list_new_messages(self, lookback_days):
        return self.messages

    def build_engaged_set(self):
        self.engaged_builds += 1
        return self.engaged

    def trash(self, message_id):
        self.trashed.append(message_id)

    def untrash(self, message_id):
        self.restored.append(message_id)

    def mark_seen(self, message_id):
        self.seen.append(message_id)


def promo(i, sender="Deals <news@shop.example.com>", subject="50% off", **kw):
    return Message(id=f"m{i}", thread_id=f"t{i}", sender=sender, subject=subject,
                   labels=frozenset({"INBOX", "CATEGORY_PROMOTIONS"}), has_list_unsubscribe=True, **kw)
