"use strict";

// Live dashboard. All data is inserted with textContent (never innerHTML),
// so a symbol or reason string can't inject markup.

const $ = (id) => document.getElementById(id);
const state = { data: null, serverOffsetMs: 0, sort: { key: "time", dir: "desc" }, lastMessage: 0 };

// ---------------------------------------------------------------- format
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
function money(v, signed) {
  if (v === null || v === undefined) return "—";
  const s = usd.format(Math.abs(v));
  if (v < 0) return "-" + s;
  return signed && v > 0 ? "+" + s : s;
}
function pct(v, signed, digits) {
  if (v === null || v === undefined) return "—";
  const d = digits === undefined ? 2 : digits;
  return (signed && v > 0 ? "+" : "") + v.toFixed(d) + "%";
}
function num(v) {
  if (v === null || v === undefined) return "—";
  const abs = Math.abs(v);
  const digits = abs >= 100 ? 2 : abs >= 1 ? 4 : 6;
  return v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}
function utc(iso) {
  if (!iso) return "—";
  return iso.slice(0, 19).replace("T", " ");
}
function signClass(v) { return v > 0 ? "pos" : v < 0 ? "neg" : ""; }
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = text;
  return e;
}

// ------------------------------------------------------------------- api
async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Dashboard-Request": "1" },
    body: JSON.stringify(body || {}),
  });
  let payload = {};
  try { payload = await res.json(); } catch (_) { /* empty body */ }
  if (!res.ok || payload.ok === false) throw new Error(payload.message || payload.error || res.statusText);
  return payload;
}

async function refresh() {
  try {
    const res = await fetch("/api/state", { credentials: "same-origin" });
    if (res.ok) render(await res.json());
  } catch (_) { setConn("down", "offline"); }
}

function toast(message, isError) {
  const t = $("toast");
  t.textContent = message;
  t.classList.toggle("err", !!isError);
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 4000);
}

// ---------------------------------------------------------------- render
function render(data) {
  state.data = data;
  state.serverOffsetMs = new Date(data.server_time).getTime() - Date.now();
  state.lastMessage = Date.now();
  renderHeader(data);
  renderAccounts(data.accounts);
  renderTrades();
  renderActivity(data.activity);
  tickNews();
}

function renderHeader(d) {
  const env = $("env");
  env.textContent = d.environment;
  env.classList.toggle("live", d.environment === "live");

  const o = d.overall;
  const pill = $("overall-status");
  pill.textContent = o.status;
  pill.className = "pill pill-" + o.status;
  $("overall-note").textContent = o.kill_switch
    ? "kill switch set"
    : `${o.accounts - o.accounts_halted}/${o.accounts} accounts trading`;

  $("total-equity").textContent = money(o.total_equity);
  $("total-balance").textContent = "balance " + money(o.total_balance);
  const pnl = $("day-pnl");
  pnl.textContent = money(o.day_pnl, true);
  pnl.className = "value " + signClass(o.day_pnl);
  $("day-pnl-pct").textContent = pct(o.day_pnl_pct, true, 2);
  $("kill-banner").hidden = !o.kill_switch;
}

function meter(label, used, detail) {
  const wrap = el("div");
  const head = el("div", "meter-label");
  head.append(el("span", null, label), el("span", null, used === null ? "—" : pct(used, false, 0) + " · " + detail));
  const bar = el("div", "meter" + (used >= 80 ? " crit" : used >= 50 ? " warn" : ""));
  const fill = el("span");
  fill.style.width = Math.max(0, Math.min(100, used || 0)) + "%";
  bar.append(fill);
  wrap.append(head, bar);
  return wrap;
}

function kv(key, value, cls) {
  const box = el("div");
  box.append(el("div", "k", key), el("div", "v " + (cls || ""), value));
  return box;
}

