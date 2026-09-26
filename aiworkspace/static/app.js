// @ts-check
import { applyLang, getLang, setLang, t } from "./i18n.js";
import { h, renderMarkdown } from "./markdown.js";

/**
 * @typedef {{id: string, title: string, created_at: number, updated_at: number}} Conversation
 * @typedef {{id: string, conversation_id: string, role: "user"|"assistant", content: string,
 *   status: "complete"|"streaming"|"cancelled"|"error", provider: string|null, model: string|null,
 *   simulated: boolean, error: string|null, stop_reason: string|null, created_at: number}} Message
 * @typedef {{provider: string, model: string, simulated: boolean,
 *   limits: {max_message_chars: number}}} Status
 * @typedef {{cid: string, messages: Message[], assistant: Message|null, controller: AbortController,
 *   stopTimer: number|undefined}} Stream
 */

const $ = (/** @type {string} */ id) => /** @type {HTMLElement} */ (document.getElementById(id));
const els = {
  sidebar: $("sidebar"),
  scrim: $("scrim"),
  brand: $("brand"),
  newChat: /** @type {HTMLButtonElement} */ ($("new-chat")),
  convHeading: $("conv-heading"),
  convState: $("conv-state"),
  convList: $("conv-list"),
  localOnly: $("local-only"),
  langToggle: $("lang-toggle"),
  menuBtn: $("menu-btn"),
  title: $("conv-title"),
  badge: $("mode-badge"),
  demoBanner: $("demo-banner"),
  messages: $("messages"),
  alert: $("alert"),
  alertText: $("alert-text"),
  alertClose: $("alert-close"),
  composer: /** @type {HTMLFormElement} */ ($("composer")),
  input: /** @type {HTMLTextAreaElement} */ ($("input")),
  inputLabel: $("input-label"),
  counter: $("counter"),
  send: /** @type {HTMLButtonElement} */ ($("send")),
  stop: /** @type {HTMLButtonElement} */ ($("stop")),
};

const state = {
  /** @type {Status|null} */ status: null,
  /** @type {Conversation[]} */ conversations: [],
  /** @type {"loading"|"ready"|"error"} */ listState: "loading",
  /** @type {string|null} */ currentId: null,
  /** @type {Message[]} */ messages: [],
  /** @type {"idle"|"loading"|"ready"|"error"} */ convState: "idle",
  /** @type {string|null} */ renamingId: null,
  /** @type {Stream|null} */ stream: null,
  /** @type {string|null} */ lastFailedText: null,
};

// ---------------------------------------------------------------- API

