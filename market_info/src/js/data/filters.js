// Pure filtering helpers shared by the provider and the screens.

export function normalize(text) {
  return String(text ?? '').trim().toLowerCase();
}

export function searchAssets(assets, { query = '', type = 'all' } = {}) {
  const q = normalize(query);
  return assets.filter((a) => {
    if (type !== 'all' && a.type !== type) return false;
    if (!q) return true;
    return normalize(a.symbol).includes(q) || normalize(a.name).includes(q);
  });
}

export function filterNews(news, { symbol = '', category = '' } = {}) {
  return news.filter((n) => {
    if (symbol && !n.symbols.includes(symbol)) return false;
    if (category && n.category !== category) return false;
    return true;
  });
}

export function filterAlerts(alerts, { types = null, symbol = '', status = 'all', readIds = {} } = {}) {
  return alerts.filter((a) => {
    if (types && !types.includes(a.type)) return false;
    if (symbol && a.symbol !== symbol) return false;
    const isRead = Boolean(readIds[a.id]);
    if (status === 'unread' && isRead) return false;
    if (status === 'read' && !isRead) return false;
    return true;
  });
}

// Manual demo alerts and generated alerts merged, newest first, no duplicates.
export function mergeAlerts(generated, manual) {
  const seen = new Set();
  const out = [];
  for (const a of [...manual, ...generated]) {
    if (seen.has(a.id)) continue;
    seen.add(a.id);
    out.push(a);
  }
  return out.sort((a, b) => b.time - a.time);
}