function renderAccounts(accounts) {
  const root = $("accounts");
  root.replaceChildren();
  // Rebuild the filter only when the account list changes, so an open
  // dropdown isn't reset by every live update.
  const filter = $("f-account");
  const signature = accounts.map((a) => a.id).join("|");
  if (filter.dataset.sig !== signature) {
    const current = filter.value;
    filter.replaceChildren(el("option", null, "All accounts"));
    filter.firstChild.value = "";
    for (const a of accounts) {
      const opt = el("option", null, `${a.name} · ${a.id}`);
      opt.value = a.id;
      filter.append(opt);
    }
    filter.value = accounts.some((a) => a.id === current) ? current : "";
    filter.dataset.sig = signature;
  }

  for (const a of accounts) {
    const card = el("article", "card " + a.badge);
    const head = el("div", "card-head");
    const title = el("div");
    title.append(el("div", "card-title", a.name), el("div", "card-id", a.id));
    head.append(title, el("span", "badge badge-" + a.badge, a.badge.replace("_", " ")));

    const grid = el("div", "kv");
    grid.append(
      kv("Balance", money(a.balance)),
      kv("Equity", money(a.equity)),
      kv("Today", `${money(a.day_pnl, true)} (${pct(a.day_pnl_pct, true)})`, signClass(a.day_pnl)),
    );

    card.append(
      head,
      grid,
      meter("Daily drawdown used", a.daily.used_pct, "room " + money(a.daily.room)),
      meter("Max drawdown used", a.drawdown.used_pct, "floor " + money(a.drawdown.floor)),
    );

    if (a.halt_reasons.length) {
      const ul = el("ul", "reasons");
      for (const r of a.halt_reasons) ul.append(el("li", null, r));
      card.append(ul);
    }

    const foot = el("div", "card-foot");
    const winRate = a.win_rate === null ? "—" : pct(a.win_rate, false, 0);
    const trades = `${a.trades_today} trade${a.trades_today === 1 ? "" : "s"}`;
    foot.append(el("span", null, `${trades} · win ${winRate} · ${a.open_trades} open`));
    foot.append(toggle(a));
    card.append(foot);
    root.append(card);
  }
}

function toggle(a) {
  const label = el("label", "switch");
  const input = el("input");
  input.type = "checkbox";
  input.checked = !a.paused;
  input.setAttribute("aria-label", `Trading enabled on ${a.id}`);
  input.addEventListener("change", async () => {
    input.disabled = true;
    const action = input.checked ? "unpause" : "pause";
    try {
      const res = await post(`/api/accounts/${encodeURIComponent(a.id)}/${action}`, {});
      toast(res.message);
    } catch (err) {
      input.checked = !input.checked;
      toast(`${a.id}: ${err.message}`, true);
    } finally {
      input.disabled = false;
      refresh();
    }
  });
  label.append(input, el("span", "track"), el("span", null, a.paused ? "Paused" : "Trading"));
  return label;
}

function filteredTrades() {
  const trades = (state.data && state.data.trades) || [];
  const account = $("f-account").value;
  const status = $("f-status").value;
  const symbol = $("f-symbol").value.trim().toUpperCase();
  const { key, dir } = state.sort;
  const rows = trades.filter((t) =>
    (!account || t.account === account) &&
    (!status || t.status === status) &&
    (!symbol || (t.symbol || "").toUpperCase().includes(symbol)));
  rows.sort((x, y) => {
    const a = x[key], b = y[key];
    if (a === b) return 0;
    if (a === null || a === undefined) return 1;
    if (b === null || b === undefined) return -1;
    const cmp = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
    return dir === "asc" ? cmp : -cmp;
  });
  return rows;
}

function renderTrades() {
  const body = document.querySelector("#trades tbody");
  const rows = filteredTrades();
  body.replaceChildren();
  for (const t of rows) {
    const tr = el("tr");
    const cells = [
      el("td", "mono", utc(t.time)),
      el("td", null, t.account),
      el("td", null, t.symbol),
      el("td", t.side ? "side-" + t.side : null, t.side || "—"),
      el("td", "num", num(t.entry)),
      el("td", "num", num(t.exit)),
      el("td", "num", num(t.size)),
      el("td", "num " + signClass(t.pnl), t.pnl === null ? "—" : money(t.pnl, true)),
    ];
    const st = el("td");
    st.append(el("span", "st st-" + t.status.replace(/\s+/g, "-"), t.status));
    cells.push(st);
    tr.append(...cells);
    body.append(tr);
  }
  $("trades-empty").hidden = rows.length > 0;
  for (const th of document.querySelectorAll("#trades th.sortable")) {
    th.classList.toggle("asc", th.dataset.key === state.sort.key && state.sort.dir === "asc");
    th.classList.toggle("desc", th.dataset.key === state.sort.key && state.sort.dir === "desc");
  }
}

