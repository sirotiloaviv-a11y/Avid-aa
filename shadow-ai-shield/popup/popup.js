"use strict";

const LABELS = {
  API_KEY: "API key / secret",
  EMAIL: "Email address",
  CREDIT_CARD: "Credit card",
  IBAN: "IBAN",
  SSN: "US SSN",
  ISRAELI_ID: "Israeli ID",
  PHONE: "Phone number",
  IP_ADDRESS: "IP address",
};
const LOG_SHOWN = 25;

const $ = (id) => document.getElementById(id);

function send(type, extra = {}) {
  return chrome.runtime.sendMessage({ type, ...extra }).then((res) => {
    if (!res || !res.ok) throw new Error(res ? res.error : "No response from background");
    return res.result;
  });
}

function timeAgo(ts) {
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts).toLocaleDateString();
}

function render(state) {
  const { enabled, stats, log } = state;

  $("toggle").checked = enabled;
  document.body.classList.toggle("off", !enabled);
  $("status-text").textContent = enabled ? "Protection active" : "Protection paused";

  $("count").textContent = stats.maskedToday;

  const chips = $("by-type");
  chips.replaceChildren(
    ...Object.entries(stats.byType)
      .sort((a, b) => b[1] - a[1])
      .map(([type, n]) => {
        const el = document.createElement("span");
        el.className = "chip";
        el.textContent = `${LABELS[type] || type} · ${n}`;
        return el;
      })
  );

  const list = $("log-list");
  list.replaceChildren(
    ...log.slice(0, LOG_SHOWN).map((entry) => {
      const li = document.createElement("li");
      const type = document.createElement("span");
      type.className = "type";
      type.textContent = LABELS[entry.type] || entry.type;
      const time = document.createElement("span");
      time.className = "time";
      time.textContent = timeAgo(entry.ts);
      const site = document.createElement("span");
      site.className = "site";
      site.textContent = `Masked on ${entry.site || "unknown site"}`;
      li.append(type, time, site);
      return li;
    })
  );
  $("empty").hidden = log.length > 0;
}

async function refresh() {
  try {
    render(await send("GET_STATE"));
  } catch (err) {
    console.error("[Shadow AI Shield]", err);
  }
}

$("toggle").addEventListener("change", (e) => {
  send("SET_ENABLED", { enabled: e.target.checked }).catch(console.error);
});

$("clear").addEventListener("click", () => {
  send("CLEAR_LOG").catch(console.error);
});

// Live-update while the popup is open.
chrome.storage.onChanged.addListener((_changes, area) => {
  if (area === "local") refresh();
});

refresh();
