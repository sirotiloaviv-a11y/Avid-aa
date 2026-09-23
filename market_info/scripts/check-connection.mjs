// Connection check against the real data providers.
//
//   npm run check-connection                      first configured stock and crypto
//   npm run check-connection -- --stock MSFT --crypto ETH
//
// Uses up to 1 Alpha Vantage request and 2 CoinGecko requests. Prints a
// report and saves it to connection-report.txt (no keys are included).
// Exit code: 0 passed, 1 failed, 2 setup required / partial.
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../server/config.mjs';
import { MarketCache } from '../server/cache.mjs';
import { runConnectionCheck, redact } from '../server/connectionCheck.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const arg = (name) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : null;
};

const STATUS = {
  passed: '[עבר]',
  failed: '[נכשל]',
  setup_required: '[נדרשת הגדרה]',
  partial: '[חלקי]',
};
const RESULT = { confirmed: 'אומת', contradicted: 'לא תואם!', not_checked: 'לא נבדק' };

const fmtTime = (ms) => (ms ? `${new Date(ms).toISOString().replace('T', ' ').slice(0, 16)} UTC` : 'לא ידוע');

export function formatReport(report) {
  const lines = [];
  lines.push('בדיקת חיבור לספקי נתוני שוק');
  lines.push(`זמן הבדיקה: ${fmtTime(report.ranAt)}`);
  lines.push(`תוצאה כוללת: ${STATUS[report.overall]}`);
  lines.push('');
  for (const p of report.providers) {
    lines.push(`=== ${p.name} ${STATUS[p.status]}${p.target ? ` — נבדק: ${p.target}` : ''}`);
    lines.push(`סוג הנתונים הצפוי: ${p.delayLabel}`);
    lines.push(`בקשות שנשלחו לספק: ${p.requests}`);
    for (const s of p.steps) lines.push(`  ${s.ok ? '✓' : '✗'} ${s.name}${s.detail ? ` — ${s.detail}` : ''}`);
    if (p.error) lines.push(`  שגיאה (${p.error.code}): ${p.error.message}`);
    if (p.sample) {
      const x = p.sample;
      lines.push('  נתון שהתקבל:');
      lines.push(`    מקור: ${p.name}`);
      lines.push(`    סימול: ${x.symbol}`);
      lines.push(`    מחיר: ${x.price} USD`);
      if (x.changePct !== null && x.changePct !== undefined) {
        lines.push(`    שינוי: ${x.changePct.toFixed(2)}% (${x.changeBasis ?? 'מהסגירה הקודמת'})`);
      }
      lines.push(`    מועד הנתון: ${x.asOfLabel ?? fmtTime(x.asOf)}${x.ageMinutes != null ? ` (לפני ${x.ageMinutes.toFixed(1)} דקות)` : ''}`);
      if (x.lastRefreshed) lines.push(`    Last Refreshed לפי הספק: ${x.lastRefreshed}`);
      lines.push(`    השהיה: ${p.delayLabel}`);
      lines.push(`    היסטוריה: ${x.historyPoints} נקודות${x.firstDate ? ` (${x.firstDate} עד ${x.lastDate})` : ''}`);
      if (x.old) lines.push('    אזהרה: הנתון ישן מהצפוי ביותר מיום מסחר אחד.');
      if (x.droppedRows) lines.push(`    שורות פגומות שהושמטו: ${x.droppedRows}`);
      if (x.candles === false) lines.push('    נרות: הספק אינו מספק (מחיר ונפח 24 שעות בלבד)');
      if (p.attribution) lines.push(`    ${p.attribution}`);
    }
    lines.push('  הנחות על פורמט התשובה:');
    for (const a of p.assumptions) lines.push(`    [${RESULT[a.result]}] ${a.text}${a.note ? ` — ${a.note}` : ''}`);
    lines.push('');
  }
  lines.push('מה הלאה:');
  if (report.overall === 'passed') lines.push('  החיבור לשני הספקים אומת. אפשר לבחור בהגדרות „נתוני שוק”.');
  for (const p of report.providers) {
    if (p.status === 'setup_required') lines.push(`  ${p.name}: חסר מפתח. ראו „הפעלת מצב נתוני שוק” ב-README או במסך ההגדרות.`);
    else if (p.status === 'failed' && p.error?.code === 'network') lines.push(`  ${p.name}: אין חיבור. בדקו חיבור לאינטרנט, חומת אש או VPN, ונסו שוב.`);
    else if (p.status === 'failed' && p.error?.code === 'auth_failed') lines.push(`  ${p.name}: המפתח נדחה. העתיקו אותו שוב לקובץ .env בלי רווחים.`);
    else if (p.status === 'failed' && p.error?.code === 'rate_limited') lines.push(`  ${p.name}: מגבלת בקשות. נסו שוב מאוחר יותר.`);
    else if (p.status === 'failed' && p.assumptions.some((a) => a.result === 'contradicted')) {
      lines.push(`  ${p.name}: פורמט התשובה שונה מהצפוי. שלחו את הקובץ connection-report.txt למפתח.`);
    } else if (p.status === 'failed') lines.push(`  ${p.name}: הבדיקה נכשלה. שלחו את הקובץ connection-report.txt למפתח.`);
  }
  lines.push('');
  lines.push('הדוח אינו כולל מפתחות. בטוח לשתף אותו.');
  return lines.join('\n');
}

async function main() {
  const config = loadConfig({ envFile: join(root, '.env') });
  const cache = new MarketCache({ file: join(root, '.cache', 'market-cache.json') });
  const report = await runConnectionCheck({ config, cache, stock: arg('stock'), crypto: arg('crypto') });
  const text = redact(formatReport(report), [config.alphaVantage.apiKey, config.coinGecko.apiKey]);
  console.log(text);
  writeFileSync(join(root, 'connection-report.txt'), `${text}\n`);
  mkdirSync(join(root, '.cache'), { recursive: true });
  writeFileSync(join(root, '.cache', 'connection-check.json'), JSON.stringify(report, null, 2));
  console.log(`\nהדוח נשמר: ${join(root, 'connection-report.txt')}`);
  process.exitCode = report.overall === 'passed' ? 0 : report.overall === 'failed' ? 1 : 2;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) main();
