/**
 * End-to-end walk through the complete demo flow, in a real browser.
 *
 * It starts the project's own static server, drives Chromium through the whole
 * acceptance path - load the example, pick a symbol, filter dates, read the
 * statistics and charts, export both files, clear the data - and cross-checks the
 * numbers the page displays against the same numbers computed independently from
 * the library modules. A UI that renders a stale or unrelated figure fails here.
 *
 * Playwright is required. When it is not installed the script says so and exits
 * 0, so `npm test` remains the gate and this stays an extra.
 *
 * Usage: node tests/e2e/demo-flow.mjs [--headed] [--keep-screenshots <dir>]
 */

import assert from 'node:assert/strict';
import { spawn, execSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdtemp, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { generateDemoCsv } from '../../src/lib/demo.js';
import { validateDataset } from '../../src/lib/validate.js';
import { computeStats } from '../../src/lib/stats.js';
import { selectRows } from '../../src/lib/selection.js';
import { formatDate, formatInteger, formatPercent, formatPrice } from '../../src/lib/format.js';
import { parseCsv } from '../../src/lib/csv.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(import.meta.url);

const args = process.argv.slice(2);
const headed = args.includes('--headed');
const screenshotDirArg = args.indexOf('--keep-screenshots');
const screenshotDir =
  screenshotDirArg !== -1 && args[screenshotDirArg + 1] ? args[screenshotDirArg + 1] : null;

let passed = 0;
async function step(name, body) {
  await body();
  passed += 1;
  console.log(`  ✓ ${name}`);
}

/** Resolves Playwright from the project or from the global npm root. */
function loadPlaywright() {
  try {
    return require('playwright');
  } catch {
    try {
      const globalRoot = execSync('npm root -g', { encoding: 'utf8' }).trim();
      return require(path.join(globalRoot, 'playwright'));
    } catch {
      return null;
    }
  }
}

function startServer(port) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [path.join(root, 'scripts', 'serve.mjs'), '--port', String(port)], {
      cwd: root,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    const timer = setTimeout(() => reject(new Error(`server did not start: ${output}`)), 10_000);
    child.stdout.on('data', (chunk) => {
      output += chunk;
      const match = output.match(/http:\/\/127\.0\.0\.1:(\d+)\//);
      if (match) {
        clearTimeout(timer);
        resolve({ child, baseUrl: `http://127.0.0.1:${match[1]}` });
      }
    });
    child.stderr.on('data', (chunk) => {
      output += chunk;
    });
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`server exited with ${code}: ${output}`));
    });
  });
}

/** The expected numbers, computed from the library rather than read from the UI. */
function expectedFor(symbol, range = {}) {
  const result = validateDataset(generateDemoCsv(), { fileName: 'datascope_demo_data.csv' });
  assert.equal(result.ok, true);
  const rows = selectRows(result.dataset.rows, { symbol, ...range });
  return { dataset: result.dataset, rows, stats: computeStats(rows) };
}

