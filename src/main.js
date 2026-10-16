import { GoogleGenAI, Modality } from "@google/genai";
import "./style.css";

const MODEL = "gemini-3.8-live";
const $ = (selector) => document.querySelector(selector);

const ui = {
  camera: $("#camera-preview"),
  placeholder: $("#camera-placeholder"),
  stage: $("#visual-stage"),
  stageStatus: $("#stage-status"),
  stageCaption: $("#stage-caption"),
  cameraLabel: $("#camera-label"),
  frameStatus: $("#frame-status"),
  liveIndicator: $("#live-indicator"),
  subtitle: $("#control-subtitle"),
  start: $("#start-button"),
  startLabel: $("#start-label"),
  startIcon: $("#start-icon"),
  mute: $("#mute-button"),
  cameraToggle: $("#camera-button"),
  textInput: $("#text-input"),
  send: $("#send-button"),
  textForm: $("#text-form"),
  log: $("#conversation-log"),
  welcome: $("#welcome-card"),
  toast: $("#toast"),
  privacy: $("#privacy-dialog"),
};

let session = null;
let mediaStream = null;
let audioContext = null;
let audioSource = null;
let worklet = null;
let videoTimer = null;
let cameraEnabled = false;
let microphoneMuted = false;
let nextAudioStart = 0;
let scheduledAudio = new Set();
let activeUserLine = null;
let activeAssistantLine = null;
let toastTimer = null;

function setStatus(state, message) {
  ui.stageStatus.textContent = state.toUpperCase();
  ui.stageCaption.textContent = message;
  const active = state === "Live" || state === "Listening" || state === "Thinking";
  ui.liveIndicator.classList.toggle("active", active);
  ui.stage.classList.toggle("is-live", state === "Live" || state === "Listening");
}

function showToast(message) {
  ui.toast.textContent = message;
  ui.toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ui.toast.classList.remove("visible"), 4200);
}

function addLine(kind, text = "") {
  ui.welcome?.remove();
  const row = document.createElement("div");
  row.className = `message ${kind}`;
  const badge = document.createElement("span");
  badge.className = "message-badge";
  badge.textContent = kind === "assistant" ? "B" : "YOU";
  const body = document.createElement("p");
  body.textContent = text;
  row.append(badge, body);
  ui.log.append(row);
  ui.log.scrollTop = ui.log.scrollHeight;
  return body;
}

function resetTranscriptLines() {
  activeUserLine = null;
  activeAssistantLine = null;
}

function appendTranscript(kind, text) {
  if (!text) return;
  if (kind === "user") activeUserLine ??= addLine("user");
  if (kind === "assistant") activeAssistantLine ??= addLine("assistant");
  const target = kind === "user" ? activeUserLine : activeAssistantLine;
  target.textContent += text;
  ui.log.scrollTop = ui.log.scrollHeight;
}

function base64ToBytes(value) {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return btoa(binary);
}

function resampleTo16k(samples, sourceRate) {
  if (sourceRate === 16000) return samples;
  const ratio = sourceRate / 16000;
  const length = Math.floor(samples.length / ratio);
  const output = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), samples.length);
    let sum = 0;
    for (let j = start; j < end; j += 1) sum += samples[j];
    output[i] = sum / Math.max(1, end - start);
  }
  return output;
}

