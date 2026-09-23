// The interface the screens depend on. Screens never import demo data
// directly; they call these methods, so a real data source can replace the
// demo one by implementing the same contract (see README, "חיבור מקור נתונים").
//
// Every method returns a Promise. Times are epoch milliseconds (UTC).
//
//   getSourceInfo()                     -> { id, label, isDemo, isLive }
//   getAssets()                         -> Asset[]
//   getAsset(symbol)                    -> Asset | null
//   getPriceHistory(symbol, bars)       -> Bar[]  ({ t, open, high, low, close, volume })
//   getMarketOverview()                 -> { stocks, crypto, breadth, asOf }
//   getNews({ symbol?, category? })     -> NewsItem[]
//   getNewsCategories()                 -> string[]
//   getEvents({ from?, to? })           -> CalendarEvent[]
//   getAlerts()                         -> Alert[]
//   createDemoAlert(enabledTypes)       -> Alert | null   (demo sources only)

import { DemoProvider } from './demoProvider.js';

export function createProvider(options = {}) {
  return new DemoProvider(options);
}
