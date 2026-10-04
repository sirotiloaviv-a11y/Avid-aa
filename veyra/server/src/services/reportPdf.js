import { PdfDocument } from '../lib/pdf.js';

// Executive security report: renders SecurityBrain#executiveReport() as an
// A4 PDF. Light theme for print, with the dashboard's dark brand header.

const W = 595.28;
const H = 841.89;
const M = 40;
const CW = W - M * 2;
const FOOTER_Y = H - 34;
const BOTTOM = FOOTER_Y - 14;

const C = {
  ink: '#0b1220',
  body: '#334155',
  muted: '#64748b',
  faint: '#94a3b8',
  rule: '#e2e8f0',
  soft: '#f8fafc',
  softer: '#f1f5f9',
  header: '#0a0f1c',
  brand: '#0e93b0',
  brandLight: '#38d5f0',
  indigo: '#6366f1',
  white: '#ffffff',
  good: '#059669',
};

const SEVERITY = {
  critical: { label: 'Critical', color: '#e11d48', tint: '#ffe4e6' },
  high: { label: 'High', color: '#ea580c', tint: '#ffedd5' },
  medium: { label: 'Medium', color: '#d97706', tint: '#fef3c7' },
  low: { label: 'Low', color: '#0284c7', tint: '#e0f2fe' },
};

export function scoreColor(score) {
  if (score >= 80) return '#059669';
  if (score >= 70) return '#65a30d';
  if (score >= 55) return '#d97706';
  if (score >= 40) return '#ea580c';
  return '#e11d48';
}

const formatDate = (iso) => new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' });
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** Plain-language summary paragraph for the cover section. */
export function executiveSummaryText(report) {
  const { risk, compliance, tenant, projectedScore, topActions } = report;
  const top = risk.byCategory[0];
  const soc2 = compliance.find((f) => f.id === 'soc2');
  const iso = compliance.find((f) => f.id === 'iso27001');
  const sentences = [
    `${tenant}'s security posture is rated ${risk.grade} (${risk.label}), with an overall score of ${risk.score}/100 across ${risk.coverage.monitored} of ${risk.coverage.total} supported platforms.`,
  ];
  if (risk.open === 0) {
    sentences.push('There are no open findings on the monitored platforms.');
  } else {
    sentences.push(`${plural(risk.counts.critical, 'critical issue')} and ${plural(risk.counts.high, 'high-severity issue')} are open${top ? `; the largest share of risk sits in ${top.category} (${top.share}%)` : ''}.`);
  }
  if (risk.trend?.delta7d) {
    sentences.push(`The score has ${risk.trend.delta7d > 0 ? 'improved' : 'declined'} by ${Math.abs(risk.trend.delta7d)} points over the past 7 days.`);
  }
  if (topActions.length && projectedScore > risk.score) {
    sentences.push(`Resolving the ${topActions.length === 1 ? 'priority item' : `${topActions.length} priority items`} in this report would raise the score to ${projectedScore}/100.`);
  }
  if (soc2?.readiness != null && iso?.readiness != null) {
    sentences.push(`Compliance readiness stands at ${soc2.readiness}% for SOC 2 and ${iso.readiness}% for ISO 27001.`);
  }
  if (risk.coverage.monitored < risk.coverage.total) {
    sentences.push(`${plural(risk.coverage.total - risk.coverage.monitored, 'platform')} ${risk.coverage.total - risk.coverage.monitored === 1 ? 'is' : 'are'} not yet monitored, so actual exposure may be higher.`);
  }
  return sentences.join(' ');
}

class ReportWriter {
  constructor(report) {
    this.report = report;
    this.doc = new PdfDocument({
      width: W,
      height: H,
      info: { Title: `Executive Security Report - ${report.tenant}`, Author: 'Veyra Security Brain', Subject: 'Security posture and compliance readiness' },
    });
    this.y = 0;
  }

  // ---------------------------------------------------------------- layout

