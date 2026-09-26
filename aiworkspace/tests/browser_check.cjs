// Browser check of the main flow in demo mode (no network, no API key).
//
//   NODE_PATH=$(npm root -g) node aiworkspace/tests/browser_check.cjs [screenshot-dir]
//
// Needs the `playwright` package and a Chromium build (set CHROMIUM_PATH to
// use a specific binary). Starts its own server on port 8812 with a throwaway
// database, and writes desktop and mobile screenshots to the given directory.
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const REPO = path.resolve(__dirname, "..", "..");
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "aiws-browser-"));
const SP = path.resolve(process.argv[2] || TMP);
fs.mkdirSync(SP, { recursive: true });
const DB = path.join(TMP, "browser-check.db");
const PORT = 8812;
const URL = `http://127.0.0.1:${PORT}/`;

let server;
function startServer() {
  return new Promise((resolve, reject) => {
    server = spawn("python3", ["-m", "aiworkspace", "--port", String(PORT)], {
      cwd: REPO,
      env: { ...process.env, AIWS_DB_PATH: DB, ANTHROPIC_API_KEY: "", AIWS_PROVIDER: "demo" },
    });
    server.stdout.on("data", (d) => d.toString().includes("running at") && resolve());
    server.on("exit", (c) => reject(new Error("server exited " + c)));
  });
}
function stopServer() {
  return new Promise((r) => {
    server.removeAllListeners("exit");
    server.on("exit", r);
    server.kill("SIGINT");
  });
}

