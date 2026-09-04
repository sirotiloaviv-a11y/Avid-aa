import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import type { DatabaseSync } from "node:sqlite";
import { SqliteProductRepository } from "../src/repositories/product.repository.ts";
import { ProductAvailabilityService } from "../src/services/product-availability.service.ts";
import { NotFoundError, ValidationError } from "../src/domain/errors.ts";
import { createTestDatabase, insertProduct, setInventory } from "./helpers.ts";

describe("ProductAvailabilityService", () => {
  let db: DatabaseSync;
  let service: ProductAvailabilityService;

  beforeEach(() => {
    db = createTestDatabase();
    service = new ProductAvailabilityService(new SqliteProductRepository(db));
  });

  afterEach(() => {
    db.close();
  });

  it("reports a product that exists and has inventory as available", () => {
    insertProduct(db, { id: 123, sku: "SKU-123", name: "Widget" });
    setInventory(db, 123, 17);

    assert.deepEqual(service.getAvailability("123"), {
      productId: "123",
      available: true,
      quantity: 17,
    });
  });

  it("reports a product with zero inventory as unavailable", () => {
    insertProduct(db, { id: 456, sku: "SKU-456", name: "Sold Out Widget" });
    setInventory(db, 456, 0);

    assert.deepEqual(service.getAvailability("456"), {
      productId: "456",
      available: false,
      quantity: 0,
    });
  });

  it("treats a never-stocked product as zero rather than missing", () => {
    // No product_inventory row at all — the product exists, it has just never
    // been stocked. That is a 200 with zero, not a 404.
    insertProduct(db, { id: 789, sku: "SKU-789", name: "Unstocked Widget" });

    assert.deepEqual(service.getAvailability("789"), {
      productId: "789",
      available: false,
      quantity: 0,
    });
  });

  it("throws NotFoundError when the product does not exist", () => {
    assert.throws(() => service.getAvailability("999"), NotFoundError);
  });

  it("throws NotFoundError rather than leaking another product's stock", () => {
    insertProduct(db, { id: 1, sku: "SKU-1", name: "Widget" });
    setInventory(db, 1, 5);

    assert.throws(() => service.getAvailability("2"), NotFoundError);
  });

  it("throws ValidationError for an invalid product ID", () => {
    assert.throws(() => service.getAvailability("not-a-number"), ValidationError);
  });

  it("validates before touching the database", () => {
    // No products exist, so a missing-ID failure would be indistinguishable
    // from a not-found one unless validation runs first.
    assert.throws(() => service.getAvailability("-1"), ValidationError);
  });
});