  ensure(height) {
    if (this.y + height <= BOTTOM) return;
    this.doc.addPage();
    this.continuationHeader();
  }

  continuationHeader() {
    const { doc } = this;
    doc.rect(0, 0, W, 34, { fill: C.header });
    doc.text('VEYRA', M, 12, { size: 9, font: 'bold', color: C.brandLight });
    doc.text('Executive Security Report', M + 40, 12, { size: 9, color: '#cbd5e1' });
    doc.text(this.report.tenant, M, 12, { size: 9, font: 'bold', color: C.white, align: 'right', width: CW });
    this.y = 56;
  }

  /** Section heading; `keepWith` reserves room for the first block so headings are never orphaned. */
  section(title, subtitle, keepWith = 40) {
    this.ensure(34 + keepWith);
    const { doc } = this;
    doc.text(title, M, this.y, { size: 13, font: 'bold', color: C.ink });
    if (subtitle) doc.text(subtitle, M, this.y + 3, { size: 8.5, color: C.muted, align: 'right', width: CW });
    doc.rect(M, this.y + 20, 28, 2.2, { fill: C.brand });
    doc.line(M + 28, this.y + 21.1, M + CW, this.y + 21.1, { color: C.rule, width: 0.6 });
    this.y += 34;
  }

  pill(text, x, y, { color, tint, size = 7.5 }) {
    const width = this.doc.measure(text.toUpperCase(), size, 'bold') + 12;
    this.doc.rect(x, y, width, size + 7, { fill: tint, radius: (size + 7) / 2 });
    this.doc.text(text.toUpperCase(), x + 6, y + 3.6, { size, font: 'bold', color });
    return width;
  }

  // -------------------------------------------------------------- sections

  cover() {
    const { doc, report } = this;
    doc.rect(0, 0, W, 104, { fill: C.header });
    doc.rect(0, 104, W, 3, { fill: C.brand });
    // Shield mark
    doc.rect(M, 26, 26, 26, { stroke: C.brandLight, lineWidth: 1.6, radius: 7 });
    doc.text('V', M, 31.5, { size: 14, font: 'bold', color: C.brandLight, align: 'center', width: 26 });
    doc.text('VEYRA SECURITY BRAIN', M + 36, 27, { size: 8.5, font: 'bold', color: C.brandLight });
    doc.text('Executive Security Report', M + 36, 40, { size: 19, font: 'bold', color: C.white });
    doc.text(report.tenant, M, 30, { size: 11, font: 'bold', color: C.white, align: 'right', width: CW });
    doc.text(formatDate(report.generatedAt), M, 46, { size: 9, color: '#cbd5e1', align: 'right', width: CW });
    const label = 'CONFIDENTIAL';
    const lw = doc.measure(label, 7, 'bold') + 14;
    doc.rect(M + CW - lw, 64, lw, 15, { stroke: '#475569', lineWidth: 0.8, radius: 7.5 });
    doc.text(label, M + CW - lw + 7, 68, { size: 7, font: 'bold', color: '#cbd5e1' });
    this.y = 130;
  }

