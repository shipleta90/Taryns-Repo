import httpx
import pytest

from app.llm import LLMError, LocalLLM


def llm(handler):
    return LocalLLM("http://127.0.0.1:11434", "m", transport=httpx.MockTransport(handler))


def test_refuses_remote_host():
    with pytest.raises(ValueError):
        LocalLLM("https://api.example.com", "m")
    LocalLLM("http://localhost:11434", "m")


def test_parses_json_reply():
    def handler(req):
        body = req.read().decode()
        assert '"format":"json"' in body.replace(" ", "")
        return httpx.Response(200, json={"message": {"content": '{"summary": "hi", "needs_reply": true}'}})
    assert llm(handler).chat_json("s", "u") == {"summary": "hi", "needs_reply": True}


def test_errors_become_llmerror():
    assert_raises = lambda h: pytest.raises(LLMError)
    with assert_raises(None):
        llm(lambda r: httpx.Response(500)).chat_json("s", "u")
    with assert_raises(None):
        llm(lambda r: httpx.Response(200, json={"message": {"content": "not json"}})).chat_json("s", "u")
    with assert_raises(None):
        llm(lambda r: httpx.Response(200, json={"message": {"content": "[1,2]"}})).chat_json("s", "u")

    def boom(req):
        raise httpx.ConnectError("refused")
    with assert_raises(None):
        llm(boom).chat_json("s", "u")
