// Colour selection, demo cart and cart drawer. No commerce backend is
// connected, so checkout only explains that — it never reports success.
import { COLORS, PRICE, CURRENCY } from './brand.js';

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: CURRENCY, maximumFractionDigits: 0 });
const MAX_QTY = 10;

// localStorage can be missing or throw (private mode, blocked storage).
const storage = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v == null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* not persisted */ }
  },
};

const byId = (id) => COLORS.find((c) => c.id === id);

export function initShop({ onColor }) {
  let colorId = byId(storage.get('drip-color', 'onyx'))?.id || 'onyx';
  let qty = 1;
  let cart = storage.get('drip-cart', []).filter((i) => byId(i.id) && Number.isInteger(i.qty) && i.qty > 0);

  // ── Colour ──
  for (const fs of $$('[data-swatches]')) {
    const group = fs.dataset.swatches;
    for (const c of COLORS) {
      const label = document.createElement('label');
      label.className = 'swatch';
      label.title = c.name;
      label.innerHTML = `<input type="radio" name="color-${group}" value="${c.id}"><span class="swatch-dot" style="--c:${c.body}"></span><span class="sr-only">${c.name}</span>`;
      fs.append(label);
    }
    fs.addEventListener('change', (e) => {
      if (e.target.name?.startsWith('color-')) setColor(e.target.value);
    });
  }
  $$('[data-color-list]').forEach((el) => { el.textContent = COLORS.map((c) => c.name).join(', '); });
  $$('[data-price]').forEach((el) => { el.textContent = money.format(PRICE); });

  function setColor(id, initial = false) {
    const c = byId(id);
    if (!c) return;
    colorId = id;
    storage.set('drip-color', id);
    const root = document.documentElement.style;
    root.setProperty('--bottle', c.body);
    root.setProperty('--ink-on-bottle', c.ink);
    $$('[data-color-name]').forEach((el) => { el.textContent = c.name; });
    $$(`input[value="${id}"][name^="color-"]`).forEach((el) => { el.checked = true; });
    onColor?.(c, initial);
  }

  // ── Quantity (details section) ──
  const qtyOut = $('[data-qty]');
  const totalOut = $('[data-price-total]');
  function setQty(n) {
    qty = Math.min(MAX_QTY, Math.max(1, n));
    qtyOut.textContent = qty;
    totalOut.textContent = money.format(qty * PRICE);
  }
  $('[data-qty-dec]').addEventListener('click', () => setQty(qty - 1));
  $('[data-qty-inc]').addEventListener('click', () => setQty(qty + 1));

  // ── Cart ──
  const drawer = $('[data-cart]');
  const scrim = $('[data-scrim]');
  const list = $('[data-cart-items]');
  const empty = $('[data-cart-empty]');
  const foot = $('[data-cart-foot]');
  const notice = $('[data-checkout-notice]');
  let lastFocus = null;
  let closeTimer = 0;

  function save() { storage.set('drip-cart', cart); }

  function add(id, n) {
    const line = cart.find((i) => i.id === id);
    if (line) line.qty = Math.min(MAX_QTY, line.qty + n);
    else cart.push({ id, qty: Math.min(MAX_QTY, n) });
    save();
    renderCart();
  }

  function renderCart() {
    const count = cart.reduce((s, i) => s + i.qty, 0);
    $$('[data-cart-count]').forEach((el) => { el.textContent = count; });
    list.replaceChildren(...cart.map((item) => {
      const c = byId(item.id);
      const li = document.createElement('li');
      li.className = 'cart-item';
      li.innerHTML = `
        <span class="cart-thumb"><svg viewBox="0 0 310 1000" aria-hidden="true" style="--bottle:${c.body};--ink-on-bottle:${c.ink}"><use href="#bottle-flat"/></svg></span>
        <div>
          <p class="cart-name">DRIP Bottle</p>
          <p class="cart-sub">${c.name}</p>
          <div class="cart-controls">
            <div class="qty" role="group" aria-label="Quantity for ${c.name}">
              <button type="button" data-act="dec" aria-label="Decrease">−</button>
              <output>${item.qty}</output>
              <button type="button" data-act="inc" aria-label="Increase">+</button>
            </div>
            <button type="button" class="cart-remove" data-act="remove">Remove</button>
          </div>
        </div>
        <span class="cart-price">${money.format(item.qty * PRICE)}</span>`;
      li.dataset.id = item.id;
      return li;
    }));
    const hasItems = cart.length > 0;
    empty.hidden = hasItems;
    foot.hidden = !hasItems;
    notice.hidden = true;
    $('[data-cart-subtotal]').textContent = money.format(cart.reduce((s, i) => s + i.qty * PRICE, 0));
  }

  list.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.closest('.cart-item').dataset.id;
    const line = cart.find((i) => i.id === id);
    const act = btn.dataset.act;
    if (act === 'inc') line.qty = Math.min(MAX_QTY, line.qty + 1);
    if (act === 'dec') line.qty -= 1;
    if (act === 'remove' || line.qty < 1) cart = cart.filter((i) => i.id !== id);
    save();
    renderCart();
    // Keep keyboard focus inside the drawer after the list re-renders.
    const again = list.querySelector(`[data-id="${id}"] [data-act="${act}"]`);
    (again || $('[data-cart-close]')).focus();
  });

  $('[data-checkout]').addEventListener('click', () => { notice.hidden = false; });

  function openCart() {
    clearTimeout(closeTimer);
    lastFocus = document.activeElement;
    drawer.hidden = false;
    scrim.hidden = false;
    requestAnimationFrame(() => requestAnimationFrame(() => document.documentElement.classList.add('cart-open')));
    $('[data-cart-close]').focus({ preventScroll: true });
  }
  function closeCart() {
    if (drawer.hidden) return;
    document.documentElement.classList.remove('cart-open');
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    closeTimer = setTimeout(() => { drawer.hidden = true; scrim.hidden = true; }, reduce ? 0 : 450);
    lastFocus?.focus?.({ preventScroll: true });
  }
  $$('[data-cart-open]').forEach((b) => b.addEventListener('click', openCart));
  $('[data-cart-close]').addEventListener('click', closeCart);
  scrim.addEventListener('click', closeCart);
  document.addEventListener('keydown', (e) => {
    if (drawer.hidden) return;
    if (e.key === 'Escape') closeCart();
    if (e.key === 'Tab') {
      const f = $$('button:not([disabled]), a[href], input', drawer).filter((el) => el.offsetParent !== null);
      if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
      else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
    }
  });

  // ── Toast ──
  const toast = $('[data-toast]');
  let toastTimer = 0;
  function say(msg) {
    toast.textContent = msg;
    toast.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-on'), 2600);
  }

  $('[data-add]').addEventListener('click', () => {
    add(colorId, qty);
    say(`Added ${qty} × DRIP Bottle — ${byId(colorId).name}`);
  });
  $('[data-shop]').addEventListener('click', () => {
    add(colorId, 1);
    openCart();
  });

  setQty(1);
  renderCart();
  setColor(colorId, true);

  return { get color() { return byId(colorId); } };
}