  summary() {
    const { doc, report } = this;
    const { risk } = report;
    this.section('Executive Security Summary', `Generated ${formatDate(report.generatedAt)}`);
    const top = this.y;

    // Score card with gauge
    const cardW = 168;
    const cardH = 182;
    doc.rect(M, top, cardW, cardH, { fill: C.soft, stroke: C.rule, lineWidth: 0.6, radius: 10 });
    const cx = M + cardW / 2;
    const cy = top + 78;
    const color = scoreColor(risk.score);
    doc.arc(cx, cy, 54, -135, 135, { color: '#e2e8f0', width: 11 });
    if (risk.score > 0) doc.arc(cx, cy, 54, -135, -135 + (270 * Math.min(100, risk.score)) / 100, { color, width: 11 });
    doc.text(String(risk.score), cx - 50, cy - 20, { size: 34, font: 'bold', color: C.ink, align: 'center', width: 100 });
    doc.text('out of 100', cx - 50, cy + 16, { size: 8, color: C.muted, align: 'center', width: 100 });
    const gradeText = `GRADE ${risk.grade}  ·  ${risk.label.toUpperCase()}`;
    const gw = doc.measure(gradeText, 8, 'bold') + 18;
    doc.rect(cx - gw / 2, top + 142, gw, 18, { fill: color, radius: 9 });
    doc.text(gradeText, cx - gw / 2, top + 146.5, { size: 8, font: 'bold', color: C.white, align: 'center', width: gw });
    const delta = risk.trend?.delta7d ?? 0;
    doc.text(`${delta >= 0 ? '+' : ''}${delta} vs 7 days ago`, M, top + 165, { size: 7.5, color: delta >= 0 ? C.good : SEVERITY.critical.color, align: 'center', width: cardW });

    // Narrative + KPIs
    const x = M + cardW + 18;
    const w = CW - cardW - 18;
    const used = doc.paragraph(executiveSummaryText(report), x, top + 2, { width: w, size: 9.8, color: C.body, lineHeight: 1.5 });
    const kpis = [
      { label: 'Critical', value: risk.counts.critical, color: SEVERITY.critical.color },
      { label: 'High', value: risk.counts.high, color: SEVERITY.high.color },
      { label: 'Open findings', value: risk.open, color: C.ink },
      { label: 'Coverage', value: `${risk.coverage.monitored}/${risk.coverage.total}`, color: C.brand },
    ];
    const gap = 8;
    const kw = (w - gap * (kpis.length - 1)) / kpis.length;
    const ky = Math.max(top + used + 12, top + cardH - 54);
    kpis.forEach((kpi, i) => {
      const kx = x + i * (kw + gap);
      doc.rect(kx, ky, kw, 54, { fill: C.white, stroke: C.rule, lineWidth: 0.6, radius: 8 });
      doc.text(String(kpi.value), kx, ky + 10, { size: 19, font: 'bold', color: kpi.color, align: 'center', width: kw });
      doc.text(kpi.label.toUpperCase(), kx, ky + 36, { size: 6.8, font: 'bold', color: C.muted, align: 'center', width: kw });
    });
    this.y = Math.max(top + cardH, ky + 54) + 20;

    // Severity distribution
    this.ensure(40);
    doc.text('OPEN FINDINGS BY SEVERITY', M, this.y, { size: 7.5, font: 'bold', color: C.muted });
    const barY = this.y + 14;
    const total = risk.open || 1;
    doc.rect(M, barY, CW, 9, { fill: C.softer, radius: 4.5 });
    let bx = M;
    for (const key of Object.keys(SEVERITY)) {
      const share = (risk.counts[key] / total) * CW;
      if (share > 0) doc.rect(bx, barY, share, 9, { fill: SEVERITY[key].color });
      bx += share;
    }
    let lx = M;
    for (const key of Object.keys(SEVERITY)) {
      const label = `${SEVERITY[key].label} ${risk.counts[key]}`;
      doc.circle(lx + 3, barY + 20, 3, { fill: SEVERITY[key].color });
      doc.text(label, lx + 9, barY + 16, { size: 8, color: C.body });
      lx += doc.measure(label, 8) + 24;
    }
    this.y = barY + 40;
  }

