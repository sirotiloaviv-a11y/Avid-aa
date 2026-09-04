/**
 * Minimal ambient declarations for the Node builtins this package uses.
 *
 * These exist only because `@types/node` cannot be installed here: the npm
 * registry is outside this environment's network egress allowlist, and the
 * rest of the repository is deliberately dependency-free anyway. They cover
 * exactly the surface `src/` and `tests/` touch and nothing more.
 *
 * If `@types/node` ever becomes installable, delete this file and add it to
 * `devDependencies` plus `compilerOptions.types` — nothing else has to change.
 */

declare const console: {
  log(...args: unknown[]): void;
  error(...args: unknown[]): void;
};

declare const process: {
  readonly env: Record<string, string | undefined>;
  exitCode: number | undefined;
  on(event: string, listener: () => void): void;
};

declare module "node:sqlite" {
  export type SQLInputValue = string | number | null;
  export type SQLOutputValue = string | number | bigint | null;

  export class StatementSync {
    get(...params: SQLInputValue[]): Record<string, SQLOutputValue> | undefined;
    all(...params: SQLInputValue[]): Record<string, SQLOutputValue>[];
    run(...params: SQLInputValue[]): { changes: number; lastInsertRowid: number };
  }

  export class DatabaseSync {
    constructor(location: string);
    exec(sql: string): void;
    prepare(sql: string): StatementSync;
    close(): void;
  }
}

declare module "node:http" {
  export interface IncomingMessage {
    readonly method?: string | undefined;
    readonly url?: string | undefined;
  }

  export interface ServerResponse {
    statusCode: number;
    setHeader(name: string, value: string): void;
    end(chunk?: string): void;
  }

  export interface Server {
    listen(port: number, host: string, callback?: () => void): Server;
    close(callback?: () => void): Server;
  }

  export function createServer(
    listener: (req: IncomingMessage, res: ServerResponse) => void,
  ): Server;
}

declare module "node:test" {
  type TestFn = () => void | Promise<void>;
  export function test(name: string, fn: TestFn): void;
  export function describe(name: string, fn: () => void): void;
  export function it(name: string, fn: TestFn): void;
  export function beforeEach(fn: TestFn): void;
  export function afterEach(fn: TestFn): void;
}

declare module "node:assert/strict" {
  interface Assert {
    (value: unknown, message?: string): asserts value;
    equal(actual: unknown, expected: unknown, message?: string): void;
    deepEqual(actual: unknown, expected: unknown, message?: string): void;
    ok(value: unknown, message?: string): asserts value;
    throws(fn: () => unknown, expected?: unknown, message?: string): void;
    match(actual: string, expected: RegExp, message?: string): void;
  }
  const assert: Assert;
  export default assert;
}
