"""Registrable-domain extraction without a network-fetched public-suffix list."""
from email.utils import getaddresses

# Shared mailbox providers: emailing one gmail.com friend must not make ALL of gmail.com "engaged".
# For these, engagement is tracked per exact address only.
FREEMAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "msn.com",
}

# Second-level suffixes where the registrable domain has three labels (foo.co.uk).
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}
_CC_TLD_LEN = 2


def registrable_domain(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    labels = [p for p in host.split(".") if p]
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == _CC_TLD_LEN and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def domain_of_address(address: str) -> str:
    _, _, host = address.rpartition("@")
    return registrable_domain(host) if host else ""


def parse_addresses(header_value: str) -> list[str]:
    """Return lowercase email addresses from a From/To/Cc header."""
    return [addr.lower() for _, addr in getaddresses([header_value]) if "@" in addr]


def engagement_domain(address: str) -> str | None:
    """Domain to record as engaged for this address, or None for shared freemail providers."""
    domain = domain_of_address(address)
    return None if not domain or domain in FREEMAIL else domain
