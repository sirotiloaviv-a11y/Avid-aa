import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import type { DatabaseSync } from "node:sqlite";
import { createApp } from "../src/http/app.ts";
import type { HttpResponse } from "../src/http/response.ts";
import { createTestDatabase, insertProduct, setInventory } from "./helpers.ts";

/**
 * The four required cases end to end: real routing, real validation, real
 * SQLite. Only the socket is missing.
 */
describe("GET /api/products/:id/availability", () => {
  let db: DatabaseSync;
  let handle: (method: string, path: string) => HttpResponse;

  beforeEach(() => {
    db = createTestDatabase();
    handle = createApp(db);
  });

  afterEach(() => {
    db.close();
  });

  it("returns 200 and the stock level for a product that has inventory", () => {
    insertProduct(db, { id: 123, sku: "SKU-123", name: "Widget" });
    setInventory(db, 123, 17);

    const response = handle("GET", "/api/products/123/availability");

    assert.equal(response.status, 200);
    assert.deepEqual(response.body, {
      productId: "123",
      available: true,
      quantity: 17,
    });
  });

  it("returns 200 with available:false for a product with zero inventory", () => {
    insertProduct(db, { id: 456, sku: "SKU-456", name: "Sold Out Widget" });
    setInventory(db, 456, 0);

    const response = handle("GET", "/api/products/456/availability");

    assert.equal(response.status, 200);
    assert.deepEqual(response.body, {
      productId: "456",
      available: false,
      quantity: 0,
    });
  });

  it("returns 404 when the product does not exist", () => {
    const response = handle("GET", "/api/products/999/availability");

    assert.equal(response.status, 404);
    assert.deepEqual(response.body, {
      error: { code: "NOT_FOUND", message: "Product '999' was not found" },
    });
  });

  it("returns 400 for an invalid product ID", () => {
    const response = handle("GET", "/api/products/abc/availability");

    assert.equal(response.status, 400);
    assert.deepEqual(response.body, {
      error: {
        code: "INVALID_REQUEST",
        message: "productId must be a positive integer without leading zeros",
        field: "productId",
      },
    });
  });

  it("returns 400 rather than 404 for an invalid ID, even with no products", () => {
    const response = handle("GET", "/api/products/0/availability");
    assert.equal(response.status, 400);
  });

  it("returns 404 for a path that matches no route", () => {
    const response = handle("GET", "/api/products/123");
    assert.equal(response.status, 404);
  });

  it("does not answer non-GET methods on the availability route", () => {
    insertProduct(db, { id: 123, sku: "SKU-123", name: "Widget" });
    setInventory(db, 123, 17);

    const response = handle("POST", "/api/products/123/availability");
    assert.equal(response.status, 404);
  });

  it("does not let a SQL fragment in the path reach the database", () => {
    insertProduct(db, { id: 1, sku: "SKU-1", name: "Widget" });
    setInventory(db, 1, 5);

    const response = handle("GET", "/api/products/1%20OR%201%3D1/availability");
    assert.equal(response.status, 400);
  });

  it("ignores a query string when matching the route", () => {
    insertProduct(db, { id: 123, sku: "SKU-123", name: "Widget" });
    setInventory(db, 123, 3);

    const response = handle("GET", "/api/products/123/availability?warehouse=eu");
    assert.equal(response.status, 200);
  });
});
