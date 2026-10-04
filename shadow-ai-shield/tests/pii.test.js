// Run with: node --test shadow-ai-shield/tests/pii.test.js
const test = require("node:test");
const assert = require("node:assert");
const { maskText } = require("../pii.js");

const masked = [
  ["mail me at john.doe@acme.com", "mail me at [EMAIL]"],
  ["card 4111 1111 1111 1111 ok", "card [CREDIT_CARD] ok"],
  ["ssn 123-45-6789", "ssn [SSN]"],
  ["key sk-ant-abcdefghijklmnopqrstuvwxyz123", "key [API_KEY]"],
  ["aws AKIAIOSFODNN7EXAMPLE", "aws [API_KEY]"],
  ["phone +972 54-123-4567", "phone [PHONE]"],
  ["call 054-123-4567 now", "call [PHONE] now"],
  ["ip 192.168.1.10", "ip [IP_ADDRESS]"],
  ["id 123456782", "id [ISRAELI_ID]"],
  ["IBAN GB82 WEST 1234 5698 7654 32", "IBAN [IBAN]"],
];

const untouched = [
  "version 1.2.3 and year 2026",
  "not a card 1234 5678 9012 3456",
  "order 123456789", // fails Israeli ID checksum
  "already masked: [EMAIL] [PHONE]",
];

for (const [input, expected] of masked) {
  test(`masks: ${input}`, () => assert.strictEqual(maskText(input).text, expected));
}

for (const input of untouched) {
  test(`leaves alone: ${input}`, () => assert.strictEqual(maskText(input).text, input));
}

test("reports one match per finding", () => {
  const { matches } = maskText("a@b.co and c@d.io, 4111111111111111");
  assert.deepStrictEqual(matches.map((m) => m.type), ["EMAIL", "EMAIL", "CREDIT_CARD"]);
});
