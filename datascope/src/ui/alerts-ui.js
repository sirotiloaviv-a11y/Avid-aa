/**
 * The alerts panel: active rules, and the history of everything that fired.
 *
 * Two details are deliberate.
 *
 * A rule that cannot currently be evaluated says so on its own row. A rule
 * silently doing nothing because its window is longer than the history the page
 * has collected is the failure mode that makes people distrust an alerting tool,
 * so the engine's diagnostic is shown rather than swallowed.
 *
 * Every history row repeats the full name and the symbol, matching the
 * notification text, so a row read hours later still identifies the asset
 * without the reader having to remember what the ticker was.
 */

import { clear, el, num } from './dom.js';
import { icon } from './icons.js';
import { formatClock, formatDateTime, formatPrice } from '../lib/format.js';
import { describeRule, RULE_TYPE_LABELS } from '../lib/alerts.js';

/** The icon that stands for each rule type, in the list and in the history. */
const TYPE_ICON = { price: 'target', percent: 'percent', volume: 'bar-chart' };

/**
 * Hebrew counts one, two and many differently, so "1 פעמים" reads as broken
 * text rather than as a number.
 * @param {number} count
 */
function formatTimes(count) {
  if (count === 1) return 'פעם אחת';
  if (count === 2) return 'פעמיים';
  return `${count} פעמים`;
}

/**
 * @param {HTMLElement} container
 * @param {import('../lib/alerts.js').AlertRule[]} rules
 * @param {{
 *   assetFor: (key: string) => any,
 *   diagnostics: Record<string, string|null>,
 *   onToggle: (id: string, enabled: boolean) => void,
 *   onDelete: (id: string) => void,
 * }} options
 */
export function renderRules(container, rules, options) {
  clear(container);

  if (rules.length === 0) {
    container.append(
      el('p', {
        class: 'empty-note',
        text: 'לא הוגדרו התראות. יש לבחור נכס, סוג התראה וערך סף, וללחוץ «הוספת התראה».',
      }),
    );
    return;
  }

  const list = el('ul', { class: 'rule-list' });

  for (const rule of rules) {
    const asset = options.assetFor(rule.assetKey);
    const item = el('li', { class: `rule-item${rule.enabled ? '' : ' is-disabled'}` });

    const head = el('div', { class: 'rule-head' });
    head.append(
      el('span', {
        class: 'rule-symbol',
        text: asset?.displaySymbol ?? rule.assetKey,
        attrs: { dir: 'ltr' },
      }),
    );
    if (asset?.name) head.append(el('span', { class: 'rule-name', text: asset.name }));
    const typeBadge = el('span', { class: 'badge badge-muted rule-type' });
    typeBadge.append(icon(TYPE_ICON[rule.type] ?? 'bell', { size: 11 }));
    typeBadge.append(el('span', { text: RULE_TYPE_LABELS[rule.type] ?? rule.type }));
    head.append(typeBadge);
    item.append(head);

    item.append(el('p', { class: 'rule-description', text: describeRule(rule) }));
    if (rule.note) item.append(el('p', { class: 'rule-note', text: rule.note }));

    const meta = el('div', { class: 'rule-meta' });
    meta.append(
      el('span', {
        text:
          rule.triggerCount === 0
            ? 'טרם הופעלה'
            : `הופעלה ${formatTimes(rule.triggerCount)} · אחרונה ${formatClock(rule.lastTriggeredAt)}`,
      }),
    );
    if (!rule.armed && rule.enabled) {
      // Explains why a rule whose condition still holds is quiet.
      meta.append(el('span', { class: 'rule-state', text: 'ממתינה לאיפוס התנאי' }));
    }
    if (rule.enabled && rule.armed) {
      const live = el('span', { class: 'badge badge-up' });
      live.append(el('span', { text: 'דרוכה' }));
      meta.append(live);
    }
    const diagnostic = options.diagnostics?.[rule.id];
    if (diagnostic) meta.append(el('span', { class: 'rule-diagnostic', text: diagnostic }));
    item.append(meta);

    const actions = el('div', { class: 'rule-actions' });

    const toggleId = `rule-toggle-${rule.id}`;
    const toggleWrap = el('label', { class: 'switch', attrs: { for: toggleId } });
    const toggle = el('input', {
      attrs: { type: 'checkbox', id: toggleId, ...(rule.enabled ? { checked: 'checked' } : {}) },
    });
    toggle.addEventListener('change', (event) => options.onToggle(rule.id, event.target.checked));
    toggleWrap.append(toggle);
    toggleWrap.append(el('span', { text: rule.enabled ? 'פעילה' : 'מושבתת' }));
    actions.append(toggleWrap);

    const remove = el('button', {
      class: 'button button-quiet button-small',
      attrs: { type: 'button' },
    });
    remove.append(icon('trash', { size: 12 }));
    remove.append(el('span', { text: 'מחיקה' }));
    remove.addEventListener('click', () => options.onDelete(rule.id));
    actions.append(remove);

    item.append(actions);
    list.append(item);
  }

  container.append(list);
}