async function main() {
  const playwright = loadPlaywright();
  if (!playwright) {
    console.log('Playwright is not available - skipping the browser test (npm test still covers the logic).');
    return;
  }
  const chromium = playwright.chromium ?? playwright.default?.chromium;

  const { child, baseUrl } = await startServer(4399);
  const shots = screenshotDir
    ? (await mkdir(screenshotDir, { recursive: true }), screenshotDir)
    : await mkdtemp(path.join(tmpdir(), 'datascope-e2e-'));

  const browser = await chromium.launch({ headless: !headed });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    acceptDownloads: true,
    locale: 'he-IL',
  });
  const page = await context.newPage();

  /** Any uncaught page error or console error fails the run. */
  const pageProblems = [];
  page.on('pageerror', (error) => pageProblems.push(`pageerror: ${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') pageProblems.push(`console: ${message.text()}`);
  });
  page.on('requestfailed', (request) => pageProblems.push(`requestfailed: ${request.url()}`));

  /** Everything the page requests must come from our own origin. */
  const externalRequests = [];
  await context.route('**/*', (route) => {
    const url = route.request().url();
    if (!url.startsWith(baseUrl) && !url.startsWith('data:') && !url.startsWith('blob:')) {
      externalRequests.push(url);
    }
    route.continue();
  });

  try {
    console.log(`DataScope e2e (${baseUrl})`);

    await step('the page loads with its tagline and an empty state', async () => {
      await page.goto(`${baseUrl}/`, { waitUntil: 'load' });
      assert.equal(await page.title(), 'DataScope — כלי לימודי לניתוח נתונים היסטוריים');
      assert.equal(await page.locator('.tagline').innerText(), 'כלי לימודי לניתוח נתונים היסטוריים');
      assert.equal(await page.locator('html').getAttribute('dir'), 'rtl');
      assert.equal(await page.locator('html').getAttribute('lang'), 'he');
      assert.ok(await page.locator('#empty-state').isVisible());
      assert.ok(await page.locator('#analysis').isHidden());
      assert.equal(await page.locator('#clear-data').isDisabled(), true);
    });

    await step('loading the example fills the symbol selector from the data', async () => {
      await page.click('#load-demo');
      await page.waitForSelector('#analysis:not([hidden])');
      const options = await page.locator('#symbol-select option').allInnerTexts();
      assert.deepEqual(options, ['DEMO_A', 'DEMO_B', 'DEMO_C']);
      assert.equal(await page.locator('#clear-data').isDisabled(), false);
    });

    await step('the source banner names the file, the range and the provenance', async () => {
      const { dataset } = expectedFor('DEMO_A');
      const banner = await page.locator('#source-banner').innerText();
      assert.ok(banner.includes('datascope_demo_data.csv'), banner);
      assert.ok(banner.includes(formatDate(dataset.firstDate)), banner);
      assert.ok(banner.includes(formatDate(dataset.lastDate)), banner);
      assert.ok(banner.includes('נתוני הדגמה מומצאים'), banner);
      // The demo file is grouped by symbol, so the reorder notice must show.
      assert.ok(await page.locator('.notice-sorted').isVisible());
    });

    await step('the statistics match values computed independently', async () => {
      const { stats } = expectedFor('DEMO_A');
      const text = await page.locator('#stats-grid').innerText();
      for (const expected of [
        formatInteger(stats.count),
        formatDate(stats.firstDate),
        formatDate(stats.lastDate),
        formatPrice(stats.firstClose),
        formatPrice(stats.lastClose),
        formatPercent(stats.percentChange),
        formatPrice(stats.minClose),
        formatDate(stats.minCloseDate),
        formatPrice(stats.maxClose),
        formatDate(stats.maxCloseDate),
      ]) {
        assert.ok(text.includes(expected), `stats grid is missing ${expected}\n${text}`);
      }
      // Each statistic carries its Hebrew explanation.
      assert.equal(await page.locator('.stat-card').count(), 7);
      const notes = await page.locator('.stat-note').allInnerTexts();
      assert.equal(notes.length, 7);
      assert.ok(notes.every((note) => note.trim().length > 20));
    });

    await step('both charts render, with one volume bar per observation', async () => {
      const { stats } = expectedFor('DEMO_A');
      assert.ok((await page.locator('#price-chart svg').count()) === 1);
      assert.ok((await page.locator('#price-chart path.c-line').count()) === 1);
      assert.ok((await page.locator('#price-chart path.c-area').count()) === 1);
      const bars = await page.locator('#volume-chart .c-bar').count();
      assert.equal(bars, stats.count);
      // Separate charts, not one dual-axis chart.
      assert.equal(await page.locator('.chart-figure').count(), 2);
    });

    await step('the charts are keyboard operable and announce the value read', async () => {
      await page.locator('#price-chart svg').focus();
      await page.keyboard.press('Home');
      const first = await page.locator('#chart-readout').innerText();
      const { stats } = expectedFor('DEMO_A');
      assert.ok(first.includes('DEMO_A'), first);
      assert.ok(first.includes(formatDate(stats.firstDate)), first);
      await page.keyboard.press('End');
      const last = await page.locator('#chart-readout').innerText();
      assert.ok(last.includes(formatDate(stats.lastDate)), last);
      await page.keyboard.press('ArrowLeft');
      const stepped = await page.locator('#chart-readout').innerText();
      assert.notEqual(stepped, last);
    });

    await step('hovering the price chart shows a tooltip', async () => {
      const box = await page.locator('#price-chart svg').boundingBox();
      await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
      await page.waitForSelector('#price-tooltip:not([hidden])');
      const tip = await page.locator('#price-tooltip').innerText();
      assert.ok(tip.includes('סגירה'), tip);
      assert.ok(tip.includes('מחזור'), tip);
    });

    await step('the automatic summary is labelled and template-generated', async () => {
      const { stats } = expectedFor('DEMO_A');
      assert.equal(await page.locator('#summary-heading').innerText(), 'סיכום אוטומטי');
      const summary = await page.locator('#summary-body').innerText();
      assert.ok(summary.includes('DEMO_A'), summary);
      assert.ok(summary.includes(formatPercent(stats.percentChange)), summary);
      const note = await page.locator('#summary-heading + .panel-note').innerText();
      assert.ok(note.includes('לא נעשה שימוש במודל בינה מלאכותית'), note);
    });

    await step('searching narrows the selector and selecting a symbol re-renders everything', async () => {
      await page.fill('#symbol-search', 'demo_b');
      assert.deepEqual(await page.locator('#symbol-select option').allInnerTexts(), ['DEMO_B']);
      await page.selectOption('#symbol-select', 'DEMO_B');

      const { stats } = expectedFor('DEMO_B');
      const text = await page.locator('#stats-grid').innerText();
      assert.ok(text.includes(formatPercent(stats.percentChange)), text);
      assert.ok(text.includes(formatPrice(stats.lastClose)), text);
      const summary = await page.locator('#summary-body').innerText();
      assert.ok(summary.includes('DEMO_B'), summary);
      assert.ok(summary.includes('ירידה'), summary); // DEMO_B trends down
      const caption = await page.locator('.data-table caption').innerText();
      assert.ok(caption.includes('DEMO_B'), caption);
    });

    await step('a search with no match reports it instead of failing silently', async () => {
      await page.fill('#symbol-search', 'zzzz');
      const note = await page.locator('#symbol-count').innerText();
      assert.ok(note.includes('אין סמל שתואם'), note);
      await page.fill('#symbol-search', '');
    });

    const RANGE = { from: '2024-03-01', to: '2024-05-31' };

    await step('filtering by date range moves every panel together', async () => {
      await page.selectOption('#symbol-select', 'DEMO_A');
      await page.fill('#date-from', RANGE.from);
      await page.fill('#date-to', RANGE.to);
      await page.locator('#date-to').blur();

      const { stats } = expectedFor('DEMO_A', RANGE);
      assert.ok(stats.count > 0 && stats.count < 100);

      const text = await page.locator('#stats-grid').innerText();
      assert.ok(text.includes(formatInteger(stats.count)), text);
      assert.ok(text.includes(formatDate(stats.firstDate)), text);
      assert.ok(text.includes(formatPercent(stats.percentChange)), text);
      assert.equal(await page.locator('#volume-chart .c-bar').count(), stats.count);
      const caption = await page.locator('.data-table caption').innerText();
      assert.ok(caption.includes(String(stats.count)), caption);
      const summary = await page.locator('#summary-body').innerText();
      assert.ok(summary.includes(formatDate(stats.lastDate)), summary);
    });

    await step('the table sorts and pages over exactly the filtered rows', async () => {
      const { stats, rows } = expectedFor('DEMO_A', RANGE);
      await page.selectOption('#page-size', '10');
      const pageCount = Math.ceil(stats.count / 10);
      assert.equal(await page.locator('#page-info').innerText(), `עמוד 1 מתוך ${pageCount}`);
      assert.equal(await page.locator('#page-prev').isDisabled(), true);
      assert.equal(await page.locator('.data-table tbody tr').count(), 10);

      // Sorting by close, descending, puts the maximum of the range on top.
      await page.click('.sort-button[data-sort-key="close"]');
      let firstRow = await page.locator('.data-table tbody tr').first().innerText();
      const expectedMax = Math.max(...rows.map((row) => row.close));
      assert.ok(firstRow.includes(formatPrice(expectedMax)), `${firstRow} vs ${expectedMax}`);
      assert.equal(
        await page.locator('.data-table th').nth(1).getAttribute('aria-sort'),
        'descending',
      );

      // Clicking again flips to ascending, which is the minimum.
      await page.click('.sort-button[data-sort-key="close"]');
      firstRow = await page.locator('.data-table tbody tr').first().innerText();
      const expectedMin = Math.min(...rows.map((row) => row.close));
      assert.ok(firstRow.includes(formatPrice(expectedMin)), `${firstRow} vs ${expectedMin}`);

      await page.click('#page-next');
      assert.equal(await page.locator('#page-info').innerText(), `עמוד 2 מתוך ${pageCount}`);
      await page.selectOption('#page-size', '25');
    });

    await step('exporting CSV downloads exactly the filtered rows', async () => {
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.click('#export-csv'),
      ]);
      const suggested = download.suggestedFilename();
      assert.match(suggested, /^datascope_DEMO_A_\d{4}-\d{2}-\d{2}\.csv$/, suggested);
      const file = path.join(shots, suggested);
      await download.saveAs(file);
      const content = await readFile(file, 'utf8');

      const { rows } = expectedFor('DEMO_A', RANGE);
      const { records } = parseCsv(content);
      assert.deepEqual(records[0].cells, ['date', 'symbol', 'close', 'volume']);
      assert.equal(records.length - 1, rows.length);
      assert.equal(records[1].cells[0], rows[0].date);
      assert.equal(Number(records[1].cells[2]), rows[0].close);
      assert.equal(records[records.length - 1].cells[0], rows[rows.length - 1].date);
      // The export re-imports cleanly.
      const reimported = validateDataset(content, { fileName: suggested });
      assert.equal(reimported.ok, true);
    });

    await step('exporting the Hebrew report downloads a readable text file', async () => {
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.click('#export-report'),
      ]);
      const suggested = download.suggestedFilename();
      assert.match(suggested, /^datascope_DEMO_A_\d{4}-\d{2}-\d{2}\.txt$/, suggested);
      const file = path.join(shots, suggested);
      await download.saveAs(file);
      const report = await readFile(file, 'utf8');

      const { stats } = expectedFor('DEMO_A', RANGE);
      assert.ok(report.includes('כלי לימודי לניתוח נתונים היסטוריים'), 'missing tagline');
      assert.ok(report.includes('סמל נבחר: DEMO_A'), 'missing symbol');
      assert.ok(report.includes(`מספר תצפיות: ${stats.count}`), 'missing count');
      assert.ok(report.includes(formatPercent(stats.percentChange)), 'missing change');
      assert.ok(report.includes('מגבלות הנתונים'), 'missing limitations');
      assert.ok(report.includes('פיצולי מניות ולדיבידנדים'), 'missing adjustment caveat');
      assert.ok(report.includes('נתונים מומצאים'), 'missing demo caveat');
    });

    await step('a range with no observations shows the no-results state', async () => {
      await page.selectOption('#symbol-select', 'DEMO_C');
      await page.fill('#date-from', '2024-12-25');
      await page.fill('#date-to', '2024-12-25');
      await page.locator('#date-to').blur();
      await page.waitForSelector('#no-results:not([hidden])');
      const text = await page.locator('#no-results').innerText();
      assert.ok(text.includes('DEMO_C'), text);
      assert.ok(text.includes('אינם שגיאה'), text);
      assert.ok(await page.locator('#results').isHidden());
    });

    await step('an inverted range explains itself instead of showing nothing', async () => {
      await page.fill('#date-from', '2024-06-01');
      await page.fill('#date-to', '2024-01-01');
      await page.locator('#date-to').blur();
      await page.waitForSelector('#range-message:not([hidden])');
      const message = await page.locator('#range-message').innerText();
      assert.ok(message.includes('מאוחר מתאריך הסיום'), message);
    });

    await step('resetting the range restores the full period for the symbol', async () => {
      await page.click('#reset-range');
      await page.waitForSelector('#results:not([hidden])');
      const { stats } = expectedFor('DEMO_C');
      const text = await page.locator('#stats-grid').innerText();
      assert.ok(text.includes(formatInteger(stats.count)), text);
      assert.ok(await page.locator('#range-message').isHidden());
    });

    await step('a single observation is handled without a spurious trend', async () => {
      await page.fill('#date-from', '2024-01-02');
      await page.fill('#date-to', '2024-01-02');
      await page.locator('#date-to').blur();
      const text = await page.locator('#stats-grid').innerText();
      assert.ok(text.includes('0.00%'), text);
      const summary = await page.locator('#summary-body').innerText();
      assert.ok(summary.includes('תצפית אחת בלבד'), summary);
      assert.equal(await page.locator('#volume-chart .c-bar').count(), 1);
      await page.click('#reset-range');
    });

    await page.screenshot({ path: path.join(shots, 'analysis-desktop.png'), fullPage: true });

    await step('uploading the sample CSV goes through the same import path', async () => {
      await page.click('#clear-data');
      await page.setInputFiles('#file-input', path.join(root, 'sample', 'datascope_sample.csv'));
      await page.waitForSelector('#analysis:not([hidden])');
      const banner = await page.locator('#source-banner').innerText();
      assert.ok(banner.includes('datascope_sample.csv'), banner);
      const status = await page.locator('#status-message').innerText();
      assert.ok(status.includes('756'), status);
    });

    await step('dropping a file on the dropzone imports it', async () => {
      await page.click('#clear-data');
      const csv = await readFile(path.join(root, 'sample', 'datascope_sample.csv'), 'utf8');
      // Build a real DataTransfer in the page and drop it on the zone, which is
      // the path a mouse drag takes.
      await page.evaluate(async (content) => {
        const transfer = new DataTransfer();
        transfer.items.add(new File([content], 'dropped.csv', { type: 'text/csv' }));
        const zone = document.getElementById('dropzone');
        zone.dispatchEvent(new DragEvent('dragover', { dataTransfer: transfer, bubbles: true }));
        zone.dispatchEvent(new DragEvent('drop', { dataTransfer: transfer, bubbles: true }));
      }, csv);
      await page.waitForSelector('#analysis:not([hidden])');
      const banner = await page.locator('#source-banner').innerText();
      assert.ok(banner.includes('dropped.csv'), banner);
      assert.deepEqual(await page.locator('#symbol-select option').allInnerTexts(), [
        'DEMO_A',
        'DEMO_B',
        'DEMO_C',
      ]);
    });

    await step('an invalid file is blocked with row numbers and no data is shown', async () => {
      const badFile = path.join(shots, 'broken.csv');
      const { writeFile } = await import('node:fs/promises');
      await writeFile(
        badFile,
        [
          'date,symbol,close',
          '2024-01-02,AAA,100',
          'nope,AAA,100',
          '2024-01-03,AAA,abc',
        ].join('\n'),
        'utf8',
      );
      await page.setInputFiles('#file-input', badFile);
      await page.waitForSelector('#validation-report:not([hidden])');
      const report = await page.locator('#validation-report').innerText();
      assert.ok(report.includes('הייבוא נחסם'), report);
      assert.ok(report.includes('volume'), report);
      assert.ok(report.includes('שורה'), report);
      await page.screenshot({ path: path.join(shots, 'validation-error.png') });
      // The previously imported data is still on screen: a failed import does not
      // wipe what the user was looking at.
      assert.ok(await page.locator('#analysis').isVisible());
    });

    await step('clearing the data resets the UI and stores nothing', async () => {
      await page.click('#clear-data');
      await page.waitForSelector('#empty-state:not([hidden])');
      assert.ok(await page.locator('#analysis').isHidden());
      assert.equal(await page.locator('#clear-data').isDisabled(), true);
      assert.equal(await page.locator('#table-container').innerText(), '');

      const storage = await page.evaluate(() => ({
        local: window.localStorage.length,
        session: window.sessionStorage.length,
        cookie: document.cookie,
      }));
      assert.deepEqual(storage, { local: 0, session: 0, cookie: '' });

      // A reload must come back empty: nothing is persisted between visits.
      await page.reload();
      assert.ok(await page.locator('#empty-state').isVisible());
      assert.ok(await page.locator('#analysis').isHidden());
    });

    await step('the layout works at phone width without horizontal scrolling', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.click('#load-demo');
      await page.waitForSelector('#analysis:not([hidden])');
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      assert.ok(overflow <= 1, `horizontal overflow of ${overflow}px`);
      await page.screenshot({ path: path.join(shots, 'analysis-mobile.png'), fullPage: true });
      await page.setViewportSize({ width: 1280, height: 900 });
    });

    await step('the page made no external request and logged no error', async () => {
      assert.deepEqual(externalRequests, []);
      assert.deepEqual(pageProblems, []);
    });

    console.log(`\n${passed} browser checks passed. Screenshots and downloads: ${shots}`);
  } catch (error) {
    await page
      .screenshot({ path: path.join(shots, 'failure.png'), fullPage: true })
      .catch(() => {});
    console.error(`\n✗ failed after ${passed} checks: ${error.message}`);
    if (pageProblems.length > 0) console.error('page problems:', pageProblems);
    console.error(`artifacts: ${shots}`);
    process.exitCode = 1;
  } finally {
    await browser.close();
    child.kill();
  }
}

await main();
