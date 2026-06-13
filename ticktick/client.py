"""Thin TickTick Open API client with autonomous token handling.

You log in ONCE (run `python auth.py`). After that this client loads the saved
tokens and refreshes them silently when needed, so the bot never needs you to
re-authenticate. See README for the OAuth app setup.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.ticktick.com/open/v1"
TOKEN_URL = "https://ticktick.com/oauth/token"
AUTHORIZE_URL = "https://ticktick.com/oauth/authorize"
SCOPE = "tasks:read tasks:write"

TOKENS_PATH = Path(__file__).parent.parent / "tokens.json"


class TickTickAuthError(RuntimeError):
    """Raised when we have no usable token and a manual login is required."""


class TickTickClient:
    def __init__(self, tokens_path: Path = TOKENS_PATH):
        self.tokens_path = tokens_path
        self.client_id = os.environ["TICKTICK_CLIENT_ID"]
        self.client_secret = os.environ["TICKTICK_CLIENT_SECRET"]
        self._tokens = self._load_tokens()

    # --- token plumbing ----------------------------------------------------
    def _load_tokens(self) -> dict[str, Any]:
        if not self.tokens_path.exists():
            raise TickTickAuthError(
                f"No tokens at {self.tokens_path}. Run `python auth.py` once to log in."
            )
        return json.loads(self.tokens_path.read_text())

    def _save_tokens(self, tokens: dict[str, Any]) -> None:
        if "expires_in" in tokens:
            tokens["expires_at"] = time.time() + int(tokens["expires_in"]) - 60
        self.tokens_path.write_text(json.dumps(tokens, indent=2))
        self.tokens_path.chmod(0o600)
        self._tokens = tokens

    def _refresh_if_needed(self) -> None:
        expires_at = self._tokens.get("expires_at", 0)
        if time.time() < expires_at:
            return

        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            raise TickTickAuthError(
                "Access token expired and no refresh token available. "
                "Run `python auth.py` again."
            )

        resp = requests.post(
            TOKEN_URL,
            auth=(self.client_id, self.client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": SCOPE,
            },
            timeout=30,
        )
        resp.raise_for_status()
        new_tokens = resp.json()
        new_tokens.setdefault("refresh_token", refresh_token)
        self._save_tokens(new_tokens)

    def _headers(self) -> dict[str, str]:
        self._refresh_if_needed()
        return {
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "Content-Type": "application/json",
        }

    # --- API surface -------------------------------------------------------
    def get_projects(self) -> list[dict[str, Any]]:
        r = requests.get(f"{API_BASE}/project", headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    def get_project_data(self, project_id: str) -> dict[str, Any]:
        r = requests.get(
            f"{API_BASE}/project/{project_id}/data", headers=self._headers(), timeout=30
        )
        r.raise_for_status()
        return r.json()

    def find_project_id(self, name: str) -> str | None:
        for p in self.get_projects():
            if p.get("name", "").strip().lower() == name.strip().lower():
                return p["id"]
        return None

    def create_project(self, name: str, color: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if color:
            body["color"] = color
        r = requests.post(
            f"{API_BASE}/project", headers=self._headers(), json=body, timeout=30
        )
        r.raise_for_status()
        return r.json()

    def get_or_create_project(self, name: str, color: str | None = None) -> dict[str, Any]:
        pid = self.find_project_id(name)
        if pid:
            return {"id": pid, "name": name, "existed": True}
        proj = self.create_project(name, color)
        proj["existed"] = False
        return proj

    def get_incomplete_tasks(self, list_name: str) -> list[dict[str, Any]]:
        pid = self.find_project_id(list_name)
        if not pid:
            return []
        data = self.get_project_data(pid)
        tasks = data.get("tasks", []) or []
        tasks.sort(key=lambda t: (-int(t.get("priority", 0)), t.get("sortOrder", 0)))
        return tasks

    def create_task(
        self,
        title: str,
        project_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"title": title}
        if project_id:
            body["projectId"] = project_id
        if start:
            body["startDate"] = start
            body["isAllDay"] = False
        if end:
            body["dueDate"] = end
        if content:
            body["content"] = content
        r = requests.post(
            f"{API_BASE}/task", headers=self._headers(), json=body, timeout=30
        )
        r.raise_for_status()
        return r.json()

    def complete_task(self, project_id: str, task_id: str) -> None:
        r = requests.post(
            f"{API_BASE}/project/{project_id}/task/{task_id}/complete",
            headers=self._headers(),
            timeout=30,
        )
        r.raise_for_status()
