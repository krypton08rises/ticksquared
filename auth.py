"""One-time TickTick OAuth login.

Run `python auth.py`. It opens your browser, you approve access, and it catches
the redirect on localhost, exchanges the code for tokens, and saves them to
tokens.json. You only ever do this once (unless you revoke the app).
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

from ticktick import AUTHORIZE_URL, SCOPE, TOKEN_URL, TOKENS_PATH

load_dotenv()

_received: dict[str, str] = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _received.update({k: v[0] for k, v in params.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>TickTick connected. You can close this tab.</h2>")

    def log_message(self, *args):
        pass


def main() -> None:
    client_id = os.environ["TICKTICK_CLIENT_ID"]
    client_secret = os.environ["TICKTICK_CLIENT_SECRET"]
    redirect_uri = os.environ["TICKTICK_REDIRECT_URI"]

    parsed = urllib.parse.urlparse(redirect_uri)
    host, port = parsed.hostname or "localhost", parsed.port or 8080

    state = secrets.token_urlsafe(16)
    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "scope": SCOPE,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    })

    print("Opening browser to authorise TickTick...")
    print("If it doesn't open, paste this URL:\n", auth_url, "\n")
    webbrowser.open(auth_url)

    server = HTTPServer((host, port), _Handler)
    server.handle_request()

    if _received.get("state") != state:
        raise SystemExit("State mismatch — aborting (possible CSRF).")
    code = _received.get("code")
    if not code:
        raise SystemExit(f"No code returned: {_received}")

    resp = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "scope": SCOPE,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if not resp.ok:
        print(f"\nToken exchange failed: HTTP {resp.status_code}")
        print("WWW-Authenticate:", resp.headers.get("WWW-Authenticate", "(none)"))
        print("Response body:", resp.text[:300] or "(empty)")
        print(f"client_id length={len(client_id)}, secret length={len(client_secret)}")
        raise SystemExit(1)

    tokens = resp.json()
    if "expires_in" in tokens:
        tokens["expires_at"] = time.time() + int(tokens["expires_in"]) - 60
    TOKENS_PATH.write_text(json.dumps(tokens, indent=2))
    TOKENS_PATH.chmod(0o600)
    print(f"Saved tokens to {TOKENS_PATH}. You're done — no more logins.")


if __name__ == "__main__":
    main()
