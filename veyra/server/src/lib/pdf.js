import { deflateSync } from 'node:zlib';

// Minimal, dependency-free PDF 1.4 writer: vector shapes, arcs and text in
// the standard Helvetica fonts (no embedding needed), WinAnsi encoding and
// deflate-compressed content streams. The API uses a top-left origin in
// points, like a canvas; conversion to PDF's bottom-left origin is internal.

// Advance widths (1/1000 em) for ASCII 32..126, from the Adobe Core 14 AFM files.
const HELVETICA = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
  556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
  1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
  667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
  333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
  556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
];
const HELVETICA_BOLD = [
  278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
  556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
  975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
  667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
  333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
  611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
];

// Unicode -> WinAnsiEncoding byte for characters outside Latin-1 that we use.
const WIN_ANSI = {
  '€': 0x80, '‚': 0x82, '„': 0x84, '…': 0x85, '†': 0x86, '‡': 0x87, '‰': 0x89,
  '‘': 0x91, '’': 0x92, '“': 0x93, '”': 0x94, '•': 0x95, '–': 0x96, '—': 0x97, '™': 0x99,
};
const SPECIAL_WIDTH = {
  0x80: 556, 0x82: 222, 0x84: 333, 0x85: 1000, 0x86: 556, 0x87: 556, 0x89: 1000,
  0x91: 222, 0x92: 222, 0x93: 333, 0x94: 333, 0x95: 350, 0x96: 556, 0x97: 1000, 0x99: 1000,
  0xa0: 278, 0xb7: 278, 0xd7: 584, 0xb0: 400,
};
// Characters with no WinAnsi glyph are transliterated.
const TRANSLITERATE = { '→': '->', '←': '<-', '≥': '>=', '≤': '<=', '✓': 'v', '✗': 'x', '−': '-', ' ': ' ', ' ': ' ' };

const FONTS = { regular: { key: 'F1', base: 'Helvetica', widths: HELVETICA }, bold: { key: 'F2', base: 'Helvetica-Bold', widths: HELVETICA_BOLD } };

/** Encode a JS string to WinAnsi bytes (array of numbers). */
export function encodeWinAnsi(text) {
  const bytes = [];
  for (const char of String(text ?? '').normalize('NFC')) {
    const mapped = TRANSLITERATE[char];
    if (mapped) {
      for (const c of mapped) bytes.push(c.charCodeAt(0));
      continue;
    }
    const code = char.codePointAt(0);
    if (code === 0x09) bytes.push(0x20);
    else if (code >= 0x20 && code <= 0x7e) bytes.push(code);
    else if (WIN_ANSI[char]) bytes.push(WIN_ANSI[char]);
    else if (code >= 0xa0 && code <= 0xff) bytes.push(code);
    else if (code >= 0x20) bytes.push(0x3f); // '?'
  }
  return bytes;
}

function charWidth(byte, widths) {
  if (byte >= 32 && byte <= 126) return widths[byte - 32];
  return SPECIAL_WIDTH[byte] ?? 556;
}

/** PDF literal string body (escaped), as a latin1 JS string. */
function literal(bytes) {
  let out = '';
  for (const b of bytes) {
    if (b === 0x28 || b === 0x29 || b === 0x5c) out += `\\${String.fromCharCode(b)}`;
    else if (b < 0x20 || b > 0x7e) out += `\\${b.toString(8).padStart(3, '0')}`;
    else out += String.fromCharCode(b);
  }
  return out;
}

const num = (n) => (Math.round(n * 100) / 100).toString();

function rgb(hex) {
  const h = String(hex).replace('#', '');
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h.padEnd(6, '0');
  return [0, 2, 4].map((i) => num(parseInt(full.slice(i, i + 2), 16) / 255)).join(' ');
}

export class PdfDocument {
  constructor({ width = 595.28, height = 841.89, info = {} } = {}) {
    this.width = width;
    this.height = height;
    this.info = info;
    this.pages = [];
    this.current = null;
    this.addPage();
  }

  addPage() {
    this.current = { ops: [] };
    this.pages.push(this.current);
    return this.pages.length - 1;
  }

  usePage(index) {
    this.current = this.pages[index];
  }

  get pageCount() {
    return this.pages.length;
  }

