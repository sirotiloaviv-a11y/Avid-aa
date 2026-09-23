// End-to-end check in a real browser. It needs Playwright, which is NOT a
// project dependency: install it separately (npm i -g playwright) or skip this
// step. It starts its own server on a free port and closes it afterwards.
//
//   npm run e2e                 run the checks
//   SCREENSHOTS=dir npm run e2e also save screenshots to dir
import { createRequire } from 'node:module';
import { execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createAppServer } from '../server.mjs';
import { loadConfig } from '../server/config.mjs';
import { createMarketService } from '../server/marketService.mjs';
import { lastCompletedSessionDate } from '../server/time.mjs';
import { avDaily, cgMarkets, cgChart, fakeFetch } from '../tests/fixtures/make.mjs';

async function loadPlaywright() {
  try { return await import('playwright'); } catch { /* fall through to global install */ }
  try {
    const globalRoot = execSync('npm root -g', { encoding: 'utf8' }).trim();
    return createRequire(join(globalRoot, 'noop.js'))('playwright');
  } catch {
    return null;
  }
}

const pw = await loadPlaywright();
if (!pw) {
  console.log('Playwright is not installed; skipping browser checks.');
  process.exit(0);
}

const dir = resolve(fileURLToPath(new URL('..', import.meta.url)), process.argv[2] ?? 'src');
// Market mode runs against a simulated provider (synthetic payloads in the
// documented formats). No real provider is contacted by this script.
const lastSession = lastCompletedSessionDate(Date.now());
const upstream = fakeFetch([
  [(u) => u.hostname === 'av.test' && u.searchParams.get('symbol') === 'FAIL', () => new Error('simulated disconnect')],
  [(u) => u.hostname === 'av.test' && u.searchParams.get('symbol') === 'ZZZZ', () => ({ body: { 'Error Message': 'Invalid API call.' } })],
  [(u) => u.hostname === 'av.test', (u) => ({ body: avDaily(u.searchParams.get('symbol'), lastSession, 100) })],
  [(u) => u.pathname.endsWith('/coins/markets'), () => ({ body: cgMarkets([['bitcoin', 'btc', 'Bitcoin', 61000, 500]], new Date(Date.now() - 120000).toISOString()) })],
  [(u) => u.pathname.includes('/market_chart'), () => ({ body: cgChart(Date.now(), 90) })],
]);
const marketEnv = {
  ALPHA_VANTAGE_BASE_URL: 'https://av.test/query', COINGECKO_BASE_URL: 'https://cg.test/api/v3',
  MARKET_STOCK_SYMBOLS: 'AAPL=Apple,MSFT=Microsoft,FAIL=Failing Example', MARKET_CRYPTO_ASSETS: 'BTC=bitcoin',
  ALPHA_VANTAGE_PER_MINUTE: '100', ALPHA_VANTAGE_DAILY_LIMIT: '1000',
};
const configured = createMarketService({
  config: loadConfig({ env: { ...marketEnv, ALPHA_VANTAGE_API_KEY: 'e2e-fake', COINGECKO_DEMO_API_KEY: 'e2e-fake' } }),
  fetchImpl: upstream.impl,
});
const unconfigured = createMarketService({ config: loadConfig({ env: marketEnv }), fetchImpl: upstream.impl });

const server = createAppServer(dir, { market: configured });
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}/`;
const server2 = createAppServer(dir, { market: unconfigured });
await new Promise((r) => server2.listen(0, '127.0.0.1', r));
const base2 = `http://127.0.0.1:${server2.address().port}/`;
const shots = process.env.SCREENSHOTS;
if (shots) mkdirSync(shots, { recursive: true });

const launchOptions = process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {};
const browser = await pw.chromium.launch(launchOptions);
const results = [];
const consoleErrors = [];

async function check(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
    console.log(`ok   ${name}`);
  } catch (err) {
    results.push({ name, ok: false });
    console.log(`FAIL ${name}\n     ${String(err.message).split('\n')[0]}`);
  }
}
function expect(cond, msg) { if (!cond) throw new Error(msg); }

async function newPage(viewport = { width: 1366, height: 900 }) {
  const context = await browser.newContext({ viewport, locale: 'he-IL', timezoneId: 'Asia/Jerusalem' });
  const page = await context.newPage();
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(e.message));
  return page;
}
const settle = (page) => page.waitForFunction(() => !document.querySelector('.state-loading'), null, { timeout: 5000 });
const snap = async (page, name) => { if (shots) await page.screenshot({ path: join(shots, `${name}.png`), fullPage: true }); };