  integrations() {
    const { doc, report } = this;
    this.section('Risk Breakdown by Platform', 'Per-platform score uses the same model as the overall score', 26 + 34 * report.integrations.length);
    const cols = [
      { key: 'name', label: 'Platform', x: 0, w: 168 },
      { key: 'status', label: 'Status', x: 168, w: 82 },
      { key: 'score', label: 'Score', x: 250, w: 92 },
      { key: 'critical', label: 'Critical', x: 342, w: 43, align: 'center' },
      { key: 'high', label: 'High', x: 385, w: 43, align: 'center' },
      { key: 'medium', label: 'Medium', x: 428, w: 43, align: 'center' },
      { key: 'low', label: 'Low', x: 471, w: 44, align: 'center' },
    ];
    doc.rect(M, this.y, CW, 22, { fill: C.softer, radius: 6 });
    for (const col of cols) {
      doc.text(col.label.toUpperCase(), M + col.x + (col.align ? 0 : 10), this.y + 7.5, { size: 7, font: 'bold', color: C.muted, align: col.align ?? 'left', width: col.w });
    }
    this.y += 26;

    for (const row of report.integrations) {
      const rowY = this.y;
      doc.rect(M + 10, rowY + 8, 18, 18, { fill: row.color, radius: 5 });
      doc.text(row.shortName, M + 10, rowY + 13.5, { size: 6.5, font: 'bold', color: C.white, align: 'center', width: 18 });
      doc.text(row.name, M + 36, rowY + 6, { size: 9, font: 'bold', color: row.monitored ? C.ink : C.muted });
      doc.text(row.account ?? 'Not connected', M + 36, rowY + 18, { size: 7.5, color: C.faint });

      const status = row.monitored ? 'Monitored' : row.status === 'paused' ? 'Paused' : 'Not connected';
      const statusColor = row.monitored ? C.good : row.status === 'paused' ? SEVERITY.medium.color : C.faint;
      doc.circle(M + 168 + 13, rowY + 16.5, 2.6, { fill: statusColor });
      doc.text(status, M + 168 + 20, rowY + 12.5, { size: 8.5, color: C.body });

      if (row.monitored && row.score != null) {
        const sc = scoreColor(row.score);
        doc.text(`${row.score}`, M + 250 + 10, rowY + 10.5, { size: 11, font: 'bold', color: sc });
        doc.text(row.grade, M + 250 + 32, rowY + 12.5, { size: 8, font: 'bold', color: C.muted });
        doc.rect(M + 250 + 46, rowY + 15, 38, 4, { fill: C.softer, radius: 2 });
        doc.rect(M + 250 + 46, rowY + 15, Math.max(2, (38 * row.score) / 100), 4, { fill: sc, radius: 2 });
        for (const key of ['critical', 'high', 'medium', 'low']) {
          const col = cols.find((c) => c.key === key);
          const value = row.counts[key];
          doc.text(String(value), M + col.x, rowY + 12, { size: 9.5, font: value ? 'bold' : 'regular', color: value ? SEVERITY[key].color : C.faint, align: 'center', width: col.w });
        }
      } else {
        for (const key of ['score', 'critical', 'high', 'medium', 'low']) {
          const col = cols.find((c) => c.key === key);
          doc.text('–', M + col.x + (col.align ? 0 : 10), rowY + 12, { size: 9, color: C.faint, align: col.align ?? 'left', width: col.w });
        }
      }
      doc.line(M, rowY + 34, M + CW, rowY + 34, { color: C.rule, width: 0.5 });
      this.y += 34;
    }
    this.y += 18;
  }

  categories() {
    const { doc, report } = this;
    const rows = report.risk.byCategory.slice(0, 8);
    if (!rows.length) return;
    const colW = (CW - 24) / 2;
    const rowsPerCol = Math.ceil(rows.length / 2);
    this.section('Risk Concentration by Category', 'Share of total weighted risk', rowsPerCol * 28);
    rows.forEach((row, i) => {
      const col = i < rowsPerCol ? 0 : 1;
      const x = M + col * (colW + 24);
      const y = this.y + (i % rowsPerCol) * 28;
      doc.text(row.category, x, y, { size: 8.5, color: C.body });
      doc.text(`${row.open} open · ${row.share}%`, x, y, { size: 8, color: C.muted, align: 'right', width: colW });
      doc.rect(x, y + 13, colW, 5, { fill: C.softer, radius: 2.5 });
      doc.rect(x, y + 13, Math.max(3, (colW * row.share) / 100), 5, { fill: C.indigo, radius: 2.5 });
    });
    this.y += rowsPerCol * 28 + 12;
  }

