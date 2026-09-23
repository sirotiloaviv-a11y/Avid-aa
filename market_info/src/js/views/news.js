import { esc, qs } from '../dom.js';
import { loadInto, newsCard, emptyView } from '../ui/components.js';
import { filterNews } from '../data/filters.js';
import { tzLabel } from '../format.js';

export async function render(root, ctx) {
  const tz = ctx.tz();
  let symbol = ctx.query.symbol ?? '';
  let category = ctx.query.category ?? '';

  root.innerHTML = `
    <div class="page-head"><h1>חדשות</h1>
      <span class="muted small">כל הידיעות הן ידיעות הדגמה שנכתבו עבור האבטיפוס. אין בהן ייחוס לכלי תקשורת ואין קישורים לכתבות.
        זמני פרסום לפי ${esc(tzLabel(tz))}.</span></div>
    <div id="news-body"></div>`;
  const body = qs(root, '#news-body');

  loadInto(body, ctx, () => Promise.all([
    ctx.provider.getNews(), ctx.provider.getAssets(), ctx.provider.getNewsCategories(),
  ]), ([news, assets, categories]) => {
    const bySymbol = Object.fromEntries(assets.map((a) => [a.symbol, a]));
    if (symbol && !bySymbol[symbol]) symbol = '';
    if (category && !categories.includes(category)) category = '';

    body.innerHTML = `
      <div class="toolbar">
        <label>נכס <select id="f-symbol"><option value="">כל הנכסים</option>
          ${assets.map((a) => `<option value="${esc(a.symbol)}">${esc(a.name)} (${esc(a.symbol)})</option>`).join('')}</select></label>
        <label>קטגוריה <select id="f-category"><option value="">כל הקטגוריות</option>
          ${categories.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join('')}</select></label>
        <button type="button" class="btn btn-ghost btn-sm" id="f-clear">ניקוי סינון</button>
        <span class="muted small" id="f-count" aria-live="polite"></span>
      </div>
      <div id="news-list" class="stack"></div>`;
    const symbolSel = qs(body, '#f-symbol');
    const categorySel = qs(body, '#f-category');
    symbolSel.value = symbol;
    categorySel.value = category;

    const draw = () => {
      ctx.setQuery({ symbol, category });
      const list = filterNews(news, { symbol, category });
      qs(body, '#f-count').textContent = `${list.length} ידיעות`;
      qs(body, '#news-list').innerHTML = list.length
        ? list.map((n) => newsCard(n, bySymbol, tz)).join('')
        : emptyView('אין ידיעות התואמות לסינון', 'נסו לבחור נכס או קטגוריה אחרים.');
    };
    symbolSel.addEventListener('change', () => { symbol = symbolSel.value; draw(); });
    categorySel.addEventListener('change', () => { category = categorySel.value; draw(); });
    qs(body, '#f-clear').addEventListener('click', () => {
      symbol = ''; category = '';
      symbolSel.value = ''; categorySel.value = '';
      draw();
    });
    draw();
  });
}
