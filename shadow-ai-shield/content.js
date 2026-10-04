/*
 * Shadow AI Shield — content script.
 *
 * Watches prompt inputs (<textarea> and contenteditable editors such as
 * ProseMirror on ChatGPT/Claude and Quill on Gemini) and replaces detected PII
 * with placeholders like [EMAIL] before the prompt is sent. Only the data
 * *type* is reported to the background worker — never the value itself.
 */
(() => {
  "use strict";

  const { findMatches, maskText, placeholder } = globalThis.ShadowPII;
  const DEBOUNCE_MS = 400;

  let enabled = true;
  let masking = false; // true while we are editing, so our own input events are ignored
  const timers = new WeakMap();

  chrome.storage.local.get({ enabled: true }, (s) => {
    enabled = s.enabled;
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.enabled) enabled = changes.enabled.newValue;
  });

  // ---------------------------------------------------------------------------
  // Target resolution

  function editableFrom(event) {
    const node = event.composedPath ? event.composedPath()[0] : event.target;
    if (!(node instanceof Element)) return null;
    if (node instanceof HTMLTextAreaElement) return node;
    if (node instanceof HTMLInputElement && node.type === "text") return node;
    const ce = node.closest('[contenteditable="true"], [contenteditable=""]');
    return ce || null;
  }

  // ---------------------------------------------------------------------------
  // Masking

  const nativeValueSetter = {
    textarea: Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set,
    input: Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set,
  };

  function maskTextControl(el) {
    const { text, matches } = maskText(el.value);
    if (matches.length === 0) return [];
    const caretFromEnd = el.value.length - (el.selectionEnd ?? el.value.length);
    // Use the native setter so React-controlled inputs notice the change.
    const setter = el instanceof HTMLTextAreaElement ? nativeValueSetter.textarea : nativeValueSetter.input;
    setter.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    const caret = Math.max(0, text.length - caretFromEnd);
    el.setSelectionRange(caret, caret);
    return matches.map((m) => m.type);
  }

  function maskContentEditable(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const jobs = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      for (const m of findMatches(node.nodeValue)) jobs.push({ node, ...m });
    }
    if (jobs.length === 0) return [];

    const sel = window.getSelection();
    // Edit back-to-front so earlier offsets stay valid. execCommand goes through
    // the editor's own input pipeline, which keeps ProseMirror/Quill state in sync.
    for (let i = jobs.length - 1; i >= 0; i--) {
      const { node, start, end, type } = jobs[i];
      if (!node.isConnected) continue;
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, end);
      sel.removeAllRanges();
      sel.addRange(range);
      if (!document.execCommand("insertText", false, placeholder(type))) {
        node.nodeValue = node.nodeValue.slice(0, start) + placeholder(type) + node.nodeValue.slice(end);
      }
    }

    // Leave the caret at the end of the prompt.
    const endRange = document.createRange();
    endRange.selectNodeContents(root);
    endRange.collapse(false);
    sel.removeAllRanges();
    sel.addRange(endRange);
    return jobs.map((j) => j.type);
  }

  function scan(el) {
    if (!enabled || !el || !el.isConnected) return [];
    masking = true;
    try {
      const types = el.isContentEditable ? maskContentEditable(el) : maskTextControl(el);
      if (types.length) report(types);
      return types;
    } catch (err) {
      console.warn("[Shadow AI Shield] masking failed:", err);
      return [];
    } finally {
      masking = false;
    }
  }

  function scheduleScan(el, delay) {
    clearTimeout(timers.get(el));
    timers.set(el, setTimeout(() => scan(el), delay));
  }

  // ---------------------------------------------------------------------------
  // Reporting & feedback

  function report(types) {
    showToast(types);
    try {
      chrome.runtime.sendMessage({ type: "PII_MASKED", findings: types, site: location.hostname }).catch(() => {});
    } catch {
      // Extension was reloaded; this content script is orphaned. Ignore.
    }
  }

  let toastHost = null;
  let toastTimer = null;

  function showToast(types) {
    if (!toastHost) {
      toastHost = document.createElement("div");
      toastHost.style.cssText = "position:fixed;z-index:2147483647;bottom:20px;right:20px;pointer-events:none;";
      const shadow = toastHost.attachShadow({ mode: "open" });
      shadow.innerHTML = `
        <style>
          .t { font: 500 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; color: #fff;
               background: #1f2937; border-left: 4px solid #22c55e; border-radius: 8px;
               padding: 10px 14px; box-shadow: 0 6px 20px rgba(0,0,0,.25); max-width: 320px;
               opacity: 0; transform: translateY(8px); transition: opacity .2s, transform .2s; }
          .t.show { opacity: 1; transform: none; }
        </style>
        <div class="t" role="status"></div>`;
      document.documentElement.appendChild(toastHost);
    }
    const box = toastHost.shadowRoot.querySelector(".t");
    const unique = [...new Set(types)];
    box.textContent = `🛡️ Shadow AI Shield masked ${types.length} item${types.length > 1 ? "s" : ""}: ${unique.join(", ")}`;
    box.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.remove("show"), 3500);
  }

  // ---------------------------------------------------------------------------
  // Listeners (capture phase, so we run before the page's own handlers)

  document.addEventListener(
    "input",
    (e) => {
      if (masking || !enabled) return;
      const el = editableFrom(e);
      if (el) scheduleScan(el, DEBOUNCE_MS);
    },
    true
  );

  document.addEventListener(
    "paste",
    (e) => {
      if (!enabled) return;
      const el = editableFrom(e);
      if (el) scheduleScan(el, 0); // run right after the paste lands
    },
    true
  );

  // Last line of defence: scan synchronously when the user hits Enter to send.
  // If anything was masked, hold the send so the user can review the prompt.
  document.addEventListener(
    "keydown",
    (e) => {
      if (!enabled || e.key !== "Enter" || e.shiftKey || e.isComposing) return;
      const el = editableFrom(e);
      if (!el) return;
      clearTimeout(timers.get(el));
      if (scan(el).length) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    },
    true
  );
})();