  topActions() {
    const { doc, report } = this;
    this.section(`Top ${report.topActions.length || 5} Items Requiring CISO Action`, 'Ranked by severity, exposure, exploitability and age', 110);
    if (!report.topActions.length) {
      doc.text('No open findings on the monitored platforms.', M, this.y, { size: 10, color: C.muted });
      this.y += 30;
      return;
    }
    const textX = M + 44;
    const sideW = 92;
    const textW = CW - 44 - sideW - 14;

    report.topActions.forEach((item, index) => {
      const sev = SEVERITY[item.severity] ?? SEVERITY.low;
      const titleH = doc.paragraphHeight(item.title, { width: textW, size: 10.5, font: 'bold', lineHeight: 1.3 });
      const whyH = doc.paragraphHeight(item.explanation, { width: textW, size: 8.5, lineHeight: 1.45, maxLines: 3 });
      const action = `Action: ${item.remediation?.[0] ?? 'See playbook.'}`;
      const actionH = doc.paragraphHeight(action, { width: textW, size: 8.5, font: 'bold', lineHeight: 1.4, maxLines: 2 });
      const cardH = Math.max(96, 30 + titleH + 6 + whyH + 6 + actionH + 14);
      this.ensure(cardH + 10);
      const y = this.y;

      doc.rect(M, y, CW, cardH, { fill: C.white, stroke: C.rule, lineWidth: 0.7, radius: 9 });
      doc.rect(M, y, 4, cardH, { fill: sev.color });
      doc.circle(M + 24, y + 22, 11, { fill: C.softer });
      doc.text(String(index + 1), M + 13, y + 16.5, { size: 10, font: 'bold', color: C.ink, align: 'center', width: 22 });

      let px = textX;
      px += this.pill(sev.label, px, y + 13, { color: sev.color, tint: sev.tint }) + 6;
      doc.text(`${item.integration.name}  ·  ${item.category}`, px, y + 15, { size: 8, color: C.muted });

      let ty = y + 32;
      ty += doc.paragraph(item.title, textX, ty, { width: textW, size: 10.5, font: 'bold', color: C.ink, lineHeight: 1.3 }) + 6;
      ty += doc.paragraph(item.explanation, textX, ty, { width: textW, size: 8.5, color: C.body, lineHeight: 1.45, maxLines: 3 }) + 6;
      doc.paragraph(action, textX, ty, { width: textW, size: 8.5, font: 'bold', color: C.ink, lineHeight: 1.4, maxLines: 2 });

      // Side column
      const sx = M + CW - sideW - 12;
      doc.rect(sx, y + 12, sideW, cardH - 24, { fill: C.soft, radius: 7 });
      doc.text(`+${item.projectedGain}`, sx, y + 22, { size: 18, font: 'bold', color: C.good, align: 'center', width: sideW });
      doc.text('SCORE IF FIXED', sx, y + 44, { size: 6.5, font: 'bold', color: C.muted, align: 'center', width: sideW });
      doc.text(`~${item.effort ?? '?'} effort`, sx, y + 58, { size: 8, color: C.body, align: 'center', width: sideW });
      const autoText = item.autoFix?.supported ? 'Auto-Fix ready' : 'Manual fix';
      doc.text(autoText, sx, y + 72, { size: 8, font: 'bold', color: item.autoFix?.supported ? C.brand : C.muted, align: 'center', width: sideW });

      this.y += cardH + 10;
    });
    this.y += 8;
  }