try {
  const page = await newPage();

  await check('home loads with banner, cards, watchlist, chart, news, events, alerts', async () => {
    await page.goto(base);
    await settle(page);
    expect(await page.isVisible('.demo-banner:has-text("נתוני הדגמה — לא מידע בזמן אמת")'), 'banner missing');
    expect(await page.locator('.stat-card').count() === 4, 'expected 4 market cards');
    expect(await page.locator('#watchlist .asset-row').count() === 4, 'expected 4 watchlist rows');
    expect(await page.locator('#chart-box svg .line').count() === 1, 'chart missing');
    expect(await page.locator('#home-news .news-card:has-text("ידיעת הדגמה")').count() > 0, 'news missing');
    expect(await page.locator('#home-events .mini-event').count() > 0, 'events missing');
    expect(await page.locator('#home-alerts .alert-card').count() > 0, 'alerts missing');
    expect(await page.evaluate(() => document.documentElement.dir) === 'rtl', 'page is not RTL');
    await snap(page, '01-home-desktop');
  });

  await check('home: selecting a watchlist asset and a range redraws the chart', async () => {
    await page.click('#watchlist [data-select="NOVX"]');
    await settle(page);
    expect(await page.textContent('#chart-area .chart-title').then((t) => t.includes('NOVX')), 'chart did not switch');
    await page.click('#chart-ranges [data-range="7"]');
    await settle(page);
    expect(await page.locator('#chart-box svg .vol').count() === 7, 'expected 7 volume bars');
  });

  await check('navigation reaches every screen', async () => {
    const expected = { assets: 'רשימת נכסים', news: 'חדשות', events: 'לוח אירועים', alerts: 'מרכז התראות מידע', settings: 'הגדרות', '': 'דף הבית' };
    for (const [path, title] of Object.entries(expected)) {
      await page.click(`.sidebar [data-nav="${path}"]`);
      await page.waitForFunction((t) => document.querySelector('main h1')?.textContent.includes(t), title, { timeout: 3000 })
        .catch(() => { throw new Error(`bad title for #/${path}`); });
      expect((await page.getAttribute(`.sidebar [data-nav="${path}"]`, 'aria-current')) === 'page', `nav not highlighted for #/${path}`);
      expect(await page.isVisible('.demo-banner'), `banner missing on #/${path}`);
    }
    await page.goto(`${base}#/does-not-exist`);
    expect((await page.textContent('main h1')).includes('העמוד לא נמצא'), 'no 404 view');
  });

  await check('assets: tabs, search and watchlist add/remove', async () => {
    await page.goto(`${base}#/assets`);
    await settle(page);
    expect(await page.locator('.asset-row').count() === 10, 'expected 10 assets');
    await page.click('[data-tab="crypto"]');
    expect(await page.locator('.asset-row').count() === 4, 'expected 4 crypto');
    await page.click('[data-tab="all"]');
    await page.fill('#asset-search', 'נובה');
    expect(await page.locator('.asset-row').count() === 1, 'hebrew search failed');
    await page.fill('#asset-search', 'tvl');
    expect(await page.locator('.asset-row').count() === 1, 'symbol search failed');
    await page.click('[data-watch="TVLA"]');
    expect((await page.getAttribute('[data-watch="TVLA"]', 'aria-pressed')) === 'true', 'TVLA not watched');
    await page.fill('#asset-search', 'zzz');
    expect(await page.isVisible('.state-empty:has-text("לא נמצאו נכסים")'), 'empty search state missing');
    await page.goto(base);
    await settle(page);
    expect(await page.locator('#watchlist [data-select="TVLA"]').count() === 1, 'TVLA not on home watchlist');
    await page.click('#watchlist [data-watch="TVLA"]');
    expect(await page.locator('#watchlist [data-select="TVLA"]').count() === 0, 'TVLA not removed');
  });

  await check('asset page: price, volume, chart, news; unknown symbol handled', async () => {
    await page.goto(`${base}#/asset/ORLN`);
    await settle(page);
    expect(await page.locator('.stat-card').count() === 4, 'stats missing');
    expect(await page.locator('#asset-chart svg').count() === 1, 'chart missing');
    const news = page.locator('#asset-news .news-card');
    expect(await news.count() > 0, 'asset news missing');
    await snap(page, '02-asset');
    await page.goto(`${base}#/asset/NOPE`);
    await settle(page);
    expect((await page.textContent('main h1')).includes('נכס לא נמצא'), 'unknown asset not handled');
  });

  await check('news: filter by asset and category, empty result state', async () => {
    await page.goto(`${base}#/news`);
    await settle(page);
    const total = await page.locator('.news-card').count();
    expect(total >= 15, 'expected all demo news');
    expect(await page.locator('.news-card a[href^="http"]').count() === 0, 'news must not contain external links');
    await page.selectOption('#f-symbol', 'ORLN');
    const orln = await page.locator('.news-card').count();
    expect(orln > 0 && orln < total, 'asset filter did not narrow');
    await page.selectOption('#f-category', 'רגולציה');
    expect(await page.isVisible('.state-empty'), 'empty filter state missing');
    await page.click('#f-clear');
    expect(await page.locator('.news-card').count() === total, 'clear did not reset');
    await page.goto(`${base}#/news?symbol=ZFRT`);
    await settle(page);
    expect((await page.inputValue('#f-symbol')) === 'ZFRT', 'query param not applied');
    await snap(page, '03-news');
  });

  await check('events: day/week views, time zone label, reminder persists', async () => {
    await page.goto(`${base}#/events`);
    await settle(page);
    expect((await page.textContent('.tz-box')).includes('UTC+'), 'time zone label missing');
    await page.click('[data-view="week"]');
    expect(await page.locator('.week-day').count() === 7, 'week view should have 7 days');
    await snap(page, '04-events-week');
    const btn = page.locator('#calendar [data-reminder]:not([disabled])').first();
    const id = await btn.getAttribute('data-reminder');
    await btn.click();
    expect(await page.locator(`#my-reminders [data-event-id="${id}"]`).count() === 1, 'reminder not listed');
    await page.reload();
    await settle(page);
    expect(await page.locator(`#my-reminders [data-event-id="${id}"]`).count() === 1, 'reminder not persisted');
    await page.click('[data-view="day"]');
    await page.click('[data-step="1"]');
    await page.click('[data-today]');
  });

  await check('alerts: filter, mark read, badge, trigger demo event, volume disclaimer', async () => {
    await page.goto(`${base}#/alerts`);
    await settle(page);
    const all = await page.locator('.alert-card').count();
    expect(all > 0, 'no alerts');
    const badgeBefore = Number(await page.textContent('[data-unread]'));
    await page.selectOption('#a-type', 'volume');
    const vol = page.locator('.alert-card');
    expect(await vol.count() > 0 && await page.locator('.alert-card:not(.type-volume)').count() === 0, 'type filter failed');
    expect(await page.locator('.alert-card .note:has-text("אין בו מידע על זהות הקונים")').count() > 0, 'volume disclaimer missing');
    expect(await page.locator('.alert-card dl').first().textContent().then((t) => t.includes('ממוצע')), 'trigger data missing');
    await page.locator('[data-toggle-read]').first().click();
    const badgeAfter = Number(await page.textContent('[data-unread]'));
    expect(badgeAfter === badgeBefore - 1, `badge ${badgeBefore} -> ${badgeAfter}`);
    await page.selectOption('#a-status', 'read');
    expect(await page.locator('.alert-card').count() === 1, 'read filter failed');
    await page.selectOption('#a-type', '');
    await page.selectOption('#a-status', 'all');
    await page.click('#demo-trigger');
    await page.waitForFunction((n) => document.querySelectorAll('.alert-card').length === n + 1, all, { timeout: 3000 });
    expect(await page.locator('.alert-card').first().textContent().then((t) => t.includes('הופעל ידנית')), 'manual alert not first');
    await page.click('#mark-all');
    expect(await page.isHidden('[data-unread]'), 'badge should hide when all read');
    await snap(page, '05-alerts');
  });

  await check('settings: preferred types and time zone are saved and applied', async () => {
    await page.goto(`${base}#/settings`);
    await page.uncheck('input[name="type"][value="volume"]');
    await page.selectOption('select[name="timeZone"]', 'UTC');
    await page.click('#prefs button[type="submit"]');
    expect((await page.textContent('#saved')).includes('נשמרו'), 'no save confirmation');
    await page.reload();
    expect(!(await page.isChecked('input[name="type"][value="volume"]')), 'pref not persisted');
    await page.goto(`${base}#/alerts`);
    await settle(page);
    expect(await page.locator('.alert-card.type-volume').count() === 0, 'volume alerts still shown');
    expect((await page.textContent('#hidden-note')).includes('כובו'), 'hidden note missing');
    await page.goto(`${base}#/events`);
    await settle(page);
    expect((await page.textContent('.tz-box')).includes('UTC+00:00'), 'time zone not applied');
    await snap(page, '06-settings-applied');
  });

  await check('simulated load error shows an error state with retry', async () => {
    await page.goto(`${base}#/settings`);
    await page.check('input[name="simulateError"]');
    await page.click('#prefs button[type="submit"]');
    await page.goto(`${base}#/news`);
    await page.waitForSelector('.state-error [data-retry]');
    await snap(page, '07-error-state');
    await page.goto(`${base}#/settings`);
    await page.uncheck('input[name="simulateError"]');
    await page.click('#prefs button[type="submit"]');
    await page.goto(`${base}#/news`);
    await settle(page);
    expect(await page.locator('.news-card').count() > 0, 'did not recover');
  });

  await check('reset clears local data', async () => {
    await page.goto(`${base}#/settings`);
    page.once('dialog', (d) => d.accept());
    await page.click('#reset');
    expect(await page.isChecked('input[name="type"][value="volume"]'), 'reset did not restore defaults');
  });

  await check('phone layout: bottom nav, banner, no horizontal scroll', async () => {
    const phone = await newPage({ width: 390, height: 844 });
    for (const path of ['', 'assets', 'news', 'events?view=week', 'alerts', 'settings', 'asset/NOVX']) {
      await phone.goto(`${base}#/${path}`);
      await settle(phone);
      const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow <= 1, `horizontal overflow ${overflow}px on #/${path}`);
      expect(await phone.isVisible('.demo-banner strong'), `banner hidden on #/${path}`);
    }
    const nav = await phone.locator('.sidebar').boundingBox();
    expect(nav.y + nav.height >= 840, 'nav is not at the bottom');
    await phone.goto(base);
    await settle(phone);
    await snap(phone, '08-home-phone');
    await phone.goto(`${base}#/alerts`);
    await settle(phone);
    await snap(phone, '09-alerts-phone');
  });

  const setMode = async (p, url, mode) => {
    await p.goto(`${url}#/settings`);
    await p.check(`input[name="dataMode"][value="${mode}"]`);
    await p.click('#prefs button[type="submit"]');
    await p.waitForFunction((m) => document.querySelector('[data-mode-banner]')?.dataset.mode === m, mode);
  };

  await check('market mode: switching changes the banner and keeps demo data out', async () => {
    await setMode(page, base, 'market');
    expect((await page.textContent('[data-mode-banner]')).includes('לא בזמן אמת'), 'market banner missing');
    await page.waitForSelector('#sources [data-provider="alpha_vantage"]');
    expect((await page.textContent('#sources')).includes('מפתח הוגדר'), 'provider status missing');
    expect(!(await page.textContent('#sources')).includes('e2e-fake'), 'key leaked to the page');
    await page.goto(base);
    await settle(page);
    expect((await page.textContent('#overview')).includes('מסחר במניות בארה״ב'), 'session card missing');
    expect(await page.isVisible('#watchlist .state-empty'), 'market watchlist should start empty');
    expect(await page.locator('#home-news [data-not-connected]').count() === 1, 'news not marked not-connected');
    expect(await page.locator('.tag-demo:has-text("ידיעת הדגמה")').count() === 0, 'demo news leaked into market mode');
    expect(await page.isHidden('[data-unread]'), 'demo alert badge shown in market mode');
  });

  await check('market mode: asset list shows source, delay, time and per-row failures', async () => {
    await page.goto(`${base}#/assets`);
    await settle(page);
    expect(await page.locator('.asset-row').count() === 4, 'expected 4 configured assets');
    const aapl = await page.textContent('.asset-row:has([data-watch="AAPL"])');
    expect(aapl.includes('Alpha Vantage') && aapl.includes('סוף יום'), 'stock row meta missing');
    const btc = await page.textContent('.asset-row:has([data-watch="BTC"])');
    expect(btc.includes('CoinGecko') && btc.includes('מושהה'), 'crypto row meta missing');
    const fail = await page.textContent('.asset-row:has([data-watch="FAIL"])');
    expect(fail.includes('תקלה בקבלת נתונים'), 'failing row not marked as fault');
    await page.click('[data-watch="AAPL"]');
    await page.click('[data-watch="BTC"]');
    await snap(page, '10-market-assets');
  });

  await check('market mode: stock page shows source, data time, delay and market state', async () => {
    await page.goto(`${base}#/asset/AAPL`);
    await settle(page);
    const meta = await page.textContent('.data-meta');
    for (const part of ['מקור', 'Alpha Vantage', 'מועד הנתון', 'השהיה ידועה', 'סוף יום']) expect(meta.includes(part), `missing "${part}"`);
    expect((await page.textContent('main')).includes('מצב המסחר בארה״ב כעת'), 'market state missing');
    expect(await page.locator('#asset-chart svg .line').count() === 1, 'chart missing');
    expect(await page.locator('#asset-news [data-not-connected]').count() === 1, 'asset news not marked not-connected');
    await page.click('[data-range="90"]');
    await settle(page);
    expect(await page.locator('#asset-chart svg .vol').count() === 90, 'expected 90 real volume bars');
    await snap(page, '11-market-stock');
  });

  await check('market mode: crypto page credits CoinGecko and draws no candles', async () => {
    await page.goto(`${base}#/asset/BTC`);
    await settle(page);
    expect((await page.textContent('main')).includes('Powered by CoinGecko'), 'attribution missing');
    expect((await page.textContent('main')).includes('שינוי ב-24 השעות האחרונות'), '24h basis not labeled');
    expect((await page.textContent('main')).includes('ללא נרות'), 'price-only series not explained');
  });

  await check('market mode: unknown symbol and failed fetch are reported, not filled in', async () => {
    await page.goto(`${base}#/assets?q=ZZZZ`);
    await settle(page);
    await page.click('[data-lookup]');
    await page.waitForFunction(() => location.hash === '#/asset/ZZZZ');
    await page.waitForFunction(() => document.querySelector('main h1')?.textContent.includes('נכס לא נמצא'), null, { timeout: 5000 })
      .catch(async () => { throw new Error(`unknown symbol not handled: ${(await page.textContent('main')).slice(0, 160)}`); });
    await page.goto(`${base}#/asset/FAIL`);
    await settle(page);
    expect((await page.textContent('.state-error')).includes('תקלה בקבלת נתונים'), 'fetch failure not shown');
    expect(await page.locator('#asset-chart svg').count() === 0, 'chart drawn despite failure');
  });

  await check('market mode: news, events and alerts pages say "not connected"', async () => {
    for (const path of ['news', 'events', 'alerts']) {
      await page.goto(`${base}#/${path}`);
      expect(await page.locator('[data-not-connected]').count() === 1, `#/${path} not marked`);
      expect(await page.locator('.news-card, .event-row, .alert-card').count() === 0, `#/${path} shows content`);
    }
    await page.goto(base);
    await settle(page);
    expect(await page.locator('#watchlist .asset-row').count() === 2, 'market watchlist not used on home');
    expect(await page.locator('#chart-box svg').count() === 1, 'home chart missing');
    await snap(page, '12-market-home');
  });

  await check('market mode without keys shows "setup required" with instructions', async () => {
    const p2 = await newPage();
    await setMode(p2, base2, 'market');
    await p2.waitForSelector('#sources .tag-setup');
    expect((await p2.textContent('#sources')).includes('ALPHA_VANTAGE_API_KEY'), 'missing key name');
    expect(await p2.isVisible('#sources details[open] .steps'), 'setup steps not shown');
    await snap(p2, '13-setup-required');
    await p2.goto(`${base2}#/assets`);
    await settle(p2);
    expect(await p2.locator('.row-error:has-text("נדרשת הגדרה")').count() === 4, 'rows not marked setup-required');
    await p2.goto(`${base2}#/asset/AAPL`);
    await settle(p2);
    expect(await p2.isVisible('.state-setup:has-text("נדרשת הגדרה")'), 'asset page setup state missing');
    expect(upstream.calls.every((c) => c.url.searchParams.get('apikey') !== ''), 'called provider without a key');
  });

  await check('market mode on a phone: no horizontal scroll', async () => {
    const phone = await newPage({ width: 390, height: 844 });
    await setMode(phone, base, 'market');
    for (const path of ['', 'assets', 'asset/AAPL', 'asset/BTC', 'settings']) {
      await phone.goto(`${base}#/${path}`);
      await settle(phone);
      const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow <= 1, `horizontal overflow ${overflow}px on #/${path}`);
    }
    await snap(phone, '14-market-settings-phone');
  });

  await check('no console errors', async () => {
    // 4xx/5xx answers the tests provoke on purpose are logged by the browser
    // as failed resources; those are expected here.
    const relevant = consoleErrors.filter((e) => !e.includes('favicon') && !/status of (404|503|504|502)/.test(e));
    expect(relevant.length === 0, relevant.join(' | '));
  });
} finally {
  await browser.close();
  server.close();
  server2.close();
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} browser checks passed`);
process.exit(failed ? 1 : 0);
