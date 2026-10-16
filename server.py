"""Serve Basira and its localhost-only coding-agent API."""

from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from basira_agent import BasiraAgent, Workspace, WorkspaceError, run_check


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"


def _load_local_env() -> None:
    """Load simple KEY=VALUE entries from .env without replacing shell values."""
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


def _make_agent() -> BasiraAgent:
    workspace_root = os.environ.get("BASIRA_WORKSPACE", str(ROOT))
    return BasiraAgent(Workspace(workspace_root))


class BasiraHandler(SimpleHTTPRequestHandler):
    server_version = "BasiraLocal/0.2"

    def __init__(self, *args, agent: BasiraAgent, **kwargs):
        self.agent = agent
        super().__init__(*args, directory=str(DIST), **kwargs)

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._json(200, self.agent.health())
            return
        if self.path.startswith("/api/"):
            self._json(404, {"error": "API route not found."})
            return
        super().do_GET()

    def do_POST(self) -> None:
        try:
            body = self._read_body()
            if self.path == "/api/chat":
                result = self.agent.run(body.get("history", []), body.get("message"))
                self._json(200, result)
            elif self.path == "/api/change/apply":
                change_id = body.get("id", "")
                self._json(200, self.agent.workspace.apply_change(str(change_id)))
            elif self.path == "/api/change/reject":
                change_id = body.get("id", "")
                self._json(200, self.agent.workspace.reject_change(str(change_id)))
            elif self.path == "/api/checks":
                self._json(200, run_check(self.agent.workspace, str(body.get("check", ""))))
            else:
                self._json(404, {"error": "API route not found."})
        except WorkspaceError as error:
            self._json(400, {"error": str(error)})
        except RuntimeError as error:
            self._json(503, {"error": str(error)})
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._json(400, {"error": f"Invalid request: {error}"})

    def _read_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise WorkspaceError("Invalid content length.") from error
        if length < 0 or length > 1_000_000:
            raise WorkspaceError("Request is too large.")
        raw = self.rfile.read(length)
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(parsed, dict):
            raise WorkspaceError("Request body must be a JSON object.")
        return parsed

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args) -> None:
        # Do not log chat text, source code, or request bodies.
        super().log_message(fmt, *args)


def main() -> None:
    _load_local_env()
    host = os.environ.get("BASIRA_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Basira accepts localhost bindings only. Keep workspace access local.")
    port = int(os.environ.get("BASIRA_PORT", "8000"))
    try:
        agent = _make_agent()
    except WorkspaceError as error:
        raise SystemExit(str(error)) from error
    if not DIST.exists():
        print("Build the frontend first with: npm install && npm run build")
    handler = lambda *args, **kwargs: BasiraHandler(*args, agent=agent, **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Basira coding agent at http://{host}:{port}")
    print(f"Workspace: {agent.workspace.root}")
    print(f"Model: {agent.model} via local Ollama")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Basira.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
