import base64

from app.mailtext import extract_text, strip_quoted


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def test_prefers_plain_text_part():
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": b64("Hello plain")}},
        {"mimeType": "text/html", "body": {"data": b64("<p>Hello html</p>")}},
    ]}
    assert extract_text(payload) == "Hello plain"


def test_falls_back_to_html_and_drops_scripts():
    html = "<html><head><style>x{}</style></head><body><p>Game at 9am</p><script>bad()</script></body></html>"
    payload = {"mimeType": "multipart/mixed", "parts": [{"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": b64(html)}}]}]}
    assert extract_text(payload) == "Game at 9am"


def test_strips_quotes_links_and_truncates():
    text = "New info here https://track.example.com/abc?x=1\n\nOn Mon, Oct 5, 2026 at 9:00 AM Pat <p@x.com> wrote:\n> old stuff"
    out = extract_text({"mimeType": "text/plain", "body": {"data": b64(text)}})
    assert out == "New info here [link]"
    assert len(extract_text({"mimeType": "text/plain", "body": {"data": b64("a" * 5000)}}, limit=100)) == 100


def test_strip_quoted_keeps_unquoted_lines():
    assert strip_quoted("hi\n> quoted\nthere") == "hi\nthere"


def test_empty_payload():
    assert extract_text({}) == ""
