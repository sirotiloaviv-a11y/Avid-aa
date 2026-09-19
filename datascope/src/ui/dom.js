/**
 * DOM helpers.
 *
 * Every helper here sets text through `textContent`. Nothing in this app assigns
 * `innerHTML`, and imported CSV text reaches the screen only through these
 * functions - which is the whole reason they exist. A symbol named
 * `<img onerror=...>` is then just an odd-looking label.
 *
 * No module in ui/ touches the DOM at import time; all of it happens inside
 * these functions, so the modules can be imported in Node (the build script does
 * exactly that to verify they load).
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * @param {string} tag
 * @param {{class?: string, text?: string, attrs?: Record<string, string|number|null>,
 *   children?: (Node|null)[]}} [options]
 * @returns {HTMLElement}
 */
export function el(tag, options = {}) {
  const node = document.createElement(tag);
  if (options.class) node.className = options.class;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      if (value === null || value === undefined) continue;
      node.setAttribute(name, String(value));
    }
  }
  if (options.children) {
    for (const child of options.children) if (child) node.append(child);
  }
  return node;
}

/**
 * A number, date or symbol rendered LTR inside the RTL page. Uses an isolating
 * element rather than bidi control characters, so nothing invisible can end up
 * in an export.
 * @param {string|number} value
 * @param {string} [className]
 */
export function num(value, className = '') {
  return el('span', {
    class: className ? `num ${className}` : 'num',
    text: String(value),
    attrs: { dir: 'ltr' },
  });
}

/** @param {string} tag @param {Record<string, string|number>} [attrs] */
export function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    node.setAttribute(name, String(value));
  }
  return node;
}

/** @param {SVGElement} node @param {string} text */
export function svgText(node, text) {
  node.textContent = String(text);
  return node;
}

/** @param {Element} node */
export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/**
 * @param {Element|null} node
 * @param {boolean} visible
 */
export function show(node, visible) {
  if (!node) return;
  node.hidden = !visible;
}

/**
 * @param {string} id
 * @returns {HTMLElement}
 */
export function byId(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing required element #${id}`);
  return node;
}

/**
 * Triggers a client-side download. The data never leaves the browser: it is put
 * into a blob URL, handed to a synthetic click, and revoked immediately after.
 * @param {string} fileName
 * @param {string} content
 * @param {string} mimeType
 */
export function downloadText(fileName, content, mimeType) {
  // The BOM makes Hebrew text and UTF-8 CSV open correctly in spreadsheet apps
  // that still guess the encoding from the first bytes.
  const blob = new Blob([`﻿${content}`], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = el('a', { attrs: { href: url, download: fileName } });
  link.style.display = 'none';
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
