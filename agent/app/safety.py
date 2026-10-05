"""Sensitive-content detection. Anything flagged here must never leave the Mac mini
(no cloud model) and is never auto-trashed.

This is deliberately conservative: a false positive costs a little privacy-preserving
friction, a false negative could leak an SSN or trash a bank notice.
"""
import re
from dataclasses import dataclass

_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}[- ]?(?!00)\d{2}[- ]?(?!0000)\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_KEYWORDS = re.compile(
    r"social security|\bssn\b|routing number|account number|\biban\b|\bswift\b|"
    r"bank statement|wire transfer|tax return|\bw-?2\b|\b1099\b|"
    r"credit card|debit card|\bcvv\b|\bpassword\b|one-time (?:code|passcode)|verification code|"
    # health / therapy
    r"patient portal|client portal|\btherap(?:y|ist)\b|\bdiagnosis\b|\bprescription\b|"
    r"medical record|lab results|\bappointment reminder\b|"
    # legal / family court
    r"\battorney\b|\bcustody\b|\bdivorce\b|post-judgment|\bsubpoena\b|\blitigation\b|"
    r"\bIRMO\b|\bv\.? [A-Z][a-z]+\b.*\bmatter\b|\bmatter for\b|payment plan reminder|court (?:date|order|hearing)",
    re.IGNORECASE,
)
# Senders that are financial/government regardless of what the message body says.
FINANCIAL_DOMAINS = {
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com", "capitalone.com",
    "americanexpress.com", "discover.com", "schwab.com", "fidelity.com", "vanguard.com",
    "paypal.com", "venmo.com", "stripe.com", "irs.gov", "ssa.gov", "turbotax.com",
    "intuit.com", "mint.com", "coinbase.com", "robinhood.com",
}
# Health and legal senders: kept local-only and never auto-trashed, like financial ones.
HEALTH_LEGAL_DOMAINS = {
    "simplepractice.com", "zocdoc.com", "mychart.com", "teladoc.com", "kp.org",
    "healthgrades.com", "headway.co", "alma.com", "betterhelp.com", "talkspace.com",
}


@dataclass(frozen=True)
class Sensitivity:
    reasons: tuple[str, ...]

    @property
    def sensitive(self) -> bool:
        return bool(self.reasons)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def assess(text: str, sender_domain: str = "") -> Sensitivity:
    reasons: list[str] = []
    if sender_domain and (sender_domain in FINANCIAL_DOMAINS or sender_domain.endswith(".gov")):
        reasons.append("financial-or-government-sender")
    if sender_domain in HEALTH_LEGAL_DOMAINS:
        reasons.append("health-or-legal-sender")
    if _SSN.search(text):
        reasons.append("ssn-pattern")
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            reasons.append("card-number")
            break
    if _KEYWORDS.search(text):
        reasons.append("sensitive-keyword")
    return Sensitivity(tuple(reasons))
