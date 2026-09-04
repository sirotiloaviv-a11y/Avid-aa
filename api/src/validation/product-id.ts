import { ValidationError } from "../domain/errors.ts";

/**
 * Product IDs are positive integers. They arrive as URL path segments, so the
 * only thing standing between the caller and the database is this function.
 *
 * Leading zeros are rejected rather than trimmed: accepting both "7" and "007"
 * would give one product two spellings, and the response echoes the ID back,
 * so the canonical form has to be the only form.
 */
const PRODUCT_ID_PATTERN = /^[1-9][0-9]*$/;

/**
 * SQLite stores INTEGER keys as 64-bit, but anything past 2^53-1 stops being
 * representable as a JS number, so the API refuses IDs it could not round-trip
 * rather than silently answering about a different product.
 */
const MAX_PRODUCT_ID = Number.MAX_SAFE_INTEGER;

export function parseProductId(raw: string | undefined): number {
  if (raw === undefined || raw === "") {
    throw new ValidationError("productId", "productId is required");
  }

  if (!PRODUCT_ID_PATTERN.test(raw)) {
    throw new ValidationError(
      "productId",
      "productId must be a positive integer without leading zeros",
    );
  }

  const parsed = Number(raw);
  if (parsed > MAX_PRODUCT_ID) {
    throw new ValidationError(
      "productId",
      `productId must not exceed ${MAX_PRODUCT_ID}`,
    );
  }

  return parsed;
}
