# Basira Coding Agent

Basira is a local-first coding agent prototype for repository work. It uses an existing language model through Ollama; it does not train or include its own foundation-model weights, and it is not OpenAI's GPT-6 Astra.

The agent loop can list, read, and search project files. It can prepare complete file changes as reviewable diffs. **Proposed changes remain staged until you press Apply.** The model cannot execute arbitrary shell commands. The UI offers a small allowlist of checks that you start yourself.

## Requirements

- Python 3.10 or newer.
- Node.js 20 or newer for building the interface.
- [Ollama](https://ollama.com/download) running on the same computer by default.
- One coding model downloaded in Ollama. The default is `qwen2.5-coder:7b`; smaller `3b` and `1.5b` variants are available for machines with less memory.

The Ollama model page lists Qwen2.5-Coder sizes from 0.5B to 32B; the listed 7B download is 4.7 GB. Actual memory use depends on runtime settings and context size. See the [model page](https://ollama.com/library/qwen2.5-coder).

## Quick start on Windows PowerShell

In a terminal, download a model once:

```powershell
ollama pull qwen2.5-coder:7b
```

In another terminal, open this folder and build the UI:

```powershell
npm install
npm run build
py server.py
```

Open `http://127.0.0.1:8000`. Ollama must remain running while you use Basira.

For development, run `py server.py` and `npm run dev` in separate terminals. Vite serves the interface at `http://127.0.0.1:5173` and forwards API requests to Basira on port 8000.

## Use Basira on another project

Set `BASIRA_WORKSPACE` to the repository folder before starting the server. Build and launch Basira from this project folder:

```powershell
$env:BASIRA_WORKSPACE = 'C:\path\to\your\repository'
py server.py
```

You can change the model or Ollama endpoint in `.env` using the values from `.env.example`. The endpoint defaults to `http://127.0.0.1:11434`. If you point it at another computer or a hosted endpoint, code snippets used for inference are sent there.

To use a smaller local model:

```powershell
ollama pull qwen2.5-coder:3b
$env:BASIRA_MODEL = 'qwen2.5-coder:3b'
py server.py
```

## Workspace safety

- Basira binds to loopback addresses only. It refuses a public network binding.
- File tools stay inside the selected workspace and block parent traversal and symlinks that resolve outside it.
- File tools skip `.git`, dependencies, generated directories, credentials, `.env`, and common key files. Text reads are capped at 32 KB per file.
- The model can inspect and search text, then stage a diff. It cannot directly write files. Applying a staged diff checks that the original file has not changed since review.
- The agent has no shell tool. The UI's Python tests, frontend build, and Git diff check are fixed commands. Running tests/build can execute code in the repository, so review the project before starting those checks.
- Chat history and pending proposals stay in memory in the browser/server process; Basira does not save session history to disk.
- Source snippets are sent to the configured Ollama endpoint. The default Ollama endpoint is local; a custom endpoint may receive project code.

These controls reduce risk but do not replace reviewing model output and project changes.

## Run tests

```powershell
py -m unittest discover -s tests -v
npm run build
```

Tests cover workspace boundary checks, secret/generated-file exclusions, staged-only edits, stale-file detection, and the model tool-call loop using a mocked model client.

## Current scope

Basira is a focused prototype, not an autonomous model training project. It currently has no multi-agent orchestration, persistent memory, GitHub write access, browser control, or arbitrary terminal execution. Model reasoning and tool-call reliability depend on the selected local model.

## References

- [Ollama tool calling](https://docs.ollama.com/capabilities/tool-calling)
- [Qwen2.5-Coder on Ollama](https://ollama.com/library/qwen2.5-coder)