class ApiError extends Error {
  /** @param {number} status @param {string} message */
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

/**
 * @param {string} path
 * @param {RequestInit & {json?: unknown}} [opts]
 */
async function api(path, opts = {}) {
  const { json, ...init } = opts;
  const headers = new Headers(init.headers);
  if (init.method && init.method !== "GET") headers.set("X-AIWS-Request", "1");
  if (json !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(json);
  }
  let res;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, t("networkError"));
  }
  if (!res.ok) {
    let message = `${res.status}`;
    try {
      message = (await res.json()).error || message;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

// ---------------------------------------------------------------- helpers

function showAlert(/** @type {string} */ text) {
  els.alertText.textContent = text;
  els.alert.hidden = false;
}

function hideAlert() {
  els.alert.hidden = true;
}

function currentConversation() {
  return state.conversations.find((c) => c.id === state.currentId) ?? null;
}

function displayTitle(/** @type {Conversation} */ c) {
  return c.title === "New conversation" ? t("untitled") : c.title;
}

function setDrawer(/** @type {boolean} */ open) {
  els.sidebar.classList.toggle("open", open);
  els.scrim.hidden = !open;
  els.menuBtn.setAttribute("aria-expanded", String(open));
}

function isNearBottom() {
  const m = els.messages;
  return m.scrollHeight - m.scrollTop - m.clientHeight < 120;
}

function scrollToBottom() {
  els.messages.scrollTop = els.messages.scrollHeight;
}

// ---------------------------------------------------------------- rendering: static text

function renderStaticText() {
  applyLang();
  els.brand.textContent = t("appName");
  els.newChat.textContent = t("newChat");
  els.convHeading.textContent = t("conversations");
  els.localOnly.textContent = t("localOnly");
  els.langToggle.textContent = t("language");
  els.langToggle.setAttribute("aria-label", t("languageLabel"));
  els.langToggle.setAttribute("lang", getLang() === "he" ? "en" : "he");
  els.menuBtn.setAttribute("aria-label", t("menu"));
  els.input.placeholder = t("placeholder");
  els.inputLabel.textContent = t("placeholder");
  els.send.textContent = t("send");
  els.stop.textContent = t("stop");
  els.demoBanner.textContent = t("demoBanner");
  renderBadge();
}

function renderBadge() {
  const s = state.status;
  if (!s) {
    els.badge.hidden = true;
    els.demoBanner.hidden = true;
    return;
  }
  els.badge.hidden = false;
  els.badge.className = `mode-badge ${s.simulated ? "demo" : "live"}`;
  els.badge.textContent = s.simulated ? t("demoBadge") : `${t("liveBadge")} · ${s.model}`;
  els.badge.title = s.simulated ? t("demoBanner") : `${s.provider} / ${s.model}`;
  els.demoBanner.hidden = !s.simulated;
}

// ---------------------------------------------------------------- rendering: sidebar

function renderList() {
  els.convList.replaceChildren();
  els.convState.replaceChildren();
  if (state.listState === "loading") {
    els.convState.textContent = t("loading");
    return;
  }
  if (state.listState === "error") {
    const retry = h("button", { type: "button", class: "btn btn-ghost small" }, [t("retry")]);
    retry.addEventListener("click", loadConversations);
    els.convState.append(h("span", {}, [t("loadFailed")]), " ", retry);
    return;
  }
  if (!state.conversations.length) {
    els.convState.textContent = t("noConversations");
    return;
  }
  for (const c of state.conversations) els.convList.append(renderListItem(c));
}

function renderListItem(/** @type {Conversation} */ c) {
  const active = c.id === state.currentId;
  const li = h("li", { class: `conv-item${active ? " active" : ""}` });
  if (state.renamingId === c.id) {
    const input = /** @type {HTMLInputElement} */ (
      h("input", { class: "rename-input", dir: "auto", maxlength: "120", "aria-label": t("rename") })
    );
    input.value = c.title === "New conversation" ? "" : c.title;
    const form = h("form", { class: "rename-form" }, [input]);
    const cancel = () => {
      state.renamingId = null;
      renderList();
    };
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      renameConversation(c.id, input.value);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") cancel();
    });
    input.addEventListener("blur", () => {
      if (state.renamingId === c.id) renameConversation(c.id, input.value);
    });
    li.append(form);
    queueMicrotask(() => {
      input.focus();
      input.select();
    });
    return li;
  }
  const open = h("button", { type: "button", class: "conv-open", dir: "auto" }, [displayTitle(c)]);
  if (active) open.setAttribute("aria-current", "page");
  if (state.stream?.cid === c.id) open.append(h("span", { class: "dot-live", "aria-hidden": "true" }));
  open.addEventListener("click", () => selectConversation(c.id));
  const rename = h("button", { type: "button", class: "icon-btn btn-ghost", title: t("rename"), "aria-label": `${t("rename")}: ${c.title}` }, ["✎"]);
  rename.addEventListener("click", () => {
    state.renamingId = c.id;
    renderList();
  });
  const del = h("button", { type: "button", class: "icon-btn btn-ghost", title: t("delete"), "aria-label": `${t("delete")}: ${c.title}` }, ["🗑"]);
  del.addEventListener("click", () => deleteConversation(c.id));
  li.append(open, h("span", { class: "conv-actions" }, [rename, del]));
  return li;
}

// ---------------------------------------------------------------- rendering: messages

const mdLabels = () => ({ copy: t("copy"), copied: t("copied") });

