# Basira Live Assistant

Basira is an independent, Astra-inspired real-time voice and vision assistant prototype. It streams browser microphone audio and camera frames to Gemini Live and plays the model's spoken responses. It uses an existing hosted multimodal model; it does not train or contain its own foundation-model weights.

## What works in this starter

- Live microphone input with interruption support.
- Camera preview and JPEG frame streaming at about one frame per second.
- Spoken model replies, visible input/output transcripts, and optional typed prompts.
- Mute, pause-camera, clear conversation, and end-session controls.
- A local token issuer that keeps the long-lived API key out of browser code and requests one-use Gemini Live tokens.
- Privacy notice before media sharing; this app does not write mic or camera data to disk.

## Requirements

- Python 3.10 or newer.
- Node.js 20 or newer.
- A Gemini API key with access to Gemini Live. API usage and billing are governed by the provider account and current API terms.
- A modern browser that supports microphone, camera, Web Audio, AudioWorklet, and WebSocket APIs.

Create a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey). Keep it on the local server; never add it to `src/`, `index.html`, or a public repository.

## Run on Windows PowerShell

Open a terminal in this folder:

```powershell
npm install
npm run build
Copy-Item .env.example .env
notepad .env
```

Add the key after `GEMINI_API_KEY=` in `.env`, save the file, then run:

```powershell
py server.py
```

Open `http://127.0.0.1:8000`. Press **Start a conversation** and allow camera/microphone permissions.

For frontend development, run `py server.py` in one terminal and `npm run dev` in another; Vite serves the interface on `http://127.0.0.1:5173` and forwards `/api/token` to the local server.

## Run tests

```powershell
py -m unittest discover -s tests -v
```

The tests validate the local token issuer without making a Gemini API request. A live audio/video session requires a valid API key and real browser permissions.

## Security and scope

- `server.py` binds to `127.0.0.1` by default. Keep it local; do not expose this unauthenticated token endpoint to the internet or a shared network.
- The browser receives an ephemeral token. It is limited to one session start, a fixed Live model, and the audio-response mode; it expires quickly.
- The app sends audio and camera frames to Google's Gemini Live API only while a session is active. Stopping the session turns off the local media tracks. Provider processing and retention are governed by the provider's current terms and settings.
- This is a prototype, not Google's Project Astra and not affiliated with Google. It does not yet have durable cross-session memory, external tools, glasses support, user accounts, or production-grade server authentication.

## Next development steps

1. Add explicit, user-controlled memory with review and deletion.
2. Add document and image context, with a visible list of what was shared.
3. Add selected tools behind confirmation for consequential actions.
4. Add a provider interface and evaluate local/open-weight models for offline modes.
5. Add authentication, quotas, deployment hardening, and a measured evaluation set before any public launch.

## Official references

- [Google DeepMind: Project Astra](https://deepmind.google/models/project-astra/)
- [Gemini Live API overview](https://ai.google.dev/gemini-api/docs/live-api)
- [Gemini Live API: ephemeral tokens](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens)
