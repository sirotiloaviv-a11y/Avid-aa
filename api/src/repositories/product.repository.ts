import type { DatabaseSync } from "node:sqlite";
import type { ProductInventory } from "../domain/product.ts";

/**
 * Read access to product stock.
 *
 * Declared as an interface so callers depend on the query, not on SQLite. The
 * service is tested against the real implementation because an in-memory
 * SQLite database is cheap and a fake would only prove the fake works.
 */
export interface ProductRepository {
  /** Returns null when no product carries this ID. */
  findInventoryByProductId(productId: number): ProductInventory | null;
}

export class SqliteProductRepository implements ProductRepository {
  readonly #db: DatabaseSync;

  constructor(db: DatabaseSync) {
    this.#db = db;
  }

  findInventoryByProductId(productId: number): ProductInventory | null {
    // LEFT JOIN, not INNER: a product that has never been stocked still
    // exists, and the caller is owed a 200 with zero rather than a 404.
    const row = this.#db
      .prepare(
        `SELECT p.id                    AS product_id,
                COALESCE(i.quantity, 0) AS quantity
           FROM products p
           LEFT JOIN product_inventory i ON i.product_id = p.id
          WHERE p.id = ?`,
      )
      .get(productId);

    if (row === undefined) {
      return null;
    }

    return {
      productId: Number(row["product_id"]),
      quantity: Number(row["quantity"]),
    };
  }
}
