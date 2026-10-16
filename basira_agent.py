"""Local-first coding agent with a guarded repository workspace."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


MAX_FILE_BYTES = 32_000
MAX_PROPOSAL_BYTES = 40_000
MAX_REQUEST_HISTORY = 20
MAX_HISTORY_CHARS = 24_000
MAX_MESSAGE_CHARS = 8_000
MAX_TOOL_ROUNDS = 7
SKIP_NAMES = {
    ".git", ".venv", "venv", "node_modules", "dist", "build", "coverage",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
SECRET_NAMES = {".env", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


class WorkspaceError(ValueError):
    """Raised when a workspace operation is unsafe or invalid."""


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        if not self.root.exists() or not self.root.is_dir():
            raise WorkspaceError("Workspace must be an existing folder.")
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _is_secret(parts: tuple[str, ...]) -> bool:
        lowered = tuple(part.casefold() for part in parts)
        if any(part in SKIP_NAMES or part in SECRET_NAMES for part in lowered):
            return True
        filename = lowered[-1] if lowered else ""
        if filename.startswith(".env.") and filename != ".env.example":
            return True
        return any(filename.endswith(suffix) for suffix in SECRET_SUFFIXES)

    def _parts(self, relative: str, *, allow_root: bool = False) -> tuple[str, ...]:
        if not isinstance(relative, str) or len(relative) > 500:
            raise WorkspaceError("Provide a valid workspace-relative path.")
        normalized = relative.replace("\\", "/")
        if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
            raise WorkspaceError("Absolute paths are outside the workspace.")
        path = PurePosixPath(normalized or ".")
        if any(part == ".." for part in path.parts):
            raise WorkspaceError("Parent-directory traversal is blocked.")
        parts = tuple(part for part in path.parts if part not in ("", ".", "/"))
        if not parts and not allow_root:
            raise WorkspaceError("A file path is required.")
        if self._is_secret(parts):
            raise WorkspaceError("That path is excluded from Basira's workspace tools.")
        return parts

    def resolve(self, relative: str, *, allow_root: bool = False) -> Path:
        parts = self._parts(relative, allow_root=allow_root)
        candidate = self.root.joinpath(*parts)
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceError("The path resolves outside the selected workspace.")
        return resolved

    def list_files(self, relative: str = ".", *, limit: int = 200) -> list[str]:
        folder = self.resolve(relative, allow_root=True)
        if not folder.exists() or not folder.is_dir():
            raise WorkspaceError("That folder does not exist in the workspace.")
        results: list[str] = []
        for current, directories, filenames in os.walk(folder, followlinks=False):
            current_path = Path(current)
            kept_dirs = []
            for name in directories:
                child = current_path / name
                rel = child.relative_to(self.root).as_posix()
                if not child.is_symlink() and not self._is_secret(tuple(PurePosixPath(rel).parts)):
                    kept_dirs.append(name)
            directories[:] = kept_dirs
            for name in filenames:
                child = current_path / name
                if child.is_symlink():
                    continue
                rel_path = child.relative_to(self.root).as_posix()
                if self._is_secret(tuple(PurePosixPath(rel_path).parts)):
                    continue
                results.append(rel_path)
                if len(results) >= limit:
                    return sorted(results)
        return sorted(results)

    def read_file(self, relative: str) -> str:
        path = self.resolve(relative)
        if not path.exists() or not path.is_file():
            raise WorkspaceError("That file does not exist in the workspace.")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise WorkspaceError(f"File is larger than the {MAX_FILE_BYTES}-byte read limit.")
        data = path.read_bytes()
        if b"\0" in data:
            raise WorkspaceError("Binary files are not available to the text tools.")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise WorkspaceError("The file is not valid UTF-8 text.") from error

    def search_files(self, query: str, relative: str = ".", *, limit: int = 30) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise WorkspaceError("Search text must contain 1 to 500 characters.")
        needle = query.casefold()
        matches: list[dict[str, Any]] = []
        for rel_path in self.list_files(relative, limit=400):
            try:
                contents = self.read_file(rel_path)
            except (WorkspaceError, OSError):
                continue
            for line_number, line in enumerate(contents.splitlines(), start=1):
                if needle in line.casefold():
                    matches.append({"path": rel_path, "line": line_number, "text": line[:320]})
                    if len(matches) >= limit:
                        return matches
        return matches

    def stage_change(self, relative: str, content: str, reason: str = "") -> dict[str, Any]:
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_PROPOSAL_BYTES:
            raise WorkspaceError(f"Proposed content exceeds the {MAX_PROPOSAL_BYTES}-byte limit.")
        path = self.resolve(relative)
        if path.exists() and not path.is_file():
            raise WorkspaceError("Only regular text files can be changed.")
        try:
            old_bytes = path.read_bytes() if path.exists() else b""
            old_text = old_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise WorkspaceError("The current file cannot be safely edited as UTF-8 text.") from error
        if b"\0" in old_bytes:
            raise WorkspaceError("Binary files cannot be changed by the coding agent.")
        base_sha = hashlib.sha256(old_bytes).hexdigest() if path.exists() else None
        rel = path.relative_to(self.root).as_posix()
        with self._lock:
            if any(item["path"] == rel for item in self._pending.values()):
                raise WorkspaceError("There is already a pending proposal for this file. Revise that proposal instead.")
            change_id = uuid.uuid4().hex
            diff_lines = difflib.unified_diff(
                old_text.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{rel}" if base_sha else "/dev/null",
                tofile=f"b/{rel}",
            )
            diff = "".join(diff_lines) or "(no textual difference)"
            if len(diff) > 30_000:
                diff = diff[:30_000] + "\n… diff truncated …"
            change = {
                "id": change_id,
                "path": rel,
                "reason": str(reason)[:500],
                "base_sha256": base_sha,
                "content": content,
                "diff": diff,
                "created_at": time.time(),
            }
            self._pending[change_id] = change
            return {key: value for key, value in change.items() if key != "content"}

    def pending_changes(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {key: value for key, value in change.items() if key != "content"}
                for change in self._pending.values()
            ]

    def reject_change(self, change_id: str) -> dict[str, str]:
        with self._lock:
            change = self._pending.pop(str(change_id), None)
        if not change:
            raise WorkspaceError("That proposal is no longer available.")
        return {"path": change["path"], "status": "rejected"}

    def apply_change(self, change_id: str) -> dict[str, str]:
        with self._lock:
            change = self._pending.get(str(change_id))
            if not change:
                raise WorkspaceError("That proposal is no longer available.")
            path = self.resolve(change["path"])
            exists = path.exists()
            current = path.read_bytes() if exists else b""
            current_sha = hashlib.sha256(current).hexdigest() if exists else None
            if current_sha != change["base_sha256"]:
                self._pending.pop(str(change_id), None)
                raise WorkspaceError("The file changed since this proposal was prepared. Ask Basira to inspect it again.")
            if path.exists() and not path.is_file():
                raise WorkspaceError("The target is no longer a regular file.")
            path.parent.mkdir(parents=True, exist_ok=True)
            safe_parent = path.parent.resolve(strict=True)
            if not safe_parent.is_relative_to(self.root):
                raise WorkspaceError("The target folder resolves outside the workspace.")
            temp_name = None
            try:
                with tempfile.NamedTemporaryFile("wb", dir=safe_parent, prefix=".basira-", delete=False) as temp:
                    temp.write(change["content"].encode("utf-8"))
                    temp.flush()
                    os.fsync(temp.fileno())
                    temp_name = temp.name
                os.replace(temp_name, path)
            finally:
                if temp_name and os.path.exists(temp_name):
                    os.unlink(temp_name)
            self._pending.pop(str(change_id), None)
            return {"path": change["path"], "status": "applied"}


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List text-oriented project files within a workspace folder. Excludes dependencies, generated files, and secret files.",
            "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Workspace-relative folder, or . for the root"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one UTF-8 text file from the workspace. Never guess file contents; inspect the file first.",
            "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search file text in the workspace and return matching lines with paths and line numbers.",
            "parameters": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "path": {"type": "string", "description": "Workspace-relative folder, or . for the root"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_file_change",
            "description": "Prepare a complete replacement for one UTF-8 file. This only stages a visible diff; it never writes the file. The user must explicitly approve the proposal in the UI.",
            "parameters": {"type": "object", "required": ["path", "content", "reason"], "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "reason": {"type": "string"}}},
        },
    },
]


SYSTEM_PROMPT = """You are Basira, a careful autonomous coding assistant for the selected repository.
Work like an evidence-based software engineer: inspect before changing, use repository tools, distinguish verified facts from assumptions, and report what you actually tested. Keep changes focused. Never claim a file was changed when you only proposed it.

