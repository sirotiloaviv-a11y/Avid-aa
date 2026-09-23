// Market-data mode. The page never talks to data vendors directly: it calls
// the local server, which holds the API keys, caches answers and enforces
// quotas. News, events and alerts are not connected in this mode, and demo
// content is never used to fill the gaps.

export class MarketDataError extends Error {
  constructor({ code, message, retryAfterSec = null, provider = null }) {
    super(message);
    this.code = code;
    this.retryAfterSec = retryAfterSec;
    this.provider = provider;
  }
}

export class MarketProvider {
  constructor({ baseUrl = '', fetchImpl = (...a) => globalThis.fetch(...a), historyTtlMs = 60000 } = {}) {
    this.baseUrl = baseUrl;
    this.fetchImpl = fetchImpl;
    this.historyTtlMs = historyTtlMs;
    this.historyCache = new Map();
    this.capabilities = { news: false, events: false, alerts: false, demoTrigger: false };
    this.mode = 'market';
  }

  async request(path) {
    let res;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/api/market/${path}`, { headers: { accept: 'application/json' } });
    } catch {
      throw new MarketDataError({ code: 'server_unreachable', message: 'השרת המקומי אינו זמין. ודאו שהמערכת הופעלה עם npm start.' });
    }
    let body = null;
    try { body = await res.json(); } catch { /* handled below */ }
    if (!res.ok || !body) {
      const e = body?.error ?? { code: 'server_error', message: `שגיאה בשרת המקומי (HTTP ${res.status}).` };
      throw new MarketDataError(e);
    }
    return body;
  }

  getSourceInfo() {
    return this.request('status').then((s) => ({ id: 'market', label: 'נתוני שוק', isDemo: false, isLive: false, ...s }));
  }

  getStatus() {
    return this.request('status');
  }

  async getAssets() {
    return (await this.request('assets')).assets;
  }

  // Unknown or malformed symbols resolve to null so the page can say
  // "not found"; every other failure is thrown and shown as an error.
  async getAsset(symbol) {
    try {
      return await this.request(`quote?symbol=${encodeURIComponent(symbol)}`);
    } catch (err) {
      if (err.code === 'invalid_symbol' || err.code === 'bad_symbol_format') return null;
      throw err;
    }
  }

  async getHistory(symbol) {
    const hit = this.historyCache.get(symbol);
    if (hit && Date.now() - hit.at < this.historyTtlMs) return hit.value;
    const value = await this.request(`history?symbol=${encodeURIComponent(symbol)}`);
    this.historyCache.set(symbol, { at: Date.now(), value });
    return value;
  }

  async getPriceHistory(symbol, bars = 30) {
    const h = await this.getHistory(symbol);
    return h.bars.slice(-bars);
  }

  async getMarketOverview() {
    const s = await this.getStatus();
    return { kind: 'market', ...s };
  }

  // Not connected in market mode. Screens check `capabilities` first; these
  // return empty lists so that nothing invented can leak through.
  async getNews() { return []; }
  async getNewsCategories() { return []; }
  async getEvents() { return []; }
  async getAlerts() { return []; }
  async createDemoAlert() { return null; }
}