function floatToPcm16(samples) {
  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    pcm[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return new Uint8Array(pcm.buffer);
}

async function startMicrophone() {
  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule(new URL("./pcm-worklet.js", import.meta.url));
  const audioTrack = mediaStream.getAudioTracks()[0];
  audioSource = audioContext.createMediaStreamSource(new MediaStream([audioTrack]));
  worklet = new AudioWorkletNode(audioContext, "basira-pcm-capture");
  const silentGain = audioContext.createGain();
  silentGain.gain.value = 0;
  audioSource.connect(worklet);
  worklet.connect(silentGain).connect(audioContext.destination);
  worklet.port.onmessage = ({ data }) => {
    if (!session || microphoneMuted || !data?.samples) return;
    const input = new Float32Array(data.samples);
    const pcm = floatToPcm16(resampleTo16k(input, data.sampleRate));
    session.sendRealtimeInput({
      audio: { data: bytesToBase64(pcm), mimeType: "audio/pcm;rate=16000" },
    });
  };
}

async function startCamera() {
  const cameraTrack = mediaStream.getVideoTracks()[0];
  ui.camera.srcObject = new MediaStream([cameraTrack]);
  await ui.camera.play();
  cameraEnabled = true;
  ui.placeholder.classList.add("hidden");
  ui.cameraLabel.textContent = "CAMERA ON";
  ui.frameStatus.textContent = "FRAME STREAM ACTIVE · 1 FPS";
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { alpha: false });
  videoTimer = setInterval(() => {
    if (!session || !cameraEnabled || ui.camera.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return;
    const scale = Math.min(1, 640 / ui.camera.videoWidth, 480 / ui.camera.videoHeight);
    canvas.width = Math.max(1, Math.round(ui.camera.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(ui.camera.videoHeight * scale));
    context.drawImage(ui.camera, 0, 0, canvas.width, canvas.height);
    const base64 = canvas.toDataURL("image/jpeg", 0.72).split(",")[1];
    session.sendRealtimeInput({ video: { data: base64, mimeType: "image/jpeg" } });
  }, 1100);
}

function playAudioChunk(base64) {
  if (!audioContext) return;
  const bytes = base64ToBytes(base64);
  const pcm = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
  const floatSamples = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i += 1) floatSamples[i] = pcm[i] / 32768;
  const buffer = audioContext.createBuffer(1, floatSamples.length, 24000);
  buffer.copyToChannel(floatSamples, 0);
  const source = audioContext.createBufferSource();
  source.buffer = buffer;
  source.connect(audioContext.destination);
  const startAt = Math.max(audioContext.currentTime + 0.02, nextAudioStart);
  source.start(startAt);
  nextAudioStart = startAt + buffer.duration;
  scheduledAudio.add(source);
  source.onended = () => scheduledAudio.delete(source);
}

function stopQueuedAudio() {
  for (const source of scheduledAudio) {
    try { source.stop(); } catch { /* already stopped */ }
  }
  scheduledAudio.clear();
  nextAudioStart = 0;
}

function handleModelMessage(message) {
  const content = message.serverContent;
  if (!content) return;
  if (content.interrupted) {
    stopQueuedAudio();
    setStatus("Listening", "I’m listening.");
    return;
  }
  const inputText = content.inputTranscription?.text;
  const outputText = content.outputTranscription?.text;
  if (inputText) appendTranscript("user", inputText);
  if (outputText) appendTranscript("assistant", outputText);
  const parts = content.modelTurn?.parts ?? [];
  for (const part of parts) {
    if (part.inlineData?.mimeType?.startsWith("audio/pcm") && part.inlineData.data) {
      playAudioChunk(part.inlineData.data);
    }
    if (part.text && !outputText) appendTranscript("assistant", part.text);
  }
  if (content.turnComplete) {
    resetTranscriptLines();
    setStatus("Listening", "I’m listening.");
  } else if (parts.length || outputText) {
    setStatus("Thinking", "Putting it together…");
  }
}

async function beginSession() {
  ui.start.disabled = true;
  ui.startLabel.textContent = "Connecting…";
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    const response = await fetch("/api/token", { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error || `Token request failed (${response.status})`);
    }
    const { token } = await response.json();
    if (!token) throw new Error("The local server returned no session token.");
    await startMicrophone();
    const ai = new GoogleGenAI({ apiKey: token, httpOptions: { apiVersion: "v1beta" } });
    session = await ai.live.connect({
      model: MODEL,
      config: {
        responseModalities: [Modality.AUDIO],
        inputAudioTranscription: {},
        outputAudioTranscription: {},
        sessionResumption: {},
        systemInstruction: {
          parts: [{ text: "You are Basira, a clear, friendly, concise visual voice assistant. Respond naturally in the language the user speaks. Use the live camera frames and conversation context to answer. If visual details are unclear, say so instead of guessing. Never claim to take actions outside this conversation." }],
        },
      },
      callbacks: {
        onopen: () => {
          setStatus("Listening", "I’m listening. Show me what you want to explore.");
        },
        onmessage: handleModelMessage,
        onerror: (event) => {
          console.error("Live model error", event);
          showToast(event.message || "The live model connection encountered an error.");
        },
        onclose: (event) => {
          if (session) finishSession(false);
          if (event?.reason) console.info("Live session closed:", event.reason);
        },
      },
    });
    await startCamera();
    ui.start.classList.add("stop-button");
    ui.startLabel.textContent = "End conversation";
    ui.startIcon.textContent = "■";
    ui.start.disabled = false;
    ui.mute.disabled = false;
    ui.cameraToggle.disabled = false;
    ui.textInput.disabled = false;
    ui.send.disabled = false;
    ui.subtitle.textContent = "Mic and camera are active for this session.";
    setStatus("Live", "I’m here. What would you like to know?");
    resetTranscriptLines();
  } catch (error) {
    console.error(error);
    await finishSession(false);
    ui.start.disabled = false;
    ui.startLabel.textContent = "Start a conversation";
    ui.startIcon.textContent = "◉";
    setStatus("Standby", "Ready when you are.");
    showToast(error.message || "Could not start the live session.");
  }
}

