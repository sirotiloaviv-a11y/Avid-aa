import { toJson } from './marketService.mjs';
import { MarketError } from './errors.mjs';

function send(res, status, body) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
  });
  res.end(JSON.stringify(body));
}

// Routes under /api/market/. Returns false when the path is not an API path.
export async function handleApi(req, res, url, service) {
  if (!url.pathname.startsWith('/api/')) return false;
  if (req.method !== 'GET') { send(res, 405, { error: { code: 'method', message: 'GET only' } }); return true; }
  if (!service) { send(res, 503, { error: { code: 'not_configured', message: 'שירות נתוני השוק לא הופעל בשרת.' } }); return true; }
  const symbol = url.searchParams.get('symbol') ?? '';
  try {
    switch (url.pathname) {
      case '/api/market/status': send(res, 200, service.status()); break;
      case '/api/market/assets': send(res, 200, { assets: await service.assets() }); break;
      case '/api/market/quote': send(res, 200, await service.quote(symbol)); break;
      case '/api/market/history': send(res, 200, await service.history(symbol)); break;
      default: send(res, 404, { error: { code: 'not_found', message: 'נתיב לא קיים' } });
    }
  } catch (err) {
    if (!(err instanceof MarketError)) console.error(err);
    send(res, err instanceof MarketError ? err.status : 500, { error: toJson(err) });
  }
  return true;
}
