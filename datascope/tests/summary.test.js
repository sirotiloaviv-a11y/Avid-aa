import test from 'node:test';
import assert from 'node:assert/strict';

import { buildLimitations, buildSummary, SUMMARY_GENERATOR } from '../src/lib/summary.js';
import { computeStats } from '../src/lib/stats.js';

function summaryFor(rows, extra = {}) {
  return buildSummary({
    symbol: 'DEMO_A',
    fileName: 'demo.csv',
    isDemo: false,
    requestedRange: { from: null, to: null },
    stats: computeStats(rows),
    ...extra,
  });
}

const TWO_ROWS = [
  { date: '2024-01-02', symbol: 'DEMO_A', close: 100, volume: 1000 },
  { date: '2024-03-04', symbol: 'DEMO_A', close: 110, volume: 3000 },
];

test('the summary is labelled and declares itself template-generated', () => {
  const summary = summaryFor(TWO_ROWS);
  assert.equal(summary.title, 'סיכום אוטומטי');
  assert.equal(summary.generator.kind, 'local-template');
  assert.equal(summary.generator.usesAiModel, false);
  assert.equal(SUMMARY_GENERATOR.usesAiModel, false);
});

test('the summary names the symbol, the period, the change and the extremes', () => {
  const text = summaryFor(TWO_ROWS).paragraphs.join('\n');
  assert.match(text, /DEMO_A/);
  assert.match(text, /02\.01\.2024/);
  assert.match(text, /04\.03\.2024/);
  assert.match(text, /\+10\.00%/);
  assert.match(text, /עלייה/);
  assert.match(text, /100/);
  assert.match(text, /110/);
  assert.match(text, /2 תצפיות/);
});

test('a fall is described as a fall', () => {
  const text = summaryFor([
    { date: '2024-01-02', symbol: 'DEMO_A', close: 200, volume: 1 },
    { date: '2024-01-03', symbol: 'DEMO_A', close: 150, volume: 1 },
  ]).paragraphs.join('\n');
  assert.match(text, /ירידה/);
  assert.match(text, /−25\.00%/);
  assert.equal(text.includes('עלייה'), false);
});

test('a single observation is described as such, with no trend claim', () => {
  const text = summaryFor([{ date: '2024-01-02', symbol: 'DEMO_A', close: 100, volume: 1 }])
    .paragraphs.join('\n');
  assert.match(text, /תצפית אחת בלבד/);
  assert.match(text, /אין משמעות למינימום/);
});

test('an empty selection produces an explanation, not statistics', () => {
  const summary = summaryFor([], { requestedRange: { from: '2025-01-01', to: '2025-02-01' } });
  const text = summary.paragraphs.join('\n');
  assert.match(text, /אין תצפיות בטווח/);
  assert.match(text, /01\.01\.2025/);
  assert.match(text, /אין זו שגיאה/);
  assert.ok(summary.limitations.length > 0);
});

test('with no symbol selected the summary asks for one', () => {
  const summary = buildSummary({
    symbol: null,
    fileName: 'demo.csv',
    isDemo: false,
    requestedRange: { from: null, to: null },
    stats: computeStats([]),
  });
  assert.match(summary.paragraphs.join('\n'), /לא נבחר סמל/);
});

test('the summary states the data limitations, including split and dividend adjustment', () => {
  const summary = summaryFor(TWO_ROWS);
  const limitations = summary.limitations.join('\n');
  assert.match(limitations, /פיצולי מניות ולדיבידנדים/);
  assert.match(limitations, /מטבע/);
  assert.match(limitations, /אינם נתוני שוק מאומתים/);
  assert.match(limitations, /תאריכים שאינם מופיעים בקובץ/);
  assert.match(limitations, /כלי לימודי/);
});

test('demo data carries its own "invented data" limitation, first in the list', () => {
  const withDemo = buildLimitations({ isDemo: true });
  const withoutDemo = buildLimitations({ isDemo: false });
  assert.match(withDemo[0], /נתונים מומצאים/);
  assert.equal(withDemo.length, withoutDemo.length + 1);
  assert.equal(withoutDemo.some((item) => item.includes('מומצאים')), false);
});

test('the summary refuses to explain why the price moved', () => {
  const text = summaryFor(TWO_ROWS).paragraphs.join('\n');
  assert.match(text, /אינם מסבירים מדוע/);
});

test('the summary makes no recommendation and no prediction', () => {
  const text = [...summaryFor(TWO_ROWS).paragraphs, ...summaryFor(TWO_ROWS).limitations].join('\n');
  for (const forbidden of ['המלצה', 'כדאי לקנות', 'כדאי למכור', 'תחזית', 'יעלה', 'ירד בעתיד']) {
    assert.equal(text.includes(forbidden), false, forbidden);
  }
});

test('the summary returns plain text, so imported symbols cannot become markup', () => {
  const hostile = '<img src=x onerror="alert(1)">';
  const summary = buildSummary({
    symbol: hostile,
    fileName: 'x.csv',
    isDemo: false,
    requestedRange: { from: null, to: null },
    stats: computeStats(TWO_ROWS),
  });
  const text = summary.paragraphs.join('\n');
  // The value is carried verbatim as data - no escaping, no interpretation. The
  // DOM layer renders it with textContent, and the audit test forbids innerHTML.
  assert.ok(text.includes(hostile));
  assert.equal(typeof text, 'string');
  for (const paragraph of summary.paragraphs) assert.equal(typeof paragraph, 'string');
});