const results = [];
function check(name, ok, detail = "") {
  results.push({ name, ok: !!ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  — " + detail : ""}`);
}

(async () => {
  await startServer();
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 820 } });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(String(e)));
  page.on("dialog", (d) => d.accept());
  let alerted = false;
  await page.exposeFunction("__xss", () => (alerted = true));

  await page.goto(URL);
  await page.waitForSelector(".empty");
  check("empty state shown", await page.isVisible(".empty h2"));
  check("demo banner visible", await page.isVisible("#demo-banner"));
  check("demo badge", (await page.textContent("#mode-badge")).includes("Demo"));
  await page.screenshot({ path: path.join(SP, "desktop-1-empty.png") });

  // Hebrew message
  await page.fill("#input", "שלום! תכתוב לי פונקציה בפייתון");
  await page.keyboard.press("Enter");
  await page.waitForSelector(".typing, .msg-assistant", { timeout: 5000 });
  const sawStreaming = await page.isVisible("#stop");
  check("stop button visible while streaming", sawStreaming);
  await page.waitForSelector("#send:not([hidden])", { timeout: 15000 });
  const reply = await page.textContent(".msg-assistant .msg-body");
  check("hebrew demo reply streamed", reply.includes("מצב הדגמה"));
  check("simulated tag on reply", await page.isVisible(".msg-assistant .tag-demo"));
  check("code block is LTR", (await page.getAttribute(".code-block pre", "dir")) === "ltr");
  const pDir = await page.$eval(".msg-assistant p", (p) => getComputedStyle(p).direction);
  check("hebrew paragraph renders RTL via dir=auto", pDir === "rtl", pDir);
  check("title auto-set from first message", (await page.textContent("#conv-title")).startsWith("שלום"));
  await page.screenshot({ path: path.join(SP, "desktop-2-hebrew-reply.png") });

  // English follow-up + XSS attempt as user text
  await page.fill("#input", '<img src=x onerror="__xss()"> English follow-up **bold**');
  await page.click("#send");
  await page.waitForFunction(() => document.querySelectorAll(".msg-assistant").length === 2 && !document.querySelector(".typing") && !document.querySelector("#send[hidden]"), null, { timeout: 15000 });
  check("user HTML rendered as text, not markup", (await page.$$(".msg-user img")).length === 0 && !alerted);
  const enDir = await page.$eval(".msg-assistant:last-of-type p", (p) => getComputedStyle(p).direction);
  check("english paragraph renders LTR", enDir === "ltr", enDir);

  // Markdown renderer against hostile model output
  const md = await page.evaluate(async () => {
    const { renderMarkdown } = await import("/static/markdown.js");
    const div = document.createElement("div");
    div.append(renderMarkdown('<script>__xss()</script>\n<img src=x onerror=__xss()>\n[click](javascript:__xss())\n[ok](https://example.com)\n```html\n<b>hi</b>\n```', { copy: "c", copied: "d" }));
    document.body.append(div);
    return { scripts: div.querySelectorAll("script,img").length, links: [...div.querySelectorAll("a")].map((a) => a.getAttribute("href")), code: div.querySelector("pre code").textContent };
  });
  check("hostile markdown produces no script/img", md.scripts === 0);
  check("javascript: link not rendered as link", md.links.length === 1 && md.links[0] === "https://example.com", JSON.stringify(md.links));
  check("HTML inside code block shown literally", md.code === "<b>hi</b>");

  // Cancellation
  await page.fill("#input", "please write a long answer");
  await page.click("#send");
  await page.waitForSelector("#stop:not([hidden])");
  await page.waitForTimeout(400);
  await page.click("#stop");
  await page.waitForSelector("#send:not([hidden])", { timeout: 5000 });
  const tags = await page.$$eval(".msg-assistant:last-of-type .tag", (els) => els.map((e) => e.textContent));
  check("cancelled reply marked stopped/incomplete", tags.some((x) => x.startsWith("Stopped")), tags.join(","));

  // Error state
  await page.fill("#input", "/demo-error");
  await page.click("#send");
  await page.waitForSelector(".msg-error", { timeout: 5000 });
  check("provider error shown", (await page.textContent(".msg-error")).includes("Simulated provider error"));
  check("retry offered", await page.isVisible(".msg-error button"));
  await page.screenshot({ path: path.join(SP, "desktop-3-stopped-and-error.png") });

  // Validation: over-limit message
  await page.fill("#input", "x".repeat(16001));
  check("send disabled over length limit", await page.isDisabled("#send"));
  check("counter warns", await page.isVisible("#counter.over"));
  await page.fill("#input", "");

  // Rename
  const cid = (await page.evaluate(() => location.hash)).slice(1);
  await page.hover(".conv-item.active");
  await page.click(".conv-item.active .conv-actions button:first-child");
  await page.fill(".rename-input", "My renamed chat");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector(".conv-item.active .conv-open")?.textContent === "My renamed chat");
  check("rename via UI", (await page.textContent("#conv-title")) === "My renamed chat");

  // Second conversation, then reload and reopen the first
  await page.click("#new-chat");
  await page.fill("#input", "second conversation");
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelectorAll(".conv-item").length === 2 && !document.querySelector("#send[hidden]"), null, { timeout: 15000 });
  await page.reload();
  await page.waitForSelector(".conv-item");
  check("two conversations after reload", (await page.$$(".conv-item")).length === 2);
  await page.click(`.conv-open:text("My renamed chat")`);
  await page.waitForSelector(".msg-assistant");
  const count = await page.$$eval(".msg", (e) => e.length);
  check("reopened history has all messages", count === 8, `messages=${count}`);

  // Restart server, history must survive
  await stopServer();
  await startServer();
  await page.goto(URL + "#" + cid);
  await page.waitForSelector(".msg-assistant");
  check("history survives server restart", (await page.$$eval(".msg", (e) => e.length)) === 8);
  check("renamed title survives restart", (await page.textContent("#conv-title")) === "My renamed chat");

  // RTL interface + mobile
  await page.click("#lang-toggle");
  check("interface switches to RTL", (await page.getAttribute("html", "dir")) === "rtl");
  await page.screenshot({ path: path.join(SP, "desktop-4-hebrew-interface.png") });
  await page.setViewportSize({ width: 390, height: 800 });
  await page.waitForTimeout(400);
  check("sidebar hidden on mobile", !(await page.$eval("#sidebar", (s) => { const r = s.getBoundingClientRect(); return r.right > 0 && r.left < innerWidth; })));
  const noHScroll = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  check("no horizontal page scroll on mobile", noHScroll);
  await page.screenshot({ path: path.join(SP, "mobile-1-conversation.png") });
  await page.click("#menu-btn");
  await page.waitForTimeout(300);
  check("drawer opens on mobile", await page.$eval("#sidebar", (s) => { const r = s.getBoundingClientRect(); return r.right > 0 && r.left < innerWidth; }));
  await page.screenshot({ path: path.join(SP, "mobile-2-drawer.png") });
  await page.click("#scrim", { position: { x: 20, y: 400 } });
  await page.waitForTimeout(300);
  check("scrim closes drawer", !(await page.$eval("#sidebar", (s) => s.classList.contains("open"))));
  await page.click("#lang-toggle").catch(() => {});
  await page.setViewportSize({ width: 1280, height: 820 });
  await page.evaluate(() => { try { localStorage.setItem("aiws.lang", "en"); } catch {} });
  await page.reload();
  await page.waitForSelector(".conv-item");

  // Delete both
  for (let i = 0; i < 2; i++) {
    await page.hover(".conv-item >> nth=0");
    await page.click(".conv-item >> nth=0 >> .conv-actions button:last-child");
    await page.waitForFunction((n) => document.querySelectorAll(".conv-item").length === n, 1 - i);
  }
  check("delete via UI empties list", (await page.textContent("#conv-state")).includes("No conversations"));

  check("no console/CSP errors", consoleErrors.length === 0, consoleErrors.join(" | "));
  await browser.close();
  await stopServer();
  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} browser checks passed`);
  console.log(`screenshots: ${SP}`);
  process.exit(failed.length ? 1 : 0);
})().catch(async (e) => {
  console.error(e);
  try { await stopServer(); } catch {}
  process.exit(1);
});
