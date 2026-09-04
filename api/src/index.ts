import { createDatabase, databaseLocationFromEnv } from "./db/database.ts";
import { createHttpServer } from "./http/server.ts";

const port = Number(process.env["PORT"] ?? "3000");
const host = process.env["HOST"] ?? "127.0.0.1";

const db = createDatabase(databaseLocationFromEnv());
const server = createHttpServer({ db, port, host });

server.listen(port, host, () => {
  console.log(`API listening on http://${host}:${port}`);
});

process.on("SIGINT", () => {
  server.close(() => {
    db.close();
  });
});
