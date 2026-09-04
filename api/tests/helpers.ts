import type { DatabaseSync } from "node:sqlite";
import { createDatabase } from "../src/db/database.ts";

/** A fresh in-memory database on the real schema — no fixtures file, no cleanup. */
export function createTestDatabase(): DatabaseSync {
  return createDatabase(":memory:");
}

export function insertProduct(
  db: DatabaseSync,
  product: { id: number; sku: string; name: string },
): void {
  db.prepare("INSERT INTO products (id, sku, name) VALUES (?, ?, ?)").run(
    product.id,
    product.sku,
    product.name,
  );
}

export function setInventory(db: DatabaseSync, productId: number, quantity: number): void {
  db.prepare(
    "INSERT INTO product_inventory (product_id, quantity) VALUES (?, ?)",
  ).run(productId, quantity);
}
