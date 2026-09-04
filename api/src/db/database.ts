import { DatabaseSync } from "node:sqlite";
import { SCHEMA } from "./schema.sql.ts";

/**
 * Opens a database and brings it up to the current schema.
 *
 * `node:sqlite` is a Node builtin, which is what keeps this package at zero
 * dependencies — the same constraint the scanner in `moat/` holds itself to.
 *
 * @param location A filesystem path, or ":memory:" for an ephemeral database.
 */
export function createDatabase(location: string): DatabaseSync {
  const db = new DatabaseSync(location);
  // Off by default in SQLite, and the inventory table's cascade is worthless
  // without it.
  db.exec("PRAGMA foreign_keys = ON;");
  db.exec(SCHEMA);
  return db;
}

export function databaseLocationFromEnv(): string {
  return process.env["DATABASE_PATH"] ?? "./data/products.db";
}
