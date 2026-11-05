"""Todoist (family tasks, groceries, dinners) through Todoist's API v1.

The token lives in the macOS Keychain:  python -m app.secrets set-todoist-token
Nothing read from Todoist is saved on the Mac mini; every call goes to Todoist live.
"""
from __future__ import annotations

import httpx

BASE = "https://api.todoist.com/api/v1"


class TodoistError(RuntimeError):
    pass


class Todoist:
    def __init__(self, token: str, client: httpx.Client | None = None):
        self.http = client or httpx.Client(base_url=BASE, timeout=15,
                                           headers={"Authorization": f"Bearer {token}"})

    # --- low level --------------------------------------------------------------------
    def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        """GET a paginated list. API v1 returns {"results": [...], "next_cursor": ...};
        a bare list is accepted too, so a small API change doesn't break the hub."""
        out: list[dict] = []
        params = dict(params or {})
        for _ in range(20):   # hard stop: never loop forever on a bad cursor
            r = self.http.get(path, params=params)
            self._raise(r)
            data = r.json()
            if isinstance(data, list):
                return out + data
            out += data.get("results") or []
            cursor = data.get("next_cursor")
            if not cursor:
                break
            params["cursor"] = cursor
        return out

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.status_code in (401, 403):
            raise TodoistError("Todoist rejected the token. On the Mac mini run: "
                               "python -m app.secrets set-todoist-token")
        if r.status_code >= 400:
            raise TodoistError(f"Todoist error {r.status_code}: {r.text[:200]}")

    # --- reads --------------------------------------------------------------------------
    def projects(self) -> list[dict]:
        return self._get_all("/projects")

    def project_ids(self, names: list[str]) -> dict[str, str]:
        """{name (as given): project id} for the projects that exist, matched case-insensitively."""
        by_name = {p.get("name", "").strip().lower(): p["id"] for p in self.projects()}
        return {n: by_name[n.lower()] for n in names if n.lower() in by_name}

    def tasks(self, project_id: str) -> list[dict]:
        return self._get_all("/tasks", {"project_id": project_id})

    def sections(self, project_id: str) -> dict[str, str]:
        """{section id: section name}"""
        return {s["id"]: s.get("name", "") for s in self._get_all("/sections", {"project_id": project_id})}

    def task(self, task_id: str) -> dict:
        r = self.http.get(f"/tasks/{task_id}")
        self._raise(r)
        return r.json()

    # --- writes (only after a tap on the hub, or an approved card in Bruce) ---------------
    def close(self, task_id: str) -> None:
        r = self.http.post(f"/tasks/{task_id}/close")
        self._raise(r)

    def add(self, content: str, project_id: str, labels: list[str] | None = None,
            due_string: str = "", section_id: str = "") -> dict:
        body: dict = {"content": content[:500], "project_id": project_id}
        if labels:
            body["labels"] = labels
        if due_string:
            body["due_string"] = due_string
            body["due_lang"] = "en"
        if section_id:
            body["section_id"] = section_id
        r = self.http.post("/tasks", json=body)
        self._raise(r)
        return r.json()
