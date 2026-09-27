/* סנאנס — הוספה מהירה לעגלה בלי לעזוב את העמוד (תואם Dawn: מגירת עגלה + בועת העגלה בכותרת) */
(() => {
  const ADD_URL = ((window.Shopify && window.Shopify.routes && window.Shopify.routes.root) || '/') + 'cart/add.js';

  // כפתורי + / − של הכמות
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-sn-qty]');
    if (!button) return;
    const input = button.parentElement.querySelector('input');
    const next = (parseInt(input.value, 10) || 1) + Number(button.dataset.snQty);
    input.value = Math.min(Math.max(next, 1), Number(input.max) || 99);
  });

  document.addEventListener('submit', async (event) => {
    const form = event.target.closest('[data-sn-quick-add]');
    if (!form) return;
    event.preventDefault();

    const button = form.querySelector('.sn-btn-add');
    const label = button.querySelector('[data-label]');
    const original = label.textContent;
    const cartDrawer = document.querySelector('cart-drawer');
    const sections = cartDrawer && typeof cartDrawer.getSectionsToRender === 'function'
      ? cartDrawer.getSectionsToRender().map((section) => section.id)
      : ['cart-icon-bubble'];

    const body = new FormData(form);
    body.append('sections', sections.join(','));
    body.append('sections_url', window.location.pathname);

    button.setAttribute('aria-busy', 'true');
    button.classList.remove('is-added', 'is-error');

    try {
      const response = await fetch(ADD_URL, {
        method: 'POST',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        body,
      });
      const data = await response.json();
      if (!response.ok || data.status) throw new Error(data.description || data.message);

      if (cartDrawer && typeof cartDrawer.renderContents === 'function') {
        cartDrawer.classList.remove('is-empty');
        cartDrawer.renderContents(data);
      } else if (data.sections && data.sections['cart-icon-bubble']) {
        const bubble = document.getElementById('cart-icon-bubble');
        const html = new DOMParser().parseFromString(data.sections['cart-icon-bubble'], 'text/html');
        const inner = html.querySelector('.shopify-section');
        if (bubble && inner) bubble.innerHTML = inner.innerHTML;
      }

      if (typeof publish === 'function' && typeof PUB_SUB_EVENTS !== 'undefined') {
        publish(PUB_SUB_EVENTS.cartUpdate, { source: 'sn-quick-add', productVariantId: body.get('id'), cartData: data });
      }

      button.classList.add('is-added');
      label.textContent = 'נוסף ✓';
      form.querySelector('input[name="quantity"]').value = 1;
    } catch (error) {
      button.classList.add('is-error');
      label.textContent = error.message || 'משהו השתבש, נסו שוב';
    } finally {
      button.removeAttribute('aria-busy');
      setTimeout(() => {
        button.classList.remove('is-added', 'is-error');
        label.textContent = original;
      }, 2200);
    }
  });
})();
