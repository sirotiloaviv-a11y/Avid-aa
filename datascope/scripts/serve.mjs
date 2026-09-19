/**
 * Minimal static file server for local use - so `npm start` works with no
 * installed packages at all.
 *
 * It binds to 127.0.0.1 only, serves a single directory, and refuses any path
 * that resolves outside it. It is a development convenience, not a production
 * web server.
 *
 * Usage: node scripts/serve.mjs [--dir <folder>] [--port <number>]
 */

import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(here, '..');

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.ico': 'image/x-icon',
};

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

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`);
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

server.listen(port, '127.0.0.1', () => {
  console.log(`DataScope מוגש מתוך: ${servedRoot}`);
  console.log(`נא לפתוח בדפדפן: http://127.0.0.1:${port}/`);
  console.log('לעצירה: Ctrl+C');
});