Available tools let you list, search, and read project files, and prepare a complete file replacement as a pending diff. You cannot execute shell commands, access the network, or apply a change. A proposed edit is not written until the user reviews the diff and presses Apply. Do not include secrets in your replies or proposals. Do not read credentials or environment-secret files; they are excluded by the workspace.

For coding tasks, first inspect relevant files and tests, then explain the approach briefly, propose the smallest coherent changes, and identify suitable checks for the user to run. Ask before introducing new dependencies or changing project-wide behavior. Respond in the user's language when practical."""


class OllamaClient:
    def __init__(self, host: str):
        self.host = host.rstrip("/")

    def chat(self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        context_size = os.environ.get("BASIRA_NUM_CTX", "16384")
        try:
            num_ctx = min(65536, max(4096, int(context_size)))
        except ValueError:
            num_ctx = 16384
        body = json.dumps({
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"temperature": 0.2, "num_ctx": num_ctx},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama returned HTTP {error.code}: {detail[:600]}") from error
        except urllib.error.URLError as error:
            raise RuntimeError("Cannot reach Ollama at the configured local address. Start Ollama, then try again.") from error
        if not isinstance(result, dict) or not isinstance(result.get("message"), dict):
            raise RuntimeError("Ollama returned an invalid chat response.")
        return result

    def tags(self) -> list[str]:
        request = urllib.request.Request(f"{self.host}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
            return []
        models = result.get("models", []) if isinstance(result, dict) else []
        return [str(item.get("name", item.get("model", ""))) for item in models if isinstance(item, dict)]


class BasiraAgent:
    def __init__(self, workspace: Workspace, *, model: str | None = None, client: Any | None = None):
        self.workspace = workspace
        self.model = model or os.environ.get("BASIRA_MODEL", "qwen2.5-coder:7b")
        self.client = client or OllamaClient(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))

    def health(self) -> dict[str, Any]:
        installed = self.client.tags() if hasattr(self.client, "tags") else []
        return {
            "model": self.model,
            "workspace": self.workspace.root.name or str(self.workspace.root),
            "ollama_available": bool(installed),
            "model_installed": self.model in installed,
            "installed_models": installed[:30],
        }

    @staticmethod
    def _clean_history(history: Any) -> list[dict[str, str]]:
        if not isinstance(history, list):
            raise WorkspaceError("Conversation history must be a list.")
        cleaned = []
        for item in history[-MAX_REQUEST_HISTORY:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = item.get("content")
            if isinstance(content, str) and len(content) <= MAX_MESSAGE_CHARS:
                cleaned.append({"role": item["role"], "content": content})
        while cleaned and sum(len(item["content"]) for item in cleaned) > MAX_HISTORY_CHARS:
            cleaned.pop(0)
        return cleaned

    def _execute_tool(self, name: str, args: Any) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
        if not isinstance(args, dict):
            return {"error": "Tool arguments must be an object."}, None, "invalid arguments"
        try:
            if name == "list_files":
                items = self.workspace.list_files(str(args.get("path", ".")))
                return {"files": items, "count": len(items)}, None, f"Listed {len(items)} files"
            if name == "read_file":
                path = str(args.get("path", ""))
                contents = self.workspace.read_file(path)
                return {"path": path, "content": contents}, None, f"Read {path}"
            if name == "search_files":
                query = str(args.get("query", ""))
                matches = self.workspace.search_files(query, str(args.get("path", ".")))
                return {"matches": matches, "count": len(matches)}, None, f"Found {len(matches)} matches"
            if name == "propose_file_change":
                proposal = self.workspace.stage_change(
                    str(args.get("path", "")),
                    str(args.get("content", "")),
                    str(args.get("reason", "")),
                )
                return {"proposal_id": proposal["id"], "path": proposal["path"], "approval_required": True}, proposal, f"Prepared a diff for {proposal['path']}"
            return {"error": "Unknown tool."}, None, "Rejected an unknown tool"
        except (WorkspaceError, OSError) as error:
            return {"error": str(error)}, None, f"Tool failed: {str(error)[:160]}"

    def run(self, history: Any, user_message: Any) -> dict[str, Any]:
        if not isinstance(user_message, str) or not user_message.strip() or len(user_message) > MAX_MESSAGE_CHARS:
            raise WorkspaceError(f"Message must contain 1 to {MAX_MESSAGE_CHARS:,} characters.")
        clean_history = self._clean_history(history)
        conversation = clean_history + [{"role": "user", "content": user_message.strip()}]
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation
        proposals: list[dict[str, Any]] = []
        tool_log: list[dict[str, str]] = []
        final_text = ""

        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat(self.model, messages, TOOL_SPECS)
            assistant = response.get("message", {})
            content = assistant.get("content", "")
            calls = assistant.get("tool_calls") or []
            if not calls:
                final_text = content if isinstance(content, str) else ""
                break
            safe_assistant = {"role": "assistant", "content": content, "tool_calls": calls}
            messages.append(safe_assistant)
            for call in calls:
                function = call.get("function", {}) if isinstance(call, dict) else {}
                name = function.get("name", "")
                args = function.get("arguments", {})
                result, proposal, summary = self._execute_tool(name, args)
                if proposal:
                    proposals.append(proposal)
                tool_log.append({"tool": name or "unknown", "summary": summary})
                messages.append({"role": "tool", "tool_name": name or "unknown", "content": json.dumps(result, ensure_ascii=False)})
        else:
            final_text = "I reached the tool-call limit for this turn. Continue the task and I’ll inspect the next part."

        if not final_text.strip():
            final_text = "I finished the available repository checks for this turn."
        response_history = conversation + [{"role": "assistant", "content": final_text}]
        return {
            "reply": final_text,
            "history": response_history[-MAX_REQUEST_HISTORY:],
            "proposals": proposals,
            "tool_log": tool_log,
            "model": self.model,
        }


def run_check(workspace: Workspace, check: str) -> dict[str, Any]:
    if check == "python-tests":
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    elif check == "frontend-build":
        command = ["npm.cmd" if os.name == "nt" else "npm", "run", "build"]
    elif check == "git-diff-check":
        command = ["git", "diff", "--check"]
    else:
        raise WorkspaceError("Choose one of the listed checks.")
    try:
        completed = subprocess.run(
            command,
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        return {
            "check": check,
            "command": " ".join(command),
            "exit_code": completed.returncode,
            "ok": completed.returncode == 0,
            "output": output[-16_000:],
        }
    except FileNotFoundError as error:
        raise WorkspaceError(f"Required command is unavailable: {error.filename}") from error
    except subprocess.TimeoutExpired as error:
        partial = error.stdout or b""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        raise WorkspaceError(f"Check timed out after 120 seconds. {partial[-2_000:]}") from error