function renderActivity(events) {
  const ul = $("activity");
  ul.replaceChildren();
  if (!events.length) ul.append(el("li", "empty", "No activity recorded."));
  for (const e of events) {
    const li = el("li");
    const kind = e.kind.split(":")[0];
    li.append(el("span", "t", utc(e.time)), el("span", null, e.account), el("span", "k-" + kind, `${e.kind}: ${e.message}`));
    ul.append(li);
  }
}

function tickNews() {
  const d = state.data;
  if (!d) return;
  const news = d.news;
  const timer = $("news-timer");
  const title = $("news-title");
  timer.classList.remove("neg");
  if (!news.enabled) { timer.textContent = "off"; title.textContent = "news safeguard disabled"; return; }
  if (news.blocked) {
    timer.textContent = "BLOCKED";
    timer.classList.add("neg");
    title.textContent = news.reason || "";
    return;
  }
  if (!news.next) { timer.textContent = "—"; title.textContent = "none scheduled this week"; return; }
  const ms = new Date(news.next.time).getTime() - (Date.now() + state.serverOffsetMs);
  const s = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(s / 86400);
  const hms = [Math.floor((s % 86400) / 3600), Math.floor((s % 3600) / 60), s % 60]
    .map((n) => String(n).padStart(2, "0")).join(":");
  timer.textContent = (days ? days + "d " : "") + hms;
  title.textContent = `${news.next.currency} · ${news.next.title}`;
}

// ------------------------------------------------------------- controls
function confirmModal({ title, text, confirmLabel, danger, withReason }) {
  return new Promise((resolve) => {
    $("modal-title").textContent = title;
    $("modal-text").textContent = text;
    const confirm = $("modal-confirm");
    confirm.textContent = confirmLabel;
    confirm.className = "btn " + (danger ? "btn-danger" : "btn-ok");
    $("modal-reason-wrap").hidden = !withReason;
    $("modal-reason").value = "";
    $("modal").hidden = false;
    confirm.focus();
    const close = (value) => {
      $("modal").hidden = true;
      confirm.onclick = null;
      $("modal-cancel").onclick = null;
      document.onkeydown = null;
      resolve(value);
    };
    confirm.onclick = () => close({ reason: $("modal-reason").value.trim() });
    $("modal-cancel").onclick = () => close(null);
    document.onkeydown = (ev) => { if (ev.key === "Escape") close(null); };
  });
}

async function onKill() {
  const answer = await confirmModal({
    title: "Activate KILL SWITCH?",
    text: "Halts ALL accounts now: no new entries, and open positions are flattened. Stays on until you press RESUME.",
    confirmLabel: "HALT EVERYTHING",
    danger: true,
    withReason: true,
  });
  if (!answer) return;
  try {
    const res = await post("/api/kill", { reason: answer.reason });
    toast(res.message);
  } catch (err) { toast("Kill switch failed: " + err.message, true); }
  refresh();
}

async function onResume() {
  const answer = await confirmModal({
    title: "Resume trading?",
    text: "Clears the kill switch and manual halts. Daily-loss and max-drawdown halts, and paused accounts, stay as they are.",
    confirmLabel: "Resume",
    danger: false,
    withReason: false,
  });
  if (!answer) return;
  try {
    const res = await post("/api/resume", {});
    toast(res.message);
  } catch (err) { toast("Resume failed: " + err.message, true); }
  refresh();
}

// ----------------------------------------------------------------- live
function setConn(cls, text) {
  const c = $("conn");
  c.className = "conn " + cls;
  $("conn-text").textContent = text;
}

function connect() {
  if (!window.EventSource) { setInterval(refresh, 5000); return; }
  const es = new EventSource("/api/stream");
  es.addEventListener("state", (ev) => {
    setConn("ok", "live");
    render(JSON.parse(ev.data));
  });
  es.onerror = () => setConn("down", "reconnecting");
}

document.addEventListener("DOMContentLoaded", () => {
  $("btn-kill").addEventListener("click", onKill);
  $("btn-resume").addEventListener("click", onResume);
  for (const id of ["f-account", "f-status", "f-symbol"]) $(id).addEventListener("input", renderTrades);
  for (const th of document.querySelectorAll("#trades th.sortable")) {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      state.sort = { key, dir: state.sort.key === key && state.sort.dir === "desc" ? "asc" : "desc" };
      renderTrades();
    });
  }
  refresh();
  connect();
  setInterval(tickNews, 1000);
  // Fallback: if the stream goes quiet (proxy buffering, sleep), poll.
  setInterval(() => { if (Date.now() - state.lastMessage > 20000) refresh(); }, 10000);
});
