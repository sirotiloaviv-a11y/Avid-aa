const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

// Wraps symbols, prices and percentages so they keep left-to-right order
// inside right-to-left Hebrew text.
export function ltr(text, cls = '') {
  return `<bdi dir="ltr" class="ltr ${cls}">${esc(text)}</bdi>`;
}

export function trendClass(value) {
  if (value > 0) return 'up';
  if (value < 0) return 'down';
  return 'flat';
}

export function qs(root, selector) {
  return root.querySelector(selector);
}

export function qsa(root, selector) {
  return [...root.querySelectorAll(selector)];
}
