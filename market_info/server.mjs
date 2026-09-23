// Minimal static file server for local use only. It listens on 127.0.0.1, so
// the app is not reachable from other machines.
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

const here = fileURLToPath(new URL('.', import.meta.url));
const root = resolve(here, process.argv[2] ?? 'src');
const port = Number(process.env.PORT ?? 5173);
const host = process.env.HOST ?? '127.0.0.1';

export function createAppServer(dir = root) {
  return createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      let path = normalize(decodeURIComponent(url.pathname)).replace(/^([/\\])+/, '');
      if (path === '' || path.endsWith(sep)) path = join(path, 'index.html');
      const file = resolve(dir, path);
      if (file !== dir && !file.startsWith(dir + sep)) {
        res.writeHead(403).end('Forbidden');
        return;
      }
      const info = await stat(file).catch(() => null);
      if (!info || !info.isFile()) {
        res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }).end('Not found');
        return;
      }
      res.writeHead(200, {
        'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
      });
      res.end(await readFile(file));
    } catch {
      res.writeHead(500).end('Server error');
    }
  });
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  createAppServer().listen(port, host, () => {
    console.log(`מרכז מידע שוק (הדגמה) פועל: http://localhost:${port}`);
    console.log(`מגיש קבצים מתוך: ${root}`);
    console.log('לעצירה: Ctrl+C');
  }).on('error', (err) => {
    if (err.code === 'EADDRINUSE') {
      console.error(`הפורט ${port} תפוס. נסו: PORT=5174 npm start`);
    } else {
      console.error(err.message);
    }
    process.exit(1);
  });
}
