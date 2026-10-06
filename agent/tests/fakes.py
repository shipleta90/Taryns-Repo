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

    def recent_messages(self, lookback_days, limit):
        return self.messages[:limit]

    def message_text(self, message_id):
        return self.bodies.get(message_id, "") if hasattr(self, "bodies") else ""

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


class FakeLLM:
    """Answers extraction calls by matching a needle in the email, and overview calls with `overview`."""
    model = "fake:1b"

    def __init__(self, answers=None, fail=False, overview="You have a quiet morning.", overview_fails=False):
        self.answers = answers or {}
        self.fail = fail
        self.overview = overview
        self.overview_fails = overview_fails
        self.prompts: list[tuple[str, str]] = []

    def chat_json(self, system, user):
        from app.llm import LLMError
        self.prompts.append((system, user))
        if self.fail:
            raise LLMError("down")
        if user.startswith("<<<NOTES"):
            if self.overview_fails:
                raise LLMError("overview failed")
            return {"overview": self.overview}
        for needle, ans in self.answers.items():
            if needle in user:
                return ans
        return {"summary": "A message.", "category": "Other", "action": "", "due": "", "needs_reply": False}

    @property
    def email_prompts(self):
        return [p for p in self.prompts if p[1].startswith("<<<EMAIL")]
