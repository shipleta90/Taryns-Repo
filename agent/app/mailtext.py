"""Turn a Gmail API message payload into short, clean plain text for the local model."""
import base64
import re
from html.parser import HTMLParser

_QUOTE_HEADER = re.compile(r"^On .{5,200} wrote:\s*$", re.MULTILINE)


class _TextOnly(HTMLParser):
    SKIP = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextOnly()
    p.feed(html)
    return "".join(p.parts)


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _find(payload: dict, mime: str) -> str | None:
    if payload.get("mimeType") == mime and payload.get("body", {}).get("data"):
        return _decode(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        found = _find(part, mime)
        if found:
            return found
    return None


def strip_quoted(text: str) -> str:
    """Drop the quoted earlier conversation so the model reads only the new part."""
    m = _QUOTE_HEADER.search(text)
    if m:
        text = text[: m.start()]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def extract_text(payload: dict, limit: int = 2000) -> str:
    text = _find(payload, "text/plain")
    if text is None:
        html = _find(payload, "text/html")
        text = html_to_text(html) if html else ""
    text = strip_quoted(text)
    text = re.sub(r"https?://\S+", "[link]", text)   # long tracking URLs waste the model's attention
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:limit]
