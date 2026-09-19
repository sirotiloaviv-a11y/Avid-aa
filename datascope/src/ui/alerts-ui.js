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
import { formatClock, formatDateTime, formatPrice } from '../lib/format.js';
import { describeRule, RULE_TYPE_LABELS } from '../lib/alerts.js';

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
    head.append(el('span', { class: 'rule-type', text: RULE_TYPE_LABELS[rule.type] ?? rule.type }));
    item.append(head);

    item.append(el('p', { class: 'rule-description', text: describeRule(rule) }));
    if (rule.note) item.append(el('p', { class: 'rule-note', text: rule.note }));

    const meta = el('div', { class: 'rule-meta' });
    meta.append(
      el('span', {
        text:
          rule.triggerCount === 0
            ? 'טרם הופעלה'
            : `הופעלה ${rule.triggerCount} פעמים · אחרונה ${formatClock(rule.lastTriggeredAt)}`,
      }),
    );
    if (!rule.armed && rule.enabled) {
      // Explains why a rule whose condition still holds is quiet.
      meta.append(el('span', { class: 'rule-state', text: 'ממתינה לאיפוס התנאי' }));
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
      text: 'מחיקה',
      attrs: { type: 'button' },
    });
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
 */
export function renderHistory(container, entries) {
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

    const head = el('div', { class: 'history-head' });
    head.append(el('time', { class: 'history-time', text: formatClock(entry.ts), attrs: { datetime: new Date(entry.ts).toISOString(), title: formatDateTime(entry.ts) } }));
    // The same "Name / SYMBOL" label the notification used.
    head.append(el('span', { class: 'history-asset', text: entry.title, attrs: { dir: 'auto' } }));
    head.append(el('span', { class: 'history-type', text: RULE_TYPE_LABELS[entry.type] ?? entry.type }));
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