  #op(line) {
    this.current.ops.push(line);
  }

  #y(y) {
    return this.height - y;
  }

  // ------------------------------------------------------------------ text

  measure(text, size = 10, font = 'regular') {
    const widths = (FONTS[font] ?? FONTS.regular).widths;
    return (encodeWinAnsi(text).reduce((sum, b) => sum + charWidth(b, widths), 0) * size) / 1000;
  }

  /** Greedy word wrap; words longer than the line are broken. */
  wrap(text, width, size = 10, font = 'regular') {
    const lines = [];
    for (const paragraph of String(text ?? '').split('\n')) {
      let line = '';
      for (const word of paragraph.split(/\s+/).filter(Boolean)) {
        const candidate = line ? `${line} ${word}` : word;
        if (this.measure(candidate, size, font) <= width) {
          line = candidate;
          continue;
        }
        if (line) lines.push(line);
        let rest = word;
        while (this.measure(rest, size, font) > width && rest.length > 1) {
          let cut = rest.length - 1;
          while (cut > 1 && this.measure(rest.slice(0, cut), size, font) > width) cut--;
          lines.push(rest.slice(0, cut));
          rest = rest.slice(cut);
        }
        line = rest;
      }
      lines.push(line);
    }
    return lines;
  }

  /**
   * Draw a single line of text. `y` is the top of the line box.
   * align: left | center | right (center/right need `width`).
   */
  text(value, x, y, { size = 10, font = 'regular', color = '#000000', align = 'left', width = 0 } = {}) {
    const bytes = encodeWinAnsi(value);
    if (!bytes.length) return;
    const w = this.measure(value, size, font);
    let tx = x;
    if (align === 'center') tx = x + (width - w) / 2;
    if (align === 'right') tx = x + width - w;
    const baseline = this.#y(y + size * 0.78);
    const f = (FONTS[font] ?? FONTS.regular).key;
    this.#op(`BT /${f} ${num(size)} Tf ${rgb(color)} rg ${num(tx)} ${num(baseline)} Td (${literal(bytes)}) Tj ET`);
  }

  /** Wrapped text block; returns the height used. */
  paragraph(value, x, y, { width, size = 10, font = 'regular', color = '#000000', lineHeight = 1.4, maxLines = Infinity, align = 'left' } = {}) {
    let lines = this.wrap(value, width, size, font);
    if (lines.length > maxLines) {
      lines = lines.slice(0, maxLines);
      let last = lines[maxLines - 1];
      while (last && this.measure(`${last}…`, size, font) > width) last = last.slice(0, -1);
      lines[maxLines - 1] = `${last.trimEnd()}…`;
    }
    lines.forEach((line, i) => this.text(line, x, y + i * size * lineHeight, { size, font, color, align, width }));
    return lines.length * size * lineHeight;
  }

  paragraphHeight(value, { width, size = 10, font = 'regular', lineHeight = 1.4, maxLines = Infinity } = {}) {
    return Math.min(this.wrap(value, width, size, font).length, maxLines) * size * lineHeight;
  }

  // ---------------------------------------------------------------- shapes

  #paint({ fill, stroke, lineWidth = 1 }) {
    const parts = [];
    if (fill) parts.push(`${rgb(fill)} rg`);
    if (stroke) parts.push(`${rgb(stroke)} RG ${num(lineWidth)} w`);
    return { prefix: parts.join(' '), op: fill && stroke ? 'B' : fill ? 'f' : 'S' };
  }

  rect(x, y, w, h, { fill, stroke, lineWidth, radius = 0 } = {}) {
    if (!fill && !stroke) return;
    const { prefix, op } = this.#paint({ fill, stroke, lineWidth });
    const r = Math.max(0, Math.min(radius, w / 2, h / 2));
    if (!r) {
      this.#op(`q ${prefix} ${num(x)} ${num(this.#y(y + h))} ${num(w)} ${num(h)} re ${op} Q`);
      return;
    }
    const k = r * 0.5523;
    const [l, t, rt, b] = [x, this.#y(y), x + w, this.#y(y + h)];
    this.#op([
      `q ${prefix}`,
      `${num(l + r)} ${num(t)} m`,
      `${num(rt - r)} ${num(t)} l`,
      `${num(rt - r + k)} ${num(t)} ${num(rt)} ${num(t - r + k)} ${num(rt)} ${num(t - r)} c`,
      `${num(rt)} ${num(b + r)} l`,
      `${num(rt)} ${num(b + r - k)} ${num(rt - r + k)} ${num(b)} ${num(rt - r)} ${num(b)} c`,
      `${num(l + r)} ${num(b)} l`,
      `${num(l + r - k)} ${num(b)} ${num(l)} ${num(b + r - k)} ${num(l)} ${num(b + r)} c`,
      `${num(l)} ${num(t - r)} l`,
      `${num(l)} ${num(t - r + k)} ${num(l + r - k)} ${num(t)} ${num(l + r)} ${num(t)} c`,
      `h ${op} Q`,
    ].join(' '));
  }

  line(x1, y1, x2, y2, { color = '#000000', width = 1, dash } = {}) {
    const d = dash ? `[${dash.join(' ')}] 0 d ` : '';
    this.#op(`q ${rgb(color)} RG ${num(width)} w ${d}${num(x1)} ${num(this.#y(y1))} m ${num(x2)} ${num(this.#y(y2))} l S Q`);
  }

  circle(cx, cy, r, { fill, stroke, lineWidth } = {}) {
    this.rect(cx - r, cy - r, r * 2, r * 2, { fill, stroke, lineWidth, radius: r });
  }

  /**
   * Stroke an arc. Angles in degrees, clockwise from 12 o'clock.
   */
  arc(cx, cy, r, startDeg, endDeg, { color = '#000000', width = 1, cap = 'round' } = {}) {
    if (endDeg <= startDeg) return;
    const rad = (d) => (d * Math.PI) / 180;
    const point = (a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
    const segments = Math.ceil((endDeg - startDeg) / 90);
    const step = (endDeg - startDeg) / segments;
    const [sx, sy] = point(rad(startDeg));
    const path = [`${num(sx)} ${num(this.#y(sy))} m`];
    for (let i = 0; i < segments; i++) {
      const a1 = rad(startDeg + i * step);
      const a2 = rad(startDeg + (i + 1) * step);
      const k = (4 / 3) * Math.tan((a2 - a1) / 4) * r;
      const [x0, y0] = point(a1);
      const [x3, y3] = point(a2);
      const c1 = [x0 + k * Math.cos(a1), y0 + k * Math.sin(a1)];
      const c2 = [x3 - k * Math.cos(a2), y3 - k * Math.sin(a2)];
      path.push(`${num(c1[0])} ${num(this.#y(c1[1]))} ${num(c2[0])} ${num(this.#y(c2[1]))} ${num(x3)} ${num(this.#y(y3))} c`);
    }
    const capStyle = cap === 'round' ? 1 : 0;
    this.#op(`q ${rgb(color)} RG ${num(width)} w ${capStyle} J ${path.join(' ')} S Q`);
  }

  // ---------------------------------------------------------------- output

  toBuffer() {
    const chunks = [];
    const offsets = [];
    let length = 0;
    const push = (data) => {
      const buf = Buffer.isBuffer(data) ? data : Buffer.from(data, 'latin1');
      chunks.push(buf);
      length += buf.length;
    };
    const object = (id, body) => {
      offsets[id] = length;
      push(`${id} 0 obj\n`);
      for (const part of [].concat(body)) push(part);
      push('\nendobj\n');
    };

    const pageIds = this.pages.map((_, i) => 6 + i * 2);
    push('%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');
    object(1, '<< /Type /Catalog /Pages 2 0 R >>');
    object(2, `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageIds.length} >>`);
    object(3, `<< /Type /Font /Subtype /Type1 /BaseFont /${FONTS.regular.base} /Encoding /WinAnsiEncoding >>`);
    object(4, `<< /Type /Font /Subtype /Type1 /BaseFont /${FONTS.bold.base} /Encoding /WinAnsiEncoding >>`);

    const infoEntries = Object.entries({ Producer: 'Veyra Security Brain', ...this.info })
      .map(([key, value]) => `/${key} (${literal(encodeWinAnsi(value))})`);
    const created = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const stamp = `D:${created.getUTCFullYear()}${pad(created.getUTCMonth() + 1)}${pad(created.getUTCDate())}${pad(created.getUTCHours())}${pad(created.getUTCMinutes())}${pad(created.getUTCSeconds())}Z`;
    object(5, `<< ${infoEntries.join(' ')} /CreationDate (${stamp}) >>`);

    this.pages.forEach((page, i) => {
      const pageId = pageIds[i];
      const contentId = pageId + 1;
      object(pageId, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(this.width)} ${num(this.height)}] ` +
        `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentId} 0 R >>`);
      const stream = deflateSync(Buffer.from(page.ops.join('\n'), 'latin1'));
      object(contentId, [`<< /Length ${stream.length} /Filter /FlateDecode >>\nstream\n`, stream, '\nendstream']);
    });

    const size = 6 + this.pages.length * 2;
    const xrefOffset = length;
    let xref = `xref\n0 ${size}\n0000000000 65535 f \n`;
    for (let id = 1; id < size; id++) xref += `${String(offsets[id]).padStart(10, '0')} 00000 n \n`;
    push(xref);
    push(`trailer\n<< /Size ${size} /Root 1 0 R /Info 5 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`);
    return Buffer.concat(chunks);
  }
}