function messageNode(/** @type {Message} */ m, /** @type {boolean} */ live = false) {
  const body = h("div", { class: "msg-body" });
  if (m.role === "user") {
    body.append(h("p", { dir: "auto", class: "plain" }, [m.content]));
  } else if (m.content) {
    body.append(renderMarkdown(m.content, mdLabels()));
  }
  if (live && !m.content) {
    body.append(h("div", { class: "typing", role: "status" }, [h("span", {}, []), h("span", {}, []), h("span", {}, []), h("span", { class: "visually-hidden" }, [t("thinking")])]));
  }
  const node = h("article", { class: `msg msg-${m.role}`, "data-id": m.id }, [
    h("div", { class: "msg-role visually-hidden" }, [m.role === "user" ? t("you") : t("assistant")]),
    body,
  ]);
  if (m.role === "assistant") {
    const meta = [];
    if (m.simulated) meta.push(h("span", { class: "tag tag-demo" }, [t("simulated")]));
    if (m.status === "cancelled") meta.push(h("span", { class: "tag" }, [t("stopped")]));
    if (m.stop_reason === "max_tokens") meta.push(h("span", { class: "tag" }, [t("truncated")]));
    if (m.stop_reason === "refusal") meta.push(h("span", { class: "tag tag-warn" }, [t("refused")]));
    if (m.status === "error") {
      const err = h("div", { class: "msg-error", role: "alert", dir: "auto" }, [m.error || t("interrupted")]);
      if (state.lastFailedText && !state.stream) {
        const retry = h("button", { type: "button", class: "btn btn-ghost small" }, [t("retry")]);
        retry.addEventListener("click", () => {
          const text = state.lastFailedText;
          if (text) sendMessage(text);
        });
        err.append(" ", retry);
      }
      node.append(err);
    }
    if (meta.length) node.append(h("div", { class: "msg-meta" }, meta));
  }
  return node;
}

function renderMessages() {
  const stick = isNearBottom();
  els.messages.replaceChildren();
  const streamHere = state.stream && state.stream.cid === state.currentId;
  els.messages.setAttribute("aria-busy", String(state.convState === "loading" || !!streamHere));

  if (state.convState === "loading") {
    els.messages.append(h("div", { class: "center muted" }, [t("loading")]));
    return;
  }
  if (state.convState === "error") {
    const retry = h("button", { type: "button", class: "btn btn-ghost" }, [t("retry")]);
    retry.addEventListener("click", () => state.currentId && selectConversation(state.currentId));
    els.messages.append(h("div", { class: "center" }, [h("p", {}, [t("loadFailed")]), retry]));
    return;
  }
  const list = streamHere && state.stream ? state.stream.messages : state.messages;
  if (!list.length) {
    els.messages.append(
      h("div", { class: "empty" }, [
        h("h2", {}, [t("emptyTitle")]),
        h("p", { class: "muted" }, [t("emptyBody")]),
      ]),
    );
    return;
  }
  const inner = h("div", { class: "messages-inner" });
  for (const m of list) {
    const live = !!streamHere && state.stream?.assistant?.id === m.id;
    inner.append(messageNode(m, live));
  }
  els.messages.append(inner);
  if (stick) scrollToBottom();
}

let rafPending = false;
function scheduleStreamRender() {
  if (rafPending) return;
  rafPending = true;
  requestAnimationFrame(() => {
    rafPending = false;
    const s = state.stream;
    if (!s || s.cid !== state.currentId || !s.assistant) return;
    const stick = isNearBottom();
    const old = els.messages.querySelector(`[data-id="${s.assistant.id}"]`);
    const fresh = messageNode(s.assistant, true);
    if (old) old.replaceWith(fresh);
    else renderMessages();
    if (stick) scrollToBottom();
  });
}

function renderComposer() {
  const streaming = !!state.stream;
  const streamHere = streaming && state.stream?.cid === state.currentId;
  els.stop.hidden = !streamHere;
  els.send.hidden = !!streamHere;
  const max = state.status?.limits.max_message_chars ?? 16000;
  const len = els.input.value.trim().length;
  const over = len > max;
  els.counter.textContent = len > max * 0.8 ? `${len.toLocaleString()} / ${max.toLocaleString()}` : "";
  els.counter.classList.toggle("over", over);
  els.send.disabled = streaming || !len || over;
  els.send.title = streaming ? t("busyElsewhere") : over ? t("tooLong") : "";
}

function renderHeader() {
  const c = currentConversation();
  els.title.textContent = c ? displayTitle(c) : t("appName");
  document.title = c ? `${displayTitle(c)} · AI Workspace` : "AI Workspace";
}

function renderAll() {
  renderStaticText();
  renderList();
  renderHeader();
  renderMessages();
  renderComposer();
}

// ---------------------------------------------------------------- actions

async function loadStatus() {
  try {
    state.status = await (await api("/api/status")).json();
  } catch {
    state.status = null;
  }
  renderBadge();
  renderComposer();
}

async function loadConversations() {
  state.listState = "loading";
  renderList();
  try {
    const data = await (await api("/api/conversations")).json();
    state.conversations = data.conversations;
    state.listState = "ready";
  } catch {
    state.listState = "error";
  }
  renderList();
  renderHeader();
}

