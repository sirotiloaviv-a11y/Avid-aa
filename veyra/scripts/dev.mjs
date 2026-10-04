// Runs the API (port 4000) and the Vite dev server (port 5173) together,
// with prefixed output, and stops both when either exits or on Ctrl+C.
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';

for (const dir of ['server', 'web']) {
  if (!existsSync(path.join(root, dir, 'node_modules'))) {
    console.error(`Dependencies for ${dir}/ are missing. Run "npm run setup" first.`);
    process.exit(1);
  }
}

const processes = [
  { name: 'api', color: '\x1b[36m', dir: 'server' },
  { name: 'web', color: '\x1b[35m', dir: 'web' },
].map(({ name, color, dir }) => {
  const child = spawn(npm, ['run', 'dev'], { cwd: path.join(root, dir), env: process.env, shell: process.platform === 'win32' });
  const prefix = `${color}[${name}]\x1b[0m `;
  const pipe = (stream, target) => {
    let buffer = '';
    stream.on('data', (chunk) => {
      buffer += chunk;
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) target.write(`${prefix}${line}\n`);
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  return child;
});

let stopping = false;
const stop = (code = 0) => {
  if (stopping) return;
  stopping = true;
  for (const child of processes) if (child.exitCode === null) child.kill('SIGTERM');
  setTimeout(() => process.exit(code), 300);
};

for (const child of processes) child.on('exit', (code) => stop(code ?? 0));
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

console.log('\n  Veyra Security Brain\n  Dashboard: http://127.0.0.1:5173\n  API:       http://127.0.0.1:4000/api/health\n');
