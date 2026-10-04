/*
 * PII detection rules shared by the content script.
 *
 * Loaded as a classic script before content.js (content scripts cannot be ES
 * modules), so it exposes a single global: ShadowPII. Also exportable under
 * Node for unit tests.
 */
(function (root) {
  "use strict";

  function luhnValid(digits) {
    let sum = 0;
    let double = false;
    for (let i = digits.length - 1; i >= 0; i--) {
      let d = digits.charCodeAt(i) - 48;
      if (double) {
        d *= 2;
        if (d > 9) d -= 9;
      }
      sum += d;
      double = !double;
    }
    return sum % 10 === 0;
  }

  function israeliIdValid(id) {
    if (!/^\d{9}$/.test(id)) return false;
    let sum = 0;
    for (let i = 0; i < 9; i++) {
      let d = (id.charCodeAt(i) - 48) * ((i % 2) + 1);
      if (d > 9) d -= 9;
      sum += d;
    }
    return sum % 10 === 0;
  }

  // Order matters: earlier rules win when matches overlap.
  const RULES = [
    {
      type: "API_KEY",
      label: "API key / secret",
      re: /\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|AIza[0-9A-Za-z_-]{35}|xox[abpr]-[A-Za-z0-9-]{10,})\b/g,
    },
    {
      type: "EMAIL",
      label: "Email address",
      re: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
    },
    {
      type: "CREDIT_CARD",
      label: "Credit card",
      re: /\b(?:\d[ -]?){12,18}\d\b/g,
      validate: (m) => {
        const digits = m.replace(/\D/g, "");
        return digits.length >= 13 && digits.length <= 19 && luhnValid(digits);
      },
    },
    {
      type: "IBAN",
      label: "IBAN",
      re: /\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b/g,
    },
    {
      type: "SSN",
      label: "US SSN",
      re: /\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b/g,
    },
    {
      type: "ISRAELI_ID",
      label: "Israeli ID",
      re: /\b\d{9}\b/g,
      validate: israeliIdValid,
    },
    {
      type: "PHONE",
      label: "Phone number",
      // Boundaries reject digit runs that continue past the match, so a long
      // number that failed the Luhn check is not re-captured as a phone.
      re: /(?<![\w+]|\d[ .-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{1,4}\)[ .-]?)?\d{2,4}[ .-]\d{3,4}[ .-]?\d{3,4}(?![ .-]?\d)\b/g,
      validate: (m) => {
        const n = m.replace(/\D/g, "").length;
        return n >= 9 && n <= 15;
      },
    },
    {
      type: "IP_ADDRESS",
      label: "IP address",
      re: /\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/g,
    },
  ];

  const LABELS = Object.fromEntries(RULES.map((r) => [r.type, r.label]));

  function placeholder(type) {
    return "[" + type + "]";
  }

  /** Returns non-overlapping matches sorted by start offset. */
  function findMatches(text) {
    const found = [];
    for (const rule of RULES) {
      rule.re.lastIndex = 0;
      let m;
      while ((m = rule.re.exec(text)) !== null) {
        const value = m[0];
        if (rule.validate && !rule.validate(value)) continue;
        const start = m.index;
        const end = start + value.length;
        if (found.some((f) => start < f.end && end > f.start)) continue;
        found.push({ type: rule.type, start, end });
      }
    }
    return found.sort((a, b) => a.start - b.start);
  }

  /** Replaces every match with its placeholder. */
  function maskText(text) {
    const matches = findMatches(text);
    if (matches.length === 0) return { text, matches };
    let out = "";
    let pos = 0;
    for (const m of matches) {
      out += text.slice(pos, m.start) + placeholder(m.type);
      pos = m.end;
    }
    out += text.slice(pos);
    return { text: out, matches };
  }

  const api = { RULES, LABELS, findMatches, maskText, placeholder };
  root.ShadowPII = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
