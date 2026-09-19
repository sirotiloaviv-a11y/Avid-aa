/**
 * The scrolling ticker bar of market movers.
 *
 * The strip is rendered twice, end to end, and the animation translates by
 * exactly half its width - which is what makes the loop seamless rather than
 * snapping back at the end. The duplicate is hidden from assistive technology so
 * a screen reader hears each mover once.
 *
 * Motion here is decoration, not information: the same figures are in the cards
 * and the table. `prefers-reduced-motion` stops the animation entirely (the CSS
 * does that) and the bar becomes an ordinary horizontally scrollable strip.
 */

import { clear, el, num } from './dom.js';
import { icon } from './icons.js';
import { formatPercent, formatPrice } from '../lib/format.js';

/**
 * @param {HTMLElement} container The element with the marquee animation.
 * @param {{asset: any, quote: any}[]} movers Already ranked.
 * @param {{onSelect?: (key: string) => void}} [options]
 */
export function renderTicker(container, movers, options = {}) {
  clear(container);

  if (movers.length === 0) {
    container.append(el('span', { class: 'ticker-empty', text: 'ממתין לנתוני שוק…' }));
    container.classList.remove('is-scrolling');
    return;
  }

  const strip = buildStrip(movers, options, false);
  container.append(strip);
  // The second copy carries the animation across the seam.
  container.append(buildStrip(movers, options, true));
  container.classList.add('is-scrolling');
}

function buildStrip(movers, options, isDuplicate) {
  const strip = el('div', { class: 'ticker-strip' });
  if (isDuplicate) strip.setAttribute('aria-hidden', 'true');

  for (const { asset, quote } of movers) {
    const direction =
      quote.changePct > 0 ? 'up' : quote.changePct < 0 ? 'down' : 'flat';

    const item = el('button', {
      class: `ticker-item dir-${direction}`,
      attrs: {
        type: 'button',
        // The duplicate must not be a second tab stop for the same thing.
        tabindex: isDuplicate ? '-1' : '0',
        title: asset.name ? `${asset.name} / ${asset.displaySymbol}` : asset.displaySymbol,
      },
    });

    item.append(el('span', { class: 'ticker-symbol', text: asset.displaySymbol, attrs: { dir: 'ltr' } }));
    item.append(num(formatPrice(quote.price), 'ticker-price'));
    const arrow = el('span', { class: 'ticker-arrow', attrs: { 'aria-hidden': 'true' } });
    arrow.append(
      icon(direction === 'up' ? 'trending-up' : direction === 'down' ? 'trending-down' : 'minus', {
        size: 12,
      }),
    );
    item.append(arrow);
    item.append(num(formatPercent(quote.changePct), 'ticker-change'));

    if (options.onSelect) {
      item.addEventListener('click', () => options.onSelect(asset.key));
    }
    strip.append(item);
  }

  return strip;
}
