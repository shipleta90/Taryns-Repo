"""Inbox triage rules. Pure functions: no network, fully unit-tested.

Policy (from the build spec):
  * Promotions from a domain you have never engaged with -> trash (reversible).
  * Anything sensitive (financial/PII), starred, important, or from an engaged domain -> never touched.
  * Everything else is labelled so we know we've seen it, and left alone.
The model is never involved in these decisions, so a malicious email cannot steer them.
"""
import re
from dataclasses import dataclass, field
from enum import Enum

from . import safety
from .domains import domain_of_address, engagement_domain, parse_addresses

PROMO_LABEL = "CATEGORY_PROMOTIONS"
PROTECTED_LABELS = {"STARRED", "IMPORTANT", "SENT", "DRAFT"}


class Action(str, Enum):
    TRASH = "trash"
    LABEL = "label"   # mark as seen, leave in inbox
    SKIP = "skip"     # leave completely alone (and don't mark seen; see reason)


@dataclass(frozen=True)
class Message:
    id: str
    thread_id: str
    sender: str                    # raw From header
    subject: str
    snippet: str = ""
    labels: frozenset[str] = frozenset()
    has_list_unsubscribe: bool = False
    thread_has_user_reply: bool = False


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


@dataclass
class EngagedSet:
    domains: set[str] = field(default_factory=set)
    addresses: set[str] = field(default_factory=set)

    def engaged(self, address: str) -> bool:
        domain = engagement_domain(address)  # freemail domains never match, only exact addresses
        return address in self.addresses or (domain is not None and domain in self.domains)


_PROMO_WORDS = re.compile(
    r"\d+\s?% (?:off|back)|\$\d+ (?:off|credit)|\b(?:sale|discount|coupon|promo(?:tion|code)?|deals?)\b|"
    r"free shipping|limited[- ]time|exclusive (?:offer|deal)|\b(?:give|save|get) up to\b|"
    r"shop now|last chance|don'?t miss|black friday|\bbecome a member\b|\bclaim your\b|\bsponsored\b",
    re.IGNORECASE,
)
_TRANSACTIONAL = re.compile(
    r"\b(?:order|receipt|invoice|shipped|shipping|delivery|delivered|tracking|confirm(?:ation|ed)?|"
    r"password|security|verify|verification|sign[- ]in|statement|payment|renewal|booking|"
    r"reservation|ticket|appointment|schedule|cancel(?:led|ed)?)\b",
    re.IGNORECASE,
)


def is_promotion(msg: Message) -> bool:
    if PROMO_LABEL in msg.labels:
        return True
    if not msg.has_list_unsubscribe or "CATEGORY_PERSONAL" in msg.labels:
        return False
    text = f"{msg.subject} {msg.snippet}"
    if _TRANSACTIONAL.search(text):
        return False
    if "CATEGORY_UPDATES" in msg.labels:
        # Gmail files lots of marketing under Updates; only call it a promo if it reads like one.
        return bool(_PROMO_WORDS.search(text))
    return True


def decide(msg: Message, engaged: EngagedSet) -> Decision:
    addrs = parse_addresses(msg.sender)
    sender = addrs[0] if addrs else ""
    domain = domain_of_address(sender)

    sens = safety.assess(f"{msg.subject}\n{msg.snippet}", domain)
    if sens.sensitive:
        return Decision(Action.SKIP, "sensitive: " + ",".join(sens.reasons))
    protected = msg.labels & PROTECTED_LABELS
    if PROMO_LABEL in msg.labels:
        protected = protected - {"IMPORTANT"}   # Gmail marks lots of marketing "important"
    if protected:
        return Decision(Action.SKIP, "protected label: " + ",".join(sorted(protected)))
    if msg.thread_has_user_reply:
        return Decision(Action.SKIP, "you replied in this thread")
    if not sender:
        return Decision(Action.SKIP, "unparseable sender")
    if engaged.engaged(sender):
        return Decision(Action.LABEL, "engaged sender/domain")
    if is_promotion(msg):
        return Decision(Action.TRASH, f"promotion from never-engaged domain {domain}")
    cats = ",".join(sorted(l.removeprefix("CATEGORY_") for l in msg.labels if l.startswith("CATEGORY_"))) or "none"
    unsub = "yes" if msg.has_list_unsubscribe else "no"
    return Decision(Action.LABEL, f"not a promotion (gmail category: {cats}; unsubscribe header: {unsub})")
