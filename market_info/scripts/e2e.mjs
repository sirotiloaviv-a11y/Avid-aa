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
const server = createAppServer(dir);
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${server.address().port}/`;
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

  await check('no console errors', async () => {
    const relevant = consoleErrors.filter((e) => !e.includes('favicon'));
    expect(relevant.length === 0, relevant.join(' | '));
  });
} finally {
  await browser.close();
  server.close();
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} browser checks passed`);
process.exit(failed ? 1 : 0);
