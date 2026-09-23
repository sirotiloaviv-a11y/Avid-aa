// The interface the screens depend on. Screens never import data sources
// directly; they call these methods on the provider for the active mode.
//
// Every method returns a Promise. Times are epoch milliseconds (UTC).
//
//   capabilities                        -> { news, events, alerts, demoTrigger }
//   getSourceInfo()                     -> { id, label, isDemo, isLive, ... }
//   getAssets()                         -> Asset[]  (an item may carry `error` instead of a price)
//   getAsset(symbol)                    -> Asset | null
//   getPriceHistory(symbol, bars)       -> Bar[]  ({ t, open, high, low, close, volume }; any of
//                                          open/high/low/volume may be null when the source lacks them)
//   getMarketOverview()                 -> demo: { stocks, crypto, breadth, asOf }
//                                          market: { kind: 'market', providers, sessions, ... }
//   getNews({ symbol?, category? })     -> NewsItem[]
//   getNewsCategories()                 -> string[]
//   getEvents({ from?, to? })           -> CalendarEvent[]
//   getAlerts()                         -> Alert[]
//   createDemoAlert(enabledTypes)       -> Alert | null   (demo only)
//
// Market-mode assets and series also carry `meta`: source, data time (asOf),
// fetch time, known delay, and stale / partial flags.

import { DemoProvider } from './demoProvider.js';
import { MarketProvider } from './marketProvider.js';

export function createProvider(mode = 'demo', options = {}) {
  return mode === 'market' ? new MarketProvider(options) : new DemoProvider(options);
}
