import { buildDemoDataset, makeManualDemoAlert, NEWS_CATEGORIES, average } from './demoData.js';
import { filterNews } from './filters.js';

export class DemoProvider {
  // latencyMs simulates a network round trip so loading states are visible.
  // shouldFail lets the settings screen simulate a failed request.
  constructor({ now = new Date(), latencyMs = 350, shouldFail = () => false } = {}) {
    this.dataset = buildDemoDataset(now);
    this.latencyMs = latencyMs;
    this.shouldFail = shouldFail;
    this.capabilities = { news: true, events: true, alerts: true, demoTrigger: true };
    this.mode = 'demo';
  }

  async respond(produce) {
    if (this.latencyMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, this.latencyMs));
    }
    if (this.shouldFail()) {
      throw new Error('שגיאה מדומה בטעינת נתוני ההדגמה (הופעלה מההגדרות).');
    }
    return structuredClone(produce());
  }

  getSourceInfo() {
    return this.respond(() => ({ id: 'demo', label: 'נתוני הדגמה מקומיים', isDemo: true, isLive: false }));
  }

  getAssets() {
    return this.respond(() => this.dataset.assets);
  }

  getAsset(symbol) {
    return this.respond(() => this.dataset.assets.find((a) => a.symbol === symbol) ?? null);
  }

  getPriceHistory(symbol, bars = 30) {
    return this.respond(() => (this.dataset.histories[symbol] ?? []).slice(-bars));
  }

  getMarketOverview() {
    return this.respond(() => {
      const group = (type) => {
        const list = this.dataset.assets.filter((a) => a.type === type);
        return {
          count: list.length,
          avgChangePct: average(list.map((a) => a.changePct)),
          up: list.filter((a) => a.changePct > 0).length,
          down: list.filter((a) => a.changePct < 0).length,
        };
      };
      const stocks = group('stock');
      const crypto = group('crypto');
      return {
        stocks,
        crypto,
        breadth: { up: stocks.up + crypto.up, down: stocks.down + crypto.down },
        asOf: this.dataset.generatedAt,
      };
    });
  }

  getNews(filter = {}) {
    return this.respond(() => filterNews(this.dataset.news, filter));
  }

  getNewsCategories() {
    return this.respond(() => NEWS_CATEGORIES);
  }

  getEvents({ from = -Infinity, to = Infinity } = {}) {
    return this.respond(() => this.dataset.events.filter((e) => e.time >= from && e.time < to));
  }

  getAlerts() {
    return this.respond(() => this.dataset.alerts);
  }

  createDemoAlert(enabledTypes) {
    return this.respond(() => makeManualDemoAlert(this.dataset, enabledTypes));
  }
}
