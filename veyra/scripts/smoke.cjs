// Browser smoke test for the built app: loads the dashboard, opens the AI
// analysis of a recommendation, runs Auto-Fix and watches the score rise,
// downloads the executive PDF, connects an integration, pauses another and
// opens the findings table, failing on any page error. Saves screenshots to
// ./screenshots.
// Usage: node scripts/smoke.cjs [baseUrl]   (requires the "playwright" package)
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

const base = process.argv[2] ?? 'http://127.0.0.1:4000';
const shots = 'screenshots';

const scoreOf = async (page) => {
  const label = await page.locator('svg[role="img"][aria-label^="Security score"]').getAttribute('aria-label');
  return Number(label.match(/Security score (\d+)/)[1]);
};

(async () => {
  fs.mkdirSync(shots, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/fonts\.(googleapis|gstatic)/.test(m.text())) errors.push(m.text());
  });

  await page.goto(`${base}/#/overview`);
  await page.getByText('Overall security score').waitFor();
  await page.getByRole('heading', { name: 'Security Brain Recommendations' }).waitFor();
  await page.waitForTimeout(1200); // let the gauge animation settle
  const before = await scoreOf(page);
  console.log(`overview: score ${before}`);
  await page.screenshot({ path: `${shots}/overview.png`, fullPage: true });

  // AI analysis panel (rules engine in CI: no API key)
  const firstCard = page.locator('main li').filter({ has: page.getByRole('button', { name: 'Auto-Fix' }) }).first();
  await firstCard.getByRole('button', { name: /AI analysis & fix code/ }).click();
  await firstCard.getByText('For the executive team').waitFor();
  await firstCard.getByRole('tab', { name: /Fix code/ }).click();
  const code = await firstCard.locator('pre code').innerText();
  assert.ok(code.length > 40, 'fix code is shown');
  await firstCard.getByRole('tab', { name: /Side effects/ }).click();
  await firstCard.getByText('Double-check before applying').waitFor();
  console.log(`insight: ${code.split('\n')[0].slice(0, 80)}`);
  await page.screenshot({ path: `${shots}/insight.png`, fullPage: true });

  // Auto-Fix with step-by-step progress toast
  await firstCard.getByRole('button', { name: 'Auto-Fix' }).click();
  await page.getByText(/^Auto-Fix: /).waitFor();
  await page.getByText('Validate permissions').waitFor();
  await page.screenshot({ path: `${shots}/autofix-progress.png` });
  await page.getByText(/^Fixed: /).waitFor({ timeout: 20000 });
  const toastBody = await page.getByText(/^Security score \d+ → \d+/).innerText();
  await page.screenshot({ path: `${shots}/autofix-done.png` });
  await page.waitForTimeout(1200);
  const after = await scoreOf(page);
  console.log(`auto-fix: ${toastBody}; gauge ${before} -> ${after}`);
  assert.ok(after > before, `score should rise after Auto-Fix (${before} -> ${after})`);

  // Manual-only findings offer "Mark resolved" instead
  const manual = page.getByRole('button', { name: 'Mark resolved' }).first();
  if (await manual.count()) {
    await manual.click();
    await page.getByText('Marked for resolution').waitFor();
    console.log('manual: marked a manual-only finding resolved');
  }

  // Executive PDF report
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download Executive Report (PDF)' }).click(),
  ]);
  const pdfPath = `${shots}/${download.suggestedFilename()}`;
  await download.saveAs(pdfPath);
  const pdf = fs.readFileSync(pdfPath);
  assert.match(download.suggestedFilename(), /^veyra-executive-report-\d{4}-\d{2}-\d{2}\.pdf$/);
  assert.equal(pdf.subarray(0, 5).toString(), '%PDF-');
  await page.getByText('Executive report downloaded').waitFor();
  console.log(`report: ${download.suggestedFilename()} (${pdf.length} bytes)`);

  await page.getByRole('link', { name: /Integrations/ }).first().click();
  const m365 = page.locator('article').filter({ hasText: 'Microsoft 365' });
  await m365.getByRole('button', { name: 'Connect' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Use demo values' }).click();
  await dialog.getByRole('button', { name: 'Connect', exact: true }).click();
  await page.getByText('Microsoft 365 connected').waitFor({ timeout: 15000 });
  await dialog.waitFor({ state: 'detached' });
  console.log('integrations: connected Microsoft 365');

  await page.getByRole('switch', { name: /monitoring for GitHub/ }).click();
  await page.getByText('Monitoring paused for GitHub').waitFor();
  console.log('integrations: paused GitHub');
  await page.screenshot({ path: `${shots}/integrations.png`, fullPage: true });

  await page.getByRole('link', { name: /Findings/ }).first().click();
  await page.locator('tbody tr').first().waitFor();
  const rows = await page.locator('tbody tr').count();
  console.log(`findings: ${rows} rows`);
  assert.ok(rows > 5, 'findings table has rows');
  await page.locator('tbody tr').first().click();
  await page.getByText('Remediation', { exact: true }).waitFor();
  await page.screenshot({ path: `${shots}/findings.png`, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/#/overview`);
  await page.getByText('Overall security score').waitFor();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log(`mobile: horizontal overflow ${overflow}px`);
  assert.ok(overflow <= 0, 'no horizontal page scroll at phone width');
  await page.screenshot({ path: `${shots}/mobile.png`, fullPage: true });
  await page.goto(`${base}/#/recommendations`);
  await page.getByRole('button', { name: /AI analysis & fix code/ }).first().click();
  await page.getByText('For the executive team').first().waitFor();
  const overflowRecs = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log(`mobile recommendations: horizontal overflow ${overflowRecs}px`);
  assert.ok(overflowRecs <= 0, 'no horizontal page scroll with the analysis panel open');
  await page.screenshot({ path: `${shots}/mobile-insight.png`, fullPage: true });

  await browser.close();
  assert.deepEqual(errors, [], `page errors:\n${errors.join('\n')}`);
  console.log('smoke test passed');
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
