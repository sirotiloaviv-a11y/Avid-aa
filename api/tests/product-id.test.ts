import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { parseProductId } from "../src/validation/product-id.ts";
import { ValidationError } from "../src/domain/errors.ts";

describe("parseProductId", () => {
  it("accepts a positive integer", () => {
    assert.equal(parseProductId("123"), 123);
  });

  it("accepts the smallest valid ID", () => {
    assert.equal(parseProductId("1"), 1);
  });

  it("accepts the largest safely representable ID", () => {
    assert.equal(parseProductId(String(Number.MAX_SAFE_INTEGER)), Number.MAX_SAFE_INTEGER);
  });

  const invalid: ReadonlyArray<[string, string | undefined]> = [
    ["a missing ID", undefined],
    ["an empty string", ""],
    ["a non-numeric ID", "abc"],
    ["a mixed alphanumeric ID", "12a"],
    ["zero", "0"],
    ["a negative number", "-5"],
    ["a decimal", "1.5"],
    ["a leading-zero ID", "007"],
    ["whitespace padding", " 12"],
    ["a SQL injection attempt", "1 OR 1=1"],
    ["scientific notation", "1e3"],
    ["a hex literal", "0x10"],
  ];

  for (const [description, input] of invalid) {
    it(`rejects ${description}`, () => {
      assert.throws(() => parseProductId(input), ValidationError);
    });
  }

  it("rejects an ID beyond the safe integer range", () => {
    // 2^53, the first integer a JS number cannot represent exactly.
    assert.throws(() => parseProductId("9007199254740992"), ValidationError);
  });

  it("reports which field failed", () => {
    try {
      parseProductId("abc");
      assert.ok(false, "expected parseProductId to throw");
    } catch (error) {
      assert.ok(error instanceof ValidationError);
      assert.equal(error.field, "productId");
    }
  });
});