async function selectConversation(/** @type {string} */ id) {
  setDrawer(false);
  hideAlert();
  state.currentId = id;
  state.convState = "loading";
  state.lastFailedText = null;
  try {
    history.replaceState(null, "", `#${id}`);
  } catch {
    /* ignore */
  }
  renderList();
  renderHeader();
  renderMessages();
  renderComposer();
  if (state.stream?.cid === id) {
    state.convState = "ready";
    renderMessages();
    return;
  }
  try {
    const data = await (await api(`/api/conversations/${id}`)).json();
    if (state.currentId !== id) return;
    state.messages = data.messages;
    state.convState = "ready";
  } catch (err) {
    if (state.currentId !== id) return;
    if (err instanceof ApiError && (err.status === 404 || err.status === 400)) {
      state.conversations = state.conversations.filter((c) => c.id !== id);
      state.currentId = null;
      state.messages = [];
      state.convState = "idle";
      showAlert(t("notFound"));
      renderAll();
      return;
    }
    state.convState = "error";
  }
  renderMessages();
  renderComposer();
  els.input.focus({ preventScroll: true });
  scrollToBottom();
}

function newChat() {
  setDrawer(false);
  hideAlert();
  state.currentId = null;
  state.messages = [];
  state.convState = "idle";
  state.lastFailedText = null;
  try {
    history.replaceState(null, "", location.pathname);
  } catch {
    /* ignore */
  }
  renderAll();
  els.input.focus();
}

async function renameConversation(/** @type {string} */ id, /** @type {string} */ title) {
  state.renamingId = null;
  const c = state.conversations.find((x) => x.id === id);
  const next = title.trim();
  if (!c || !next || next === c.title) {
    renderList();
    return;
  }
  try {
    const data = await (await api(`/api/conversations/${id}`, { method: "PATCH", json: { title: next } })).json();
    Object.assign(c, data.conversation);
  } catch (err) {
    showAlert(err instanceof Error ? err.message : String(err));
  }
  renderList();
  renderHeader();
}

async function deleteConversation(/** @type {string} */ id) {
  if (!confirm(t("confirmDelete"))) return;
  try {
    await api(`/api/conversations/${id}`, { method: "DELETE" });
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) {
      showAlert(err instanceof Error ? err.message : String(err));
      return;
    }
  }
  if (state.stream?.cid === id) state.stream.controller.abort();
  state.conversations = state.conversations.filter((c) => c.id !== id);
  if (state.currentId === id) newChat();
  else renderList();
}

/**
 * Parse a text/event-stream body.
 * @param {ReadableStream<Uint8Array>} body
 * @param {(event: string, data: any) => void} onEvent
 */
async function readSSE(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      const data = [];
      for (const line of chunk.split("\n")) {
        if (line.startsWith(":")) continue;
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length) onEvent(event, JSON.parse(data.join("\n")));
    }
  }
}