/**
 * @param {HTMLElement} container
 * @param {import('../lib/alerts.js').AlertEvent[]} entries Newest first.
 * @param {{newIds?: Set<string>}} [options] Ids that just fired; those rows get
 *   the arrival glow exactly once.
 */
export function renderHistory(container, entries, options = {}) {
  clear(container);

  if (entries.length === 0) {
    container.append(
      el('p', { class: 'empty-note', text: 'עדיין לא הופעלה אף התראה בהפעלה הנוכחית.' }),
    );
    return;
  }

  const list = el('ol', { class: 'history-list' });

  for (const entry of entries) {
    const item = el('li', { class: `history-item type-${entry.type}` });
    if (options.newIds?.has(entry.id)) item.classList.add('is-new');

    const head = el('div', { class: 'history-head' });
    head.append(el('time', { class: 'history-time', text: formatClock(entry.ts), attrs: { datetime: new Date(entry.ts).toISOString(), title: formatDateTime(entry.ts) } }));
    // The same "Name / SYMBOL" label the notification used.
    head.append(el('span', { class: 'history-asset', text: entry.title, attrs: { dir: 'auto' } }));
    const typeBadge = el('span', { class: 'badge badge-muted history-type' });
    typeBadge.append(icon(TYPE_ICON[entry.type] ?? 'bell', { size: 11 }));
    typeBadge.append(el('span', { text: RULE_TYPE_LABELS[entry.type] ?? entry.type }));
    head.append(typeBadge);
    item.append(head);

    item.append(el('p', { class: 'history-body', text: entry.body }));

    const meta = el('div', { class: 'history-meta' });
    meta.append(el('span', { text: entry.ruleLabel }));
    if (entry.price !== null) {
      const price = el('span', {});
      price.append(document.createTextNode('מחיר בעת ההפעלה: '));
      price.append(num(formatPrice(entry.price)));
      meta.append(price);
    }
    item.append(meta);

    list.append(item);
  }

  container.append(list);
}

/**
 * Fills the rule form's asset selector from the watchlist.
 * @param {HTMLSelectElement} select
 * @param {any[]} assets
 * @param {string|null} selectedKey
 */
export function fillAssetOptions(select, assets, selectedKey) {
  clear(select);
  for (const asset of assets) {
    const label = asset.name ? `${asset.displaySymbol} — ${asset.name}` : asset.displaySymbol;
    select.append(el('option', { text: label, attrs: { value: asset.key } }));
  }
  if (selectedKey && assets.some((asset) => asset.key === selectedKey)) {
    select.value = selectedKey;
  }
}

/**
 * Shows field errors from validateRule() next to the fields they belong to.
 * @param {HTMLElement} form
 * @param {Record<string, string>} errors
 */
export function showRuleErrors(form, errors) {
  for (const node of form.querySelectorAll('[data-error-for]')) {
    const field = node.getAttribute('data-error-for');
    const message = errors[field] ?? '';
    node.textContent = message;
    node.hidden = message === '';
    const input = form.querySelector(`[name="${field}"]`);
    if (input) {
      if (message) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    }
  }
}
