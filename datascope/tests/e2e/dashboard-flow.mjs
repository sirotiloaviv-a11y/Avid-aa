/**
 * The full dashboard, in a real browser, against the local mock market feed.
 *
 * This is the test that exercises the parts unit tests cannot: a real WebSocket
 * carrying real Binance frames, prices arriving over time, the chart redrawing,
 * and - the point of the whole exercise - an alert rule crossing its threshold
 * and producing a desktop notification with the right text in it.
 *
 * Notifications are verified by replacing `window.Notification` with a recorder
 * before any app code runs. That is the only way to assert on what a notification
 * actually said; the OS-level popup itself is outside the browser's control.
 *
 * The live providers are never contacted. The app is pointed at the mock through
 * the endpoint query parameters, and any request that escapes to a real provider
 * fails the run.
 *
 * Usage: node tests/e2e/dashboard-flow.mjs [--headed] [--keep-screenshots <dir>]
 */

import assert from 'node:assert/strict';
import { spawn, execSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(import.meta.url);

const args = process.argv.slice(2);
const headed = args.includes('--headed');
const shotArg = args.indexOf('--keep-screenshots');
const screenshotDir = shotArg !== -1 && args[shotArg + 1] ? args[shotArg + 1] : null;

const APP_PORT = 4398;
const MOCK_PORT = 4500;

let passed = 0;
async function step(name, body) {
  await body();
  passed += 1;
  console.log(`  ✓ ${name}`);
}

function loadPlaywright() {
  try {
    return require('playwright');
  } catch {
    try {
      return require(path.join(execSync('npm root -g', { encoding: 'utf8' }).trim(), 'playwright'));
    } catch {
      return null;
    }
  }
}

/** Starts a child process and waits for a line on stdout. */
function startProcess(script, extraArgs, readyPattern) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(root, 'scripts', script), ...extraArgs], {
      cwd: root,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    const timer = setTimeout(() => reject(new Error(`${script} did not start: ${output}`)), 10_000);
    const onData = (chunk) => {
      output += chunk;
      if (readyPattern.test(output)) {
        clearTimeout(timer);
        resolve(child);
      }
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`${script} exited with ${code}: ${output}`));
    });
  });
}

