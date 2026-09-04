/**
 * The schema lives in a .ts file rather than a .sql one so it ships with the
 * module graph — no bundler config, no runtime file reads, no path that works
 * in tests but not from an installed copy.
 *
 * Inventory is a separate table from the product itself because the two change
 * on completely different clocks: a product row is written once, its quantity
 * moves on every order. A product with no inventory row has simply never been
 * stocked, which reads as a quantity of zero.
 */
export const SCHEMA = `
CREATE TABLE IF NOT EXISTS products (
  id          INTEGER PRIMARY KEY,
  sku         TEXT    NOT NULL UNIQUE,
  name        TEXT    NOT NULL,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_inventory (
  product_id  INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
  quantity    INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
  updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
`;
