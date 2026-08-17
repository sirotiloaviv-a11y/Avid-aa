"""Tests for the Hebrew keyword matcher.

Run:  python -m unittest discover -s security_alert_system/tests -t .
"""

from __future__ import annotations

import unittest

from security_alert_system.keywords import (
    DEFAULT_RULES,
    KeywordMatcher,
    KeywordRule,
    Severity,
    normalize,
)


class TestNormalize(unittest.TestCase):
    def test_strips_niqqud(self):
        self.assertEqual(normalize("פִּיגוּעַ"), "פיגוע")

    def test_collapses_whitespace_and_newlines(self):
        self.assertEqual(normalize("צבע  \n  אדום"), "צבע אדום")

    def test_strips_bidi_marks(self):
        self.assertEqual(normalize("‏פיגוע‎"), "פיגוע")


class TestMatching(unittest.TestCase):
    def setUp(self):
        self.matcher = KeywordMatcher(DEFAULT_RULES)

    def _phrases(self, text: str) -> set[str]:
        return {m.phrase for m in self.matcher.find_all(text)}

    def test_plain_keyword(self):
        self.assertIn("פיגוע", self._phrases("דיווח על פיגוע בעיר"))

    def test_keyword_with_attached_prefix(self):
        self.assertIn("פיגוע", self._phrases("נפצעו בפיגוע הבוקר"))
        self.assertIn("פיגוע", self._phrases("והפיגוע התרחש אתמול"))

    def test_keyword_with_plural_suffix(self):
        self.assertIn("פיגוע", self._phrases("שני פיגועים ביממה"))

    def test_multiword_phrase_across_newline(self):
        self.assertIn("צבע אדום", self._phrases("אזעקת\nצבע אדום נשמעה"))

    def test_security_event_phrase(self):
        self.assertIn("אירוע ביטחוני", self._phrases("מדובר באירוע ביטחוני חמור"))

    def test_severity_is_highest_match(self):
        matches = self.matcher.find_all("אזעקה נשמעה בעקבות פיגוע")
        self.assertEqual(self.matcher.top_severity(matches), Severity.CRITICAL)
        # Most severe match sorts first.
        self.assertEqual(matches[0].severity, Severity.CRITICAL)

    def test_no_false_positive_on_unrelated_text(self):
        self.assertEqual(self._phrases("מזג האוויר נעים והתנועה זורמת"), set())

    def test_word_boundary_prevents_substring_hit(self):
        # "אדום" alone must not trigger the "צבע אדום" rule.
        self.assertNotIn("צבע אדום", self._phrases("הדגל בצבע אדום כהה"))

    def test_exact_rule_rejects_affixes(self):
        rule = KeywordRule("צבע אדום", Severity.CRITICAL, allow_affixes=False)
        self.assertIsNotNone(rule.search(normalize("הופעל צבע אדום")))
        self.assertIsNone(rule.search(normalize("צבעים אדומים")))

    def test_html_entities_and_punctuation(self):
        self.assertIn("פיגוע", self._phrases("«פיגוע» באזור, לפי הדיווח."))


class TestFromSpec(unittest.TestCase):
    def test_parses_phrases_and_severities(self):
        matcher = KeywordMatcher.from_spec('פיגוע:CRITICAL, "צבע אדום":CRITICAL, אזעקה:HIGH')
        self.assertEqual(len(matcher.rules), 3)
        by_phrase = {r.phrase: r for r in matcher.rules}
        self.assertEqual(by_phrase["פיגוע"].severity, Severity.CRITICAL)
        self.assertEqual(by_phrase["אזעקה"].severity, Severity.HIGH)
        self.assertFalse(by_phrase["צבע אדום"].allow_affixes)

    def test_defaults_to_high_without_severity(self):
        matcher = KeywordMatcher.from_spec("פיגוע")
        self.assertEqual(matcher.rules[0].severity, Severity.HIGH)

    def test_unknown_severity_falls_back(self):
        matcher = KeywordMatcher.from_spec("פיגוע:BOGUS")
        self.assertEqual(matcher.rules[0].severity, Severity.HIGH)


if __name__ == "__main__":
    unittest.main()