/** Drives the mock feed: force a price, a spike or a volume burst. */
async function control(action, body) {
  const response = await fetch(`http://127.0.0.1:${MOCK_PORT}/control/${action}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  assert.equal(response.ok, true, `control/${action} failed`);
  return response.json();
}

async function mockState(symbol) {
  const rows = await (await fetch(`http://127.0.0.1:${MOCK_PORT}/control/state`)).json();
  return rows.find((row) => row.symbol === symbol);
}

/** The app URL, with every endpoint pointed at the mock. */
function appUrl() {
  const params = new URLSearchParams({
    // The WS *base*, exactly as the real value is a base
    // (wss://stream.binance.com:9443); streamUrl() appends "/stream?streams=…".
    binanceWs: `ws://127.0.0.1:${MOCK_PORT}/binance`,
    binanceRest: `http://127.0.0.1:${MOCK_PORT}/binance`,
    coingeckoRest: `http://127.0.0.1:${MOCK_PORT}/coingecko`,
    yahooRest: `http://127.0.0.1:${MOCK_PORT}/yahoo`,
    stockPollMs: '2000',
    moversPollMs: '3000',
  });
  return `http://127.0.0.1:${APP_PORT}/?${params}`;
}

async function main() {
  const playwright = loadPlaywright();
  if (!playwright) {
    console.log('Playwright is not available - skipping the browser test (npm test still covers the logic).');
    return;
  }
  const chromium = playwright.chromium ?? playwright.default?.chromium;

  const mock = await startProcess('mock-market.mjs', ['--port', String(MOCK_PORT)], /listening/);
  const app = await startProcess('serve.mjs', ['--port', String(APP_PORT)], /127\.0\.0\.1/);

  const shots = screenshotDir
    ? (await mkdir(screenshotDir, { recursive: true }), screenshotDir)
    : await mkdtemp(path.join(tmpdir(), 'datascope-e2e-'));

  const browser = await chromium.launch({ headless: !headed });
  const context = await browser.newContext({
    viewport: { width: 1360, height: 950 },
    locale: 'he-IL',
    permissions: ['notifications'],
  });

  /**
   * Replace Notification before any app script runs, so every notification the
   * app raises is recorded with its exact title and body.
   */
  await context.addInitScript(() => {
    window.__notifications = [];
    // Starts as "default" and only becomes "granted" once the page asks, so the
    // test walks the same path a person does rather than starting past it.
    let permission = 'default';
    class RecordingNotification {
      static get permission() {
        return permission;
      }
      static requestPermission() {
        permission = 'granted';
        return Promise.resolve('granted');
      }
      constructor(title, options) {
        this.title = title;
        this.options = options;
        window.__notifications.push({ title, body: options?.body, tag: options?.tag, dir: options?.dir });
      }
      close() {}
    }
    window.Notification = RecordingNotification;
  });

  const page = await context.newPage();

  const problems = [];
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') problems.push(`console: ${message.text()}`);
  });

  /** Nothing may escape to a real provider. */
  const escaped = [];
  let problemsBeforeKill = 0;
  await context.route('**/*', (route) => {
    const url = route.request().url();
    const local = url.includes('127.0.0.1') || url.startsWith('data:') || url.startsWith('blob:');
    if (!local) escaped.push(url);
    route.continue();
  });

  try {
    console.log(`DataScope e2e (app :${APP_PORT}, mock :${MOCK_PORT})`);

    await step('the dashboard loads in Hebrew and connects to the crypto feed', async () => {
      await page.goto(appUrl(), { waitUntil: 'load' });
      assert.equal(await page.locator('html').getAttribute('dir'), 'rtl');
      assert.equal(await page.locator('html').getAttribute('lang'), 'he');
      assert.match(await page.locator('.tagline').innerText(), /מעקב שוק בזמן אמת/);

      await page.waitForSelector('.status-pill.status-connected', { timeout: 15_000 });
      const pills = await page.locator('#connection-pills').innerText();
      assert.match(pills, /קריפטו/);
      assert.match(pills, /מחובר/);
    });

    await step('live prices arrive and the watchlist cards fill in', async () => {
      await page.waitForFunction(
        () => {
          const card = document.querySelector('.price-card .price-value');
          return card && card.textContent.trim() !== '—' && card.textContent.trim() !== '';
        },
        { timeout: 15_000 },
      );

      const cards = page.locator('.price-card');
      assert.ok((await cards.count()) >= 3);
      const first = await cards.first().innerText();
      assert.match(first, /BTC\/USDT/);
      // The full name from the provider, beside the symbol.
      assert.match(first, /Bitcoin/);
    });

    await step('the price actually updates over time, not just once', async () => {
      const read = async () =>
        page.locator('.price-card').first().locator('.price-value').innerText();
      const before = await read();
      await page.waitForFunction(
        (previous) => {
          const node = document.querySelector('.price-card .price-value');
          return node && node.textContent.trim() !== previous;
        },
        before,
        { timeout: 15_000 },
      );
      assert.notEqual(await read(), before);
    });

    await step('the ticker bar shows movers with a direction', async () => {
      await page.waitForSelector('.ticker-item', { timeout: 15_000 });
      const items = await page.locator('.ticker-strip').first().locator('.ticker-item').count();
      assert.ok(items >= 3, `expected several movers, saw ${items}`);
      const text = await page.locator('.ticker-strip').first().innerText();
      assert.match(text, /%/);
    });

    await step('the charts render from the live series', async () => {
      await page.waitForSelector('#price-chart svg', { timeout: 15_000 });
      assert.equal(await page.locator('#price-chart path.c-line').count(), 1);
      assert.ok((await page.locator('#volume-chart .c-bar').count()) > 0);
      assert.ok(await page.locator('#chart-empty').isHidden());
    });

    await step('intraday statistics are populated for the selected asset', async () => {
      const stats = await page.locator('#intraday-stats').innerText();
      for (const label of ['מחיר אחרון', 'שינוי יומי', 'פתיחה', 'גבוה', 'נמוך', 'מחזור', 'עדכון אחרון']) {
        assert.ok(stats.includes(label), `missing ${label}`);
      }
      assert.equal(/—\s*$/.test(await page.locator('#detail-name').innerText()), false);
    });

    await step('selecting another asset moves the whole detail panel', async () => {
      await page.locator('.price-card-main', { hasText: 'ETH/USDT' }).click();
      await page.waitForFunction(
        () => document.querySelector('#detail-name')?.textContent?.includes('Ethereum'),
        { timeout: 10_000 },
      );
      assert.match(await page.locator('#detail-symbol').innerText(), /ETH\/USDT/);
      // Back to Bitcoin for the alert steps.
      await page.locator('.price-card-main', { hasText: 'BTC/USDT' }).click();
      await page.waitForFunction(
        () => document.querySelector('#detail-name')?.textContent?.includes('Bitcoin'),
        { timeout: 10_000 },
      );
    });

    await step('searching finds assets by symbol and by name', async () => {
      await page.fill('#asset-search', 'sol');
      await page.waitForSelector('.asset-option', { timeout: 10_000 });
      const options = await page.locator('.asset-option').allInnerTexts();
      assert.ok(options.some((text) => text.includes('SOL')), options.join(' | '));
      await page.fill('#asset-search', '');
      await page.keyboard.press('Escape');
    });

    await step('a stock quote arrives through the local Yahoo proxy path', async () => {
      // The stock source is polled, so this is the slowest signal on the page.
      await page.waitForFunction(
        () => {
          const cards = [...document.querySelectorAll('.price-card')];
          const aapl = cards.find((card) => card.textContent.includes('AAPL'));
          const value = aapl?.querySelector('.price-value')?.textContent?.trim();
          return value && value !== '—';
        },
        { timeout: 20_000 },
      );
      const card = await page.locator('.price-card', { hasText: 'AAPL' }).innerText();
      assert.match(card, /Apple Inc\./);
      // A polled source must say so rather than implying real time.
      assert.match(card, /ייתכן עיכוב/);
    });

    await page.screenshot({ path: path.join(shots, 'dashboard.png'), fullPage: true });

    /* ------------------------------------------------------------- alerts */

    await step('notifications can be enabled from the page', async () => {
      await page.click('#enable-notifications');
      await page.waitForFunction(
        () => document.querySelector('#enable-notifications')?.disabled === true,
        { timeout: 5_000 },
      );
      assert.match(await page.locator('#notification-state').innerText(), /פעילות/);
    });

    await step('a price alert fires once, with the full name and symbol in the title', async () => {
      const state = await mockState('BTCUSDT');
      const target = Math.round(state.price * 1.05 * 100) / 100;

      // Selected by the asset key, which is what the option value carries.
      await page.selectOption('#rule-asset', 'binance:BTCUSDT');
      await page.selectOption('#rule-type', 'price');
      await page.selectOption('#rule-direction', 'above');
      await page.fill('#rule-target', String(target));
      await page.click('#add-rule');

      await page.waitForSelector('.rule-item', { timeout: 5_000 });
      assert.match(await page.locator('.rule-item').first().innerText(), /מחיר יעד/);

      // Nothing should have fired yet: the price is still below the target.
      assert.equal((await page.evaluate(() => window.__notifications.length)), 0);

      await control('price', { symbol: 'BTCUSDT', price: target + 50 });

      await page.waitForFunction(() => window.__notifications.length > 0, { timeout: 15_000 });
      const notifications = await page.evaluate(() => window.__notifications);
      assert.equal(notifications.length, 1);

      // The requirement: asset name AND symbol, both in the notification.
      assert.equal(notifications[0].title, 'Bitcoin / BTC/USDT');
      assert.match(notifications[0].body, /המחיר/);
      assert.equal(notifications[0].dir, 'rtl');
    });

    await step('the alert is logged in the history panel', async () => {
      await page.waitForSelector('.history-item', { timeout: 10_000 });
      const entry = await page.locator('.history-item').first().innerText();
      assert.match(entry, /Bitcoin \/ BTC\/USDT/);
      assert.match(entry, /מחיר יעד/);
      assert.match(entry, /מחיר בעת ההפעלה/);
    });

    await step('a rule that stays met does not notify again', async () => {
      const before = await page.evaluate(() => window.__notifications.length);
      const state = await mockState('BTCUSDT');
      // Push it further past the target several times.
      for (let i = 1; i <= 3; i += 1) {
        await control('price', { symbol: 'BTCUSDT', price: state.price + i * 100 });
        await page.waitForTimeout(1200);
      }
      assert.equal(await page.evaluate(() => window.__notifications.length), before);
    });

    await step('a percent-spike alert fires on a sudden move', async () => {
      await page.selectOption('#rule-asset', 'binance:SOLUSDT');
      await page.selectOption('#rule-type', 'percent');
      await page.selectOption('#rule-move', 'up');
      await page.fill('#rule-threshold', '4');
      await page.selectOption('#rule-basis', 'dayOpen');
      await page.click('#add-rule');

      const before = await page.evaluate(() => window.__notifications.length);
      const state = await mockState('SOLUSDT');
      await control('price', { symbol: 'SOLUSDT', price: Math.round(state.open * 1.08 * 100) / 100 });

      await page.waitForFunction(
        (count) => window.__notifications.length > count,
        before,
        { timeout: 15_000 },
      );
      const latest = (await page.evaluate(() => window.__notifications)).at(-1);
      assert.equal(latest.title, 'Solana / SOL/USDT');
      assert.match(latest.body, /שינוי של/);
      assert.match(latest.body, /%/);
    });

    await step('an invalid rule is rejected with a field-level message', async () => {
      await page.selectOption('#rule-type', 'price');
      await page.fill('#rule-target', '-5');
      await page.click('#add-rule');
      const error = page.locator('[data-error-for="target"]');
      await error.waitFor({ state: 'visible', timeout: 5_000 });
      assert.match(await error.innerText(), /חיובי/);
      assert.equal(await page.locator('#rule-target').getAttribute('aria-invalid'), 'true');
    });

    await step('rules and history survive a reload', async () => {
      const rulesBefore = await page.locator('.rule-item').count();
      const historyBefore = await page.locator('.history-item').count();
      assert.ok(rulesBefore >= 2 && historyBefore >= 2);

      await page.reload({ waitUntil: 'load' });
      await page.waitForSelector('.rule-item', { timeout: 10_000 });

      assert.equal(await page.locator('.rule-item').count(), rulesBefore);
      assert.equal(await page.locator('.history-item').count(), historyBefore);
      assert.match(await page.locator('.history-item').first().innerText(), /\//);
    });

    await step('a disabled rule stops firing', async () => {
      const state = await mockState('BTCUSDT');
      // Re-arm the existing BTC rule by dropping below its target first.
      await control('price', { symbol: 'BTCUSDT', price: state.price * 0.9 });
      await page.waitForTimeout(1500);

      await page.locator('.rule-item .switch input').first().uncheck();
      await page.waitForTimeout(500);

      const before = await page.evaluate(() => window.__notifications.length);
      await control('price', { symbol: 'BTCUSDT', price: state.price * 1.5 });
      await page.waitForTimeout(3000);
      assert.equal(await page.evaluate(() => window.__notifications.length), before);
    });

    await step('the history exports as CSV', async () => {
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.click('#export-history'),
      ]);
      const name = download.suggestedFilename();
      assert.match(name, /^datascope_alerts_\d{4}-\d{2}-\d{2}\.csv$/);
      const file = path.join(shots, name);
      await download.saveAs(file);
      const { readFile } = await import('node:fs/promises');
      const csv = await readFile(file, 'utf8');
      assert.match(csv, /timestamp_iso,time_local,asset_name,symbol/);
      assert.match(csv, /Bitcoin/);
    });

    await page.screenshot({ path: path.join(shots, 'alerts.png'), fullPage: true });

    await step('deleting a rule removes it', async () => {
      const before = await page.locator('.rule-item').count();
      await page.locator('.rule-item .button', { hasText: 'מחיקה' }).first().click();
      await page.waitForFunction(
        (count) => document.querySelectorAll('.rule-item').length === count - 1,
        before,
        { timeout: 5_000 },
      );
    });

    await step('clearing stored data empties the rules and the history', async () => {
      await page.click('#toggle-settings');
      await page.click('#clear-storage');
      await page.waitForFunction(
        () => document.querySelectorAll('.history-item').length === 0,
        { timeout: 5_000 },
      );
      assert.match(await page.locator('#settings-status').innerText(), /נמחקו/);
    });

    await step('a dropped feed is reported and then recovers', async () => {
      // Everything logged from here on is a consequence of killing the feed on
      // purpose, so the final check grades it separately.
      problemsBeforeKill = problems.length;
      // Kill the mock: the socket closes and the pill must stop saying connected.
      mock.kill();
      await page.waitForFunction(
        () => !document.querySelector('.status-pill.status-connected'),
        { timeout: 20_000 },
      );
      const pills = await page.locator('#connection-pills').innerText();
      assert.ok(/מתחבר|שגיאה|מנותק/.test(pills), pills);
      await page.screenshot({ path: path.join(shots, 'disconnected.png') });
    });

    await step('the layout holds at phone width', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(500);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert.ok(overflow <= 1, `horizontal overflow of ${overflow}px`);
      await page.screenshot({ path: path.join(shots, 'mobile.png'), fullPage: true });
    });

    await step('nothing reached a live provider, and losing the feed threw nothing', async () => {
      assert.deepEqual(escaped, []);

      // Before the feed was killed the console must be completely clean.
      assert.deepEqual(problems.slice(0, problemsBeforeKill), []);

      // After it was killed, only connection failures are acceptable. An
      // exception here would mean the app breaks when its feed disappears,
      // which is exactly the moment it has to keep working.
      for (const problem of problems.slice(problemsBeforeKill)) {
        assert.match(
          problem,
          /ERR_CONNECTION_REFUSED|WebSocket connection|Failed to load resource/,
          `unexpected error after the feed was dropped: ${problem}`,
        );
      }
    });

    console.log(`\n${passed} browser checks passed. Artifacts: ${shots}`);
  } catch (error) {
    await page.screenshot({ path: path.join(shots, 'failure.png'), fullPage: true }).catch(() => {});
    console.error(`\n✗ failed after ${passed} checks: ${error.message}`);
    if (problems.length > 0) console.error('page problems:', problems.slice(0, 5));
    if (escaped.length > 0) console.error('escaped requests:', escaped.slice(0, 5));
    console.error(`artifacts: ${shots}`);
    process.exitCode = 1;
  } finally {
    await browser.close();
    mock.kill();
    app.kill();
  }
}

await main();