  compliance() {
    const { doc, report } = this;
    const panelH = 196;
    this.section('Compliance Posture', 'Readiness across controls assessed on monitored platforms', panelH + 10);
    const frameworks = report.compliance;
    const gap = 16;
    const pw = (CW - gap) / 2;
    frameworks.slice(0, 2).forEach((fw, i) => {
      const x = M + i * (pw + gap);
      const y = this.y;
      doc.rect(x, y, pw, panelH, { fill: C.soft, stroke: C.rule, lineWidth: 0.6, radius: 10 });
      doc.text(fw.name, x + 14, y + 14, { size: 11, font: 'bold', color: C.ink });
      doc.text(fw.fullName, x + 14, y + 29, { size: 7.5, color: C.muted });
      const readiness = fw.readiness ?? 0;
      const color = scoreColor(readiness);
      doc.text(fw.readiness == null ? 'n/a' : `${readiness}%`, x + 14, y + 44, { size: 26, font: 'bold', color });
      doc.text('READY', x + 14 + doc.measure(`${readiness}%`, 26, 'bold') + 6, y + 58, { size: 7, font: 'bold', color: C.muted });
      doc.rect(x + 14, y + 80, pw - 28, 6, { fill: '#e2e8f0', radius: 3 });
      doc.rect(x + 14, y + 80, Math.max(3, ((pw - 28) * readiness) / 100), 6, { fill: color, radius: 3 });
      doc.text(`${fw.passing} passing · ${fw.partial} partial · ${fw.failing} failing of ${fw.assessed} controls`, x + 14, y + 92, { size: 7.5, color: C.body });

      doc.text('LARGEST GAPS', x + 14, y + 112, { size: 6.8, font: 'bold', color: C.muted });
      let gy = y + 126;
      for (const gap of fw.topGaps.slice(0, 4)) {
        const failing = gap.status === 'failing';
        doc.circle(x + 18, gy + 4.5, 2.4, { fill: failing ? SEVERITY.critical.color : SEVERITY.medium.color });
        doc.text(gap.id, x + 25, gy, { size: 8, font: 'bold', color: C.ink });
        const nameX = x + 25 + 40;
        doc.paragraph(gap.name, nameX, gy, { width: pw - 14 - (nameX - x) - 4, size: 7.8, color: C.body, maxLines: 1 });
        gy += 15;
      }
      if (!fw.topGaps.length) doc.text('No open gaps.', x + 14, gy, { size: 8, color: C.good });
    });
    this.y += panelH + 12;
    doc.paragraph(
      'Readiness is the mean control score across controls evidenced by the checks Veyra runs on monitored platforms. ' +
      'A check counts fully when it passes, half when only medium or low findings are open, and zero when a critical or high finding is open. ' +
      'It indicates audit preparedness and is not a substitute for an independent audit.',
      M, this.y, { width: CW, size: 7.5, color: C.muted, lineHeight: 1.45 },
    );
    this.y += 52;
  }

  footers() {
    const { doc, report } = this;
    const total = doc.pageCount;
    for (let i = 0; i < total; i++) {
      doc.usePage(i);
      doc.line(M, FOOTER_Y, M + CW, FOOTER_Y, { color: C.rule, width: 0.6 });
      doc.text(`Veyra Security Brain  ·  ${report.tenant}  ·  Confidential`, M, FOOTER_Y + 8, { size: 7.5, color: C.faint });
      doc.text(`Page ${i + 1} of ${total}`, M, FOOTER_Y + 8, { size: 7.5, color: C.faint, align: 'right', width: CW });
    }
  }

  render() {
    this.cover();
    this.summary();
    this.integrations();
    this.doc.addPage();
    this.continuationHeader();
    this.topActions();
    this.compliance();
    this.categories();
    this.footers();
    return this.doc.toBuffer();
  }
}

/** @param {ReturnType<import('../brain.js').SecurityBrain['executiveReport']>} report */
export function renderExecutiveReport(report) {
  return new ReportWriter(report).render();
}

export function reportFilename(report) {
  return `veyra-executive-report-${report.generatedAt.slice(0, 10)}.pdf`;
}
