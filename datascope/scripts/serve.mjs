/**
 * The local server: static files, plus the Yahoo Finance proxy.
 *
 * The proxy exists for one reason. Yahoo's endpoints send no CORS headers, so a
 * browser cannot call them from a page - but they need no API key, which makes
 * them the only stock source that works the moment `npm start` does. Forwarding
 * them through the server the user is already running keeps that "no signup"
 * property without asking anyone to trust a third-party proxy.
 *
 * What it will and will not forward is deliberately narrow:
 *   - only GET,
 *   - only the two Yahoo paths the app actually calls,
 *   - only to a fixed upstream host,
 *   - nothing from the incoming request is passed on except the path and query.
 *
 * Without that, this becomes an open proxy on the user's machine: any page in
 * their browser could use it to reach anything the machine can reach.
 *
 * Usage: node scripts/serve.mjs [--dir <folder>] [--port <number>]
 */

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, '..');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.ico': 'image/x-icon',
};

const YAHOO_UPSTREAM = 'https://query1.finance.yahoo.com';
/** Exactly the two endpoints src/providers/yahoo.js calls. */
const YAHOO_ALLOWED = [/^\/v8\/finance\/chart\/[A-Za-z0-9.\-^]{1,20}$/, /^\/v1\/finance\/search$/];

function parseArgs(argv) {
  const options = { dir: '.', port: 4173 };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--dir' && argv[i + 1]) {
      options.dir = argv[i + 1];
      i += 1;
    } else if (argv[i] === '--port' && argv[i + 1]) {
      options.port = Number(argv[i + 1]) || options.port;
      i += 1;
    }
  }
  return options;
}

const { dir, port } = parseArgs(process.argv.slice(2));
const servedRoot = path.resolve(projectRoot, dir);

/** @param {string} pathname */
export function isAllowedYahooPath(pathname) {
  return YAHOO_ALLOWED.some((pattern) => pattern.test(pathname));
}

async function proxyYahoo(request, response, url) {
  const upstreamPath = url.pathname.replace(/^\/api\/yahoo/, '');

  if (request.method !== 'GET') {
    response.writeHead(405, { 'content-type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ error: 'method not allowed' }));
    return;
  }
  if (!isAllowedYahooPath(upstreamPath)) {
    response.writeHead(403, { 'content-type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ error: 'path not allowed', path: upstreamPath }));
    return;
  }

  const target = new URL(upstreamPath + url.search, YAHOO_UPSTREAM);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10_000);

  try {
    const upstream = await fetch(target, {
      signal: controller.signal,
      headers: {
        // Yahoo answers with an error page to a request with no user agent.
        'user-agent': 'Mozilla/5.0 (compatible; DataScope/2.0; +local)',
        accept: 'application/json',
      },
    });
    const body = await upstream.text();
    response.writeHead(upstream.status, {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
    });
    response.end(body);
  } catch (error) {
    const aborted = error?.name === 'AbortError';
    response.writeHead(aborted ? 504 : 502, {
      'content-type': 'application/json; charset=utf-8',
    });
    response.end(
      JSON.stringify({
        error: aborted ? 'upstream timeout' : 'upstream unreachable',
        detail: error instanceof Error ? error.message : String(error),
      }),
    );
  } finally {
    clearTimeout(timer);
  }
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`);

  if (url.pathname.startsWith('/api/yahoo')) {
    await proxyYahoo(request, response, url);
    return;
  }

  try {
    const decoded = decodeURIComponent(url.pathname);
    const relative = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '');
    const target = path.resolve(servedRoot, relative);

    // Everything served must live inside the served root.
    if (target !== servedRoot && !target.startsWith(servedRoot + path.sep)) {
      response.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
      response.end('403 Forbidden\n');
      return;
    }

    const info = await stat(target);
    const file = info.isDirectory() ? path.join(target, 'index.html') : target;
    const finalInfo = info.isDirectory() ? await stat(file) : info;

    response.writeHead(200, {
      'content-type': MIME_TYPES[path.extname(file).toLowerCase()] ?? 'application/octet-stream',
      'content-length': finalInfo.size,
      'cache-control': 'no-store',
    });
    createReadStream(file).pipe(response);
  } catch {
    response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    response.end('404 Not Found\n');
  }
});

/**
 * Only listen when this file is the program being run. The tests import it for
 * `isAllowedYahooPath`, and a module that opens a socket on import would leave
 * the test runner waiting on it forever.
 */
const isMain = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;

// Loopback only: the proxy must not be reachable from the local network.
if (isMain) server.listen(port, '127.0.0.1', () => {
  console.log(`DataScope מוגש מתוך: ${servedRoot}`);
  console.log(`נא לפתוח בדפדפן: http://127.0.0.1:${port}/`);
  console.log('proxy למניות (Yahoo) פעיל בנתיב /api/yahoo');
  console.log('לעצירה: Ctrl+C');
});

export { server };
