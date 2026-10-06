"""Local model client (Ollama). Talks only to the Ollama server on this machine.

The model is only ever asked for TEXT. It has no tools and cannot trigger any action, so a
malicious email that tries to hijack it can at worst produce a misleading summary.
"""
import json
from urllib.parse import urlparse

import httpx

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


class LLMError(RuntimeError):
    pass


class LocalLLM:
    def __init__(self, base_url: str, model: str, timeout: float = 180.0,
                 transport: httpx.BaseTransport | None = None):
        host = urlparse(base_url).hostname or ""
        if host not in LOCAL_HOSTS:
            # Privacy guard: email text must never be sent to another machine by accident.
            raise ValueError(f"OLLAMA_URL must point at this machine, not {host!r}")
        self.model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def chat_json(self, system: str, user: str) -> dict:
        """Ask for a JSON object. Raises LLMError if the server is down or the reply isn't JSON."""
        try:
            resp = self._client.post("/api/chat", json={
                "model": self.model,
                "stream": False,
                "format": "json",
                # Ollama's default context is small; the overview call sends ~25 notes at once.
                "options": {"temperature": 0.1, "num_ctx": 8192},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
            })
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError("model did not return valid JSON") from exc
        if not isinstance(data, dict):
            raise LLMError("model returned JSON that is not an object")
        return data
