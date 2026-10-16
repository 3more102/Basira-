"""Local static server and ephemeral Gemini Live token issuer for Basira."""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
LIVE_MODEL = "models/gemini-3.8-live"


def _load_local_env() -> None:
    """Load simple KEY=VALUE entries from .env without overriding shell values."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def mint_ephemeral_token(api_key: str, opener=urllib.request.urlopen) -> dict[str, Any]:
    """Request a one-use token with a short connect window and fixed live model."""
    now = datetime.now(timezone.utc)
    payload = {
        "uses": 1,
        "expireTime": (now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "newSessionExpireTime": (now + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "liveConnectConstraints": {
            "model": LIVE_MODEL,
            "config": {
                "responseModalities": ["AUDIO"],
                "sessionResumption": {},
            },
        },
    }
    request = urllib.request.Request(
        TOKEN_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini token request failed ({error.code}): {detail[:500]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not reach the Gemini token service: {error.reason}") from error
    if not isinstance(result, dict) or not result.get("name"):
        raise RuntimeError("Gemini token service returned an invalid token response.")
    return {"token": result["name"], "expires_at": result.get("expireTime")}


class BasiraHandler(SimpleHTTPRequestHandler):
    server_version = "BasiraLocal/0.1"
    _token_lock = threading.Lock()
    _last_token_request = 0.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_POST(self) -> None:
        if self.path != "/api/token":
            self.send_error(404)
            return
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            self._json(503, {"error": "Set GEMINI_API_KEY on the local server, then restart it."})
            return
        try:
            result = mint_ephemeral_token(api_key)
        except RuntimeError as error:
            self._json(502, {"error": str(error)})
            return
        self._json(200, result)

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args) -> None:
        # Keep URLs visible for local debugging, but never log request bodies or tokens.
        super().log_message(fmt, *args)


def main() -> None:
    _load_local_env()
    host = os.environ.get("BASIRA_HOST", "127.0.0.1")
    port = int(os.environ.get("BASIRA_PORT", "8000"))
    if not DIST.exists():
        print("Build the frontend first with: npm install && npm run build")
    server = ThreadingHTTPServer((host, port), BasiraHandler)
    print(f"Basira local server listening at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Basira.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