async function sendMessage(/** @type {string} */ text) {
  if (state.stream) return;
  hideAlert();
  let cid = state.currentId;
  if (!cid) {
    try {
      const data = await (await api("/api/conversations", { method: "POST" })).json();
      state.conversations.unshift(data.conversation);
      state.listState = "ready";
      cid = data.conversation.id;
      state.currentId = cid;
      state.messages = [];
      state.convState = "ready";
      try {
        history.replaceState(null, "", `#${cid}`);
      } catch {
        /* ignore */
      }
    } catch (err) {
      showAlert(err instanceof Error ? err.message : String(err));
      return;
    }
  }
  const convId = /** @type {string} */ (cid);
  const controller = new AbortController();
  /** @type {Stream} */
  const stream = {
    cid: convId,
    messages: [],
    assistant: null,
    controller,
    stopTimer: undefined,
  };
  // Show the user's message immediately; replaced by the stored one on "start".
  const pendingUser = /** @type {Message} */ ({
    id: "pending", conversation_id: convId, role: "user", content: text, status: "complete",
    provider: null, model: null, simulated: false, error: null, stop_reason: null, created_at: Date.now() / 1000,
  });
  stream.messages = [...state.messages, pendingUser];
  state.stream = stream;
  state.lastFailedText = null;
  els.input.value = "";
  autosize();
  renderAll();
  scrollToBottom();

  /** @type {Message|null} */
  let finalMsg = null;
  let failure = "";
  try {
    const res = await api(`/api/conversations/${convId}/messages`, {
      method: "POST",
      json: { content: text },
      signal: controller.signal,
    });
    if (!res.body) throw new ApiError(0, t("networkError"));
    await readSSE(res.body, (event, data) => {
      if (event === "start") {
        stream.messages = [
          ...stream.messages.filter((m) => m.id !== "pending"),
          data.user_message,
          data.assistant_message,
        ];
        stream.assistant = data.assistant_message;
        if (data.conversation) {
          const c = state.conversations.find((x) => x.id === convId);
          if (c) Object.assign(c, data.conversation);
          renderList();
          renderHeader();
        }
        renderMessages();
      } else if (event === "delta" && stream.assistant) {
        stream.assistant.content += data.text;
        scheduleStreamRender();
      } else if (event === "done" || event === "error") {
        if (data.assistant_message) finalMsg = data.assistant_message;
        if (event === "error") failure = data.message || t("networkError");
      }
    });
    if (!finalMsg && !failure) failure = t("networkError");
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // Stopped by the user; the server stores the partial reply as cancelled.
      if (stream.assistant) finalMsg = { ...stream.assistant, status: "cancelled", stop_reason: "cancelled" };
    } else {
      failure = err instanceof Error ? err.message : String(err);
      if (err instanceof ApiError && err.status && err.status !== 0) {
        // Rejected before streaming (validation, rate limit, busy): let the user edit and resend.
        if (!els.input.value) els.input.value = text;
        autosize();
      }
    }
  } finally {
    clearTimeout(stream.stopTimer);
  }

  const kept = stream.messages.filter((m) => m.id !== "pending" && m.id !== stream.assistant?.id);
  if (finalMsg) kept.push(finalMsg);
  else if (stream.assistant) kept.push({ ...stream.assistant, status: "error", error: failure });
  if (failure) state.lastFailedText = text;
  state.stream = null;
  const c = state.conversations.find((x) => x.id === convId);
  if (c) {
    c.updated_at = Date.now() / 1000;
    state.conversations = [c, ...state.conversations.filter((x) => x.id !== convId)];
  }
  if (state.currentId === convId) {
    state.messages = stream.assistant || !failure ? kept : state.messages;
    if (failure && !stream.assistant) showAlert(failure);
  }
  renderAll();
}

async function stopStreaming() {
  const s = state.stream;
  if (!s) return;
  els.stop.disabled = true;
  try {
    await api(`/api/conversations/${s.cid}/cancel`, { method: "POST" });
  } catch {
    /* fall through to abort */
  }
  // The server normally finishes within one upstream event; abort if it doesn't.
  s.stopTimer = window.setTimeout(() => s.controller.abort(), 1500);
  els.stop.disabled = false;
}

// ---------------------------------------------------------------- composer

function autosize() {
  els.input.style.height = "auto";
  els.input.style.height = `${Math.min(els.input.scrollHeight, window.innerHeight * 0.4)}px`;
  renderComposer();
}

els.input.addEventListener("input", autosize);
els.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    els.composer.requestSubmit();
  }
});
els.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.input.value.trim();
  const max = state.status?.limits.max_message_chars ?? 16000;
  if (!text || state.stream) return;
  if (text.length > max) {
    showAlert(t("tooLong"));
    return;
  }
  sendMessage(text);
});
els.stop.addEventListener("click", stopStreaming);
els.newChat.addEventListener("click", newChat);
els.alertClose.addEventListener("click", hideAlert);
els.menuBtn.addEventListener("click", () => setDrawer(!els.sidebar.classList.contains("open")));
els.scrim.addEventListener("click", () => setDrawer(false));
els.langToggle.addEventListener("click", () => {
  setLang(getLang() === "he" ? "en" : "he");
  renderAll();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (els.sidebar.classList.contains("open")) setDrawer(false);
    else if (state.stream && state.stream.cid === state.currentId) stopStreaming();
  }
});

// ---------------------------------------------------------------- boot

async function boot() {
  renderAll();
  await Promise.all([loadStatus(), loadConversations()]);
  const fromHash = location.hash.slice(1);
  if (/^[0-9a-f]{32}$/.test(fromHash) && state.conversations.some((c) => c.id === fromHash)) {
    await selectConversation(fromHash);
  } else {
    renderAll();
    els.input.focus();
  }
}

boot();