async function finishSession(closeModel = true) {
  const oldSession = session;
  session = null;
  if (closeModel && oldSession) {
    try { oldSession.close(); } catch { /* session may already be closed */ }
  }
  clearInterval(videoTimer);
  videoTimer = null;
  if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
  mediaStream = null;
  if (audioSource) audioSource.disconnect();
  audioSource = null;
  if (worklet) {
    worklet.port.onmessage = null;
    worklet.disconnect();
  }
  worklet = null;
  if (audioContext) await audioContext.close().catch(() => {});
  audioContext = null;
  stopQueuedAudio();
  ui.camera.srcObject = null;
  ui.placeholder.classList.remove("hidden");
  ui.cameraLabel.textContent = "CAMERA OFF";
  ui.frameStatus.textContent = "FRAME STREAM PAUSED";
  ui.start.classList.remove("stop-button");
  ui.startLabel.textContent = "Start a conversation";
  ui.startIcon.textContent = "◉";
  ui.start.disabled = false;
  ui.mute.disabled = true;
  ui.cameraToggle.disabled = true;
  ui.textInput.disabled = true;
  ui.send.disabled = true;
  ui.mute.classList.remove("is-muted");
  ui.mute.querySelector("span:last-child").textContent = "Mute";
  ui.cameraToggle.querySelector("span:last-child").textContent = "Camera";
  ui.subtitle.textContent = "Your camera and microphone are off.";
  cameraEnabled = false;
  microphoneMuted = false;
  setStatus("Standby", "Ready when you are.");
}

ui.start.addEventListener("click", () => session ? finishSession() : beginSession());

ui.mute.addEventListener("click", () => {
  microphoneMuted = !microphoneMuted;
  ui.mute.classList.toggle("is-muted", microphoneMuted);
  ui.mute.querySelector("span:last-child").textContent = microphoneMuted ? "Unmute" : "Mute";
  ui.subtitle.textContent = microphoneMuted ? "Microphone muted. Camera is still sharing." : "Mic and camera are active for this session.";
});

ui.cameraToggle.addEventListener("click", () => {
  cameraEnabled = !cameraEnabled;
  const track = mediaStream?.getVideoTracks()[0];
  if (track) track.enabled = cameraEnabled;
  ui.placeholder.classList.toggle("hidden", cameraEnabled);
  ui.cameraLabel.textContent = cameraEnabled ? "CAMERA ON" : "CAMERA PAUSED";
  ui.frameStatus.textContent = cameraEnabled ? "FRAME STREAM ACTIVE · 1 FPS" : "FRAME STREAM PAUSED";
  ui.cameraToggle.querySelector("span:last-child").textContent = cameraEnabled ? "Camera" : "Resume";
  ui.subtitle.textContent = cameraEnabled ? "Mic and camera are active for this session." : "Microphone active. Camera paused.";
});

ui.textForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = ui.textInput.value.trim();
  if (!text || !session) return;
  addLine("user", text);
  resetTranscriptLines();
  session.sendRealtimeInput({ text });
  ui.textInput.value = "";
  setStatus("Thinking", "Let me think about that…");
});

$("#clear-button").addEventListener("click", () => {
  ui.log.replaceChildren();
  resetTranscriptLines();
  if (!session) {
    const welcome = document.createElement("div");
    welcome.className = "welcome-card";
    welcome.innerHTML = '<div class="welcome-symbol">✳</div><strong>A little more context.</strong><p>Point your camera at something and ask me about it. I’m here to help you explore.</p><span class="suggestion-chip">“What am I looking at?”</span>';
    ui.log.append(welcome);
    ui.welcome = welcome;
  }
});

$("#privacy-button").addEventListener("click", () => ui.privacy.showModal());
$("#close-dialog").addEventListener("click", () => ui.privacy.close());
$("#dialog-done").addEventListener("click", () => ui.privacy.close());
ui.privacy.addEventListener("click", (event) => {
  if (event.target === ui.privacy) ui.privacy.close();
});

window.addEventListener("beforeunload", () => {
  clearInterval(videoTimer);
  mediaStream?.getTracks().forEach((track) => track.stop());
  session?.close();
});
