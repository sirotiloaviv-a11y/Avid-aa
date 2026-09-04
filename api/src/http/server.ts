import { createServer, type Server } from "node:http";
import type { DatabaseSync } from "node:sqlite";
import { createApp } from "./app.ts";

export interface ServerOptions {
  readonly db: DatabaseSync;
  readonly port: number;
  readonly host: string;
}

export function createHttpServer(options: ServerOptions): Server {
  const handle = createApp(options.db);

  return createServer((req, res) => {
    const response = handle(req.method ?? "GET", req.url ?? "/");
    const payload = JSON.stringify(response.body);

    res.statusCode = response.status;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.end(payload);
  });
}
