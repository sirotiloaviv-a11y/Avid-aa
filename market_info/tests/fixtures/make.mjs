// Builds synthetic provider payloads in the documented shapes.
export function avDaily(symbol, lastDate, count = 30, { start = 100, volume = 1_000_000, lastRefreshed } = {}) {
  const series = {};
  let d = new Date(`${lastDate}T00:00:00Z`);
  const dates = [];
  while (dates.length < count) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) dates.push(d.toISOString().slice(0, 10));
    d = new Date(d.getTime() - 86400000);
  }
  dates.reverse().forEach((date, i) => {
    const close = start + i;
    series[date] = {
      '1. open': (close - 0.5).toFixed(4), '2. high': (close + 1).toFixed(4),
      '3. low': (close - 1).toFixed(4), '4. close': close.toFixed(4), '5. volume': String(volume + i * 1000),
    };
  });
  return {
    'Meta Data': {
      '1. Information': 'Daily Prices (open, high, low, close) and Volumes',
      '2. Symbol': symbol, '3. Last Refreshed': lastRefreshed ?? lastDate,
      '4. Output Size': 'Compact', '5. Time Zone': 'US/Eastern',
    },
    'Time Series (Daily)': series,
  };
}

export function cgMarkets(entries, lastUpdated) {
  return entries.map(([id, symbol, name, price, change]) => ({
    id, symbol, name, current_price: price, total_volume: price * 1000,
    price_change_24h: change, price_change_percentage_24h: (change / (price - change)) * 100,
    last_updated: lastUpdated,
  }));
}

export function cgChart(endMs, days = 5, start = 1000) {
  const prices = [];
  const total_volumes = [];
  for (let i = 0; i <= days; i++) {
    const t = endMs - (days - i) * 86400000;
    prices.push([t, start + i * 10]);
    total_volumes.push([t, 5e9 + i]);
  }
  return { prices, market_caps: [], total_volumes };
}

// A fetch stand-in that routes by URL and records every call.
export function fakeFetch(routes) {
  const calls = [];
  const impl = async (url, init = {}) => {
    const u = new URL(url);
    calls.push({ url: u, headers: init.headers ?? {} });
    for (const [match, respond] of routes) {
      if (match(u)) {
        const r = await respond(u);
        if (r instanceof Error) throw r;
        const headers = new Headers(r.headers ?? {});
        return {
          status: r.status ?? 200, headers,
          text: async () => (typeof r.body === 'string' ? r.body : JSON.stringify(r.body)),
        };
      }
    }
    return { status: 404, headers: new Headers(), text: async () => '{}' };
  };
  return { impl, calls };
}
