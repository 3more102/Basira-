import "./style.css";

const ui = {
  messages: document.querySelector("#messages"),
  form: document.querySelector("#chat-form"),
  prompt: document.querySelector("#prompt"),
  send: document.querySelector("#send-button"),
  activity: document.querySelector("#activity"),
  health: document.querySelector("#connection-status"),
  workspace: document.querySelector("#workspace-name"),
  model: document.querySelector("#model-name"),
  setupHint: document.querySelector("#setup-hint"),
  refresh: document.querySelector("#refresh-status"),
  newSession: document.querySelector("#new-session"),
  checkResult: document.querySelector("#check-result"),
};

let history = [];
let busy = false;

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}

function scrollToBottom() {
  ui.messages.scrollTop = ui.messages.scrollHeight;
}

function addMessage(role, content, className = "") {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"} ${className}`.trim();
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "YOU" : "B";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.textContent = content;
  bubble.append(paragraph);
  article.append(avatar, bubble);
  ui.messages.append(article);
  scrollToBottom();
  return article;
}

function setBusy(value) {
  busy = value;
  ui.send.disabled = value;
  ui.prompt.disabled = value;
  ui.send.textContent = value ? "…" : "↑";
  ui.form.classList.toggle("is-busy", value);
}

function showActivity(items) {
  if (!items?.length) return;
  ui.activity.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = "Repository inspection";
  const list = document.createElement("ul");
  for (const item of items) {
    const row = document.createElement("li");
    row.textContent = `${item.tool}: ${item.summary}`;
    list.append(row);
  }
  ui.activity.append(title, list);
  ui.activity.hidden = false;
  scrollToBottom();
}

function renderProposal(proposal) {
  const section = document.createElement("section");
  section.className = "proposal-card";
  section.dataset.id = proposal.id;
  const heading = document.createElement("div");
  heading.className = "proposal-heading";
  const title = document.createElement("div");
  const label = document.createElement("span");
  label.className = "proposal-label";
  label.textContent = "REVIEW REQUIRED";
  const path = document.createElement("strong");
  path.className = "proposal-path";
  path.textContent = proposal.path;
  title.append(label, path);
  const state = document.createElement("span");
  state.className = "proposal-state";
  state.textContent = "Pending";
  heading.append(title, state);
  const reason = document.createElement("p");
  reason.className = "proposal-reason";
  reason.textContent = proposal.reason || "Basira proposed this file change.";
  const diff = document.createElement("pre");
  diff.className = "diff-view";
  diff.textContent = proposal.diff;
  const actions = document.createElement("div");
  actions.className = "proposal-actions";
  const reject = document.createElement("button");
  reject.type = "button";
  reject.className = "reject-button";
  reject.textContent = "Reject";
  const apply = document.createElement("button");
  apply.type = "button";
  apply.className = "apply-button";
  apply.textContent = "Apply change";
  apply.addEventListener("click", () => handleProposal(section, state, actions, "apply", proposal.id));
  reject.addEventListener("click", () => handleProposal(section, state, actions, "reject", proposal.id));
  actions.append(reject, apply);
  section.append(heading, reason, diff, actions);
  ui.messages.append(section);
  scrollToBottom();
}

async function handleProposal(card, state, actions, action, id) {
  actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  try {
    const result = await api(`/api/change/${action}`, { id });
    state.textContent = action === "apply" ? "Applied" : "Rejected";
    state.classList.add(action === "apply" ? "state-applied" : "state-rejected");
    card.classList.add("proposal-complete");
    actions.replaceChildren();
    const detail = document.createElement("span");
    detail.textContent = `${result.status}: ${result.path}`;
    actions.append(detail);
  } catch (error) {
    state.textContent = "Needs refresh";
    state.classList.add("state-error");
    const notice = document.createElement("p");
    notice.className = "proposal-error";
    notice.textContent = error.message;
    card.append(notice);
    actions.querySelectorAll("button").forEach((button) => { button.disabled = true; });
  }
}

async function refreshHealth() {
  ui.health.classList.add("checking");
  try {
    const status = await api("/api/health");
    ui.workspace.textContent = status.workspace;
    ui.model.textContent = status.model;
    ui.setupHint.replaceChildren();
    ui.setupHint.hidden = status.model_installed;
    ui.health.replaceChildren();
    const dot = document.createElement("span");
    dot.className = "status-dot";
    const label = document.createElement("span");
    if (status.model_installed) {
      label.textContent = "Local model ready";
      ui.health.className = "status-pill ready";
    } else if (status.ollama_available) {
      label.textContent = "Model not downloaded";
      ui.health.className = "status-pill missing-model";
      ui.setupHint.append(document.createTextNode("Download the configured model: "));
      const command = document.createElement("code");
      command.textContent = `ollama pull ${status.model}`;
      ui.setupHint.append(command);
    } else {
      label.textContent = "Ollama not connected";
      ui.health.className = "status-pill offline";
      ui.setupHint.textContent = "Install and start Ollama, then download the configured model. Setup steps are in the README.";
    }
    ui.health.append(dot, label);
  } catch (error) {
    ui.health.textContent = error.message;
    ui.health.className = "status-pill offline";
    ui.setupHint.hidden = false;
    ui.setupHint.textContent = error.message;
  }
}

async function submitMessage(event) {
  event.preventDefault();
  const message = ui.prompt.value.trim();
  if (!message || busy) return;
  addMessage("user", message);
  ui.prompt.value = "";
  ui.activity.hidden = true;
  setBusy(true);
  try {
    const result = await api("/api/chat", { history, message });
    history = result.history;
    addMessage("assistant", result.reply);
    showActivity(result.tool_log);
    for (const proposal of result.proposals) renderProposal(proposal);
  } catch (error) {
    addMessage("assistant", error.message, "error-message");
  } finally {
    setBusy(false);
    ui.prompt.focus();
  }
}

async function runCheck(button) {
  const check = button.dataset.check;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Running…";
  ui.checkResult.hidden = false;
  ui.checkResult.className = "check-result running";
  ui.checkResult.textContent = `Running ${check}. This runs the selected project check locally.`;
  try {
    const result = await api("/api/checks", { check });
    ui.checkResult.className = `check-result ${result.ok ? "check-ok" : "check-failed"}`;
    const summary = document.createElement("strong");
    summary.textContent = `${result.check}: ${result.ok ? "passed" : `failed (exit ${result.exit_code})`}`;
    const command = document.createElement("code");
    command.textContent = result.command;
    const output = document.createElement("pre");
    output.textContent = result.output || "No output.";
    ui.checkResult.replaceChildren(summary, command, output);
  } catch (error) {
    ui.checkResult.className = "check-result check-failed";
    ui.checkResult.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

ui.form.addEventListener("submit", submitMessage);
ui.prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ui.form.requestSubmit();
  }
  ui.prompt.style.height = "auto";
  ui.prompt.style.height = `${Math.min(ui.prompt.scrollHeight, 180)}px`;
});
ui.refresh.addEventListener("click", refreshHealth);
ui.newSession.addEventListener("click", () => {
  history = [];
  ui.messages.replaceChildren();
  ui.activity.hidden = true;
  addMessage("assistant", "New session started. Tell me what you want to inspect or change.");
});
document.querySelectorAll(".check-button").forEach((button) => button.addEventListener("click", () => runCheck(button)));

refreshHealth();
