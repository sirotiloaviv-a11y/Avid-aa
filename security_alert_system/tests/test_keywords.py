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


class TestExpandedKeywords(unittest.TestCase):
    """Coverage for the enlarged default list and its false-positive guards."""

    def setUp(self):
        self.matcher = KeywordMatcher(DEFAULT_RULES)

    def _phrases(self, text: str) -> set[str]:
        return {m.phrase for m in self.matcher.find_all(text)}

    def test_new_critical_keywords(self):
        cases = {
            "אירוע ירי": "דיווח על אירוע ירי סמוך למחסום",
            "מחבל": "המחבל נמלט מהזירה",
            "פריצת גבול": "חשש לפריצת גבול בגזרה",
            "חילופי אש": "מתנהלים חילופי אש בין הכוחות",
            "חטיפה": "ניסיון חטיפה נכשל",
            "חדירה לשטח": "התרעה על חדירה לשטח היישוב",
            "אירוע רב נפגעים": "הוכרז אירוע רב נפגעים",
        }
        for phrase, text in cases.items():
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self._phrases(text))

    def test_new_high_keywords(self):
        cases = {
            "רקטה": "רקטות נורו לעבר האזור",
            "ירי טילים": "ירי טילים לעבר המרכז",
            "מטח": "במטח שנורה נפגעו מבנים",
            "פצצת מרגמה": "פצצת מרגמה נפלה בשטח פתוח",
            "דריסה": "ניסיון דריסה בצומת",
            "מארב": "הכוח נקלע למארב",
            "נוטרל": "המחבל נוטרל על ידי הכוחות",
            "נפגעים": "אין נפגעים בנפש",
        }
        for phrase, text in cases.items():
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self._phrases(text))

    def test_new_elevated_keywords(self):
        cases = {
            "מרחב מוגן": "יש לשהות במרחב מוגן",
            "הסלמה": "חשש להסלמה בגזרה",
            "כוננות": "הכוחות בכוננות גבוהה",
            "זירת האירוע": "כוחות הגיעו לזירת האירוע",
        }
        for phrase, text in cases.items():
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self._phrases(text))

    def test_gershayim_abbreviations_match(self):
        # Hebrew gershayim (״) is normalised to an ASCII quote before matching.
        self.assertIn('מד"א', self._phrases("צוותי מד״א פינו את הפצוע"))
        self.assertIn('כטב"ם', self._phrases("כטב״ם חדר לשטח"))

    def test_prefix_off_avoids_verb_collision(self):
        # מ + טילים = "מטילים" ("they cast"), which must not raise an alert.
        self.assertNotIn("טילים", self._phrases("העובדים מטילים את היסודות"))
        self.assertIn("ירי טילים", self._phrases("ירי טילים לעבר הצפון"))

    def test_short_suffix_window_avoids_collision(self):
        # מטח + "נה" would be "מטחנה" (a grinder) if the window were wider.
        self.assertNotIn("מטח", self._phrases("קנה מטחנה חדשה למטבח"))
        self.assertIn("מטח", self._phrases("נורה מטח לעבר היישוב"))

    def test_benign_news_text_stays_silent(self):
        benign = [
            "מזג האוויר נעים והתנועה זורמת",
            "קבוצת הכדורגל ניצחה במשחק אמש",
            "מדד המחירים לצרכן עלה ברבע אחוז",
        ]
        for text in benign:
            with self.subTest(text=text):
                self.assertEqual(self._phrases(text), set())

    def test_every_default_rule_matches_its_own_phrase(self):
        # Guards against a typo silently producing a rule that can never fire.
        for rule in DEFAULT_RULES:
            with self.subTest(phrase=rule.phrase):
                self.assertIsNotNone(rule.search(normalize(rule.phrase)))

    def test_no_duplicate_default_phrases(self):
        phrases = [r.phrase for r in DEFAULT_RULES]
        self.assertEqual(len(phrases), len(set(phrases)))


class TestAffixControls(unittest.TestCase):
    def test_allow_prefixes_false(self):
        rule = KeywordRule("טילים", Severity.HIGH, allow_prefixes=False, max_suffix=0)
        self.assertIsNotNone(rule.search(normalize("ירי טילים")))
        self.assertIsNone(rule.search(normalize("מטילים")))

    def test_max_suffix_zero_requires_exact_form(self):
        rule = KeywordRule("נפילות", Severity.HIGH, max_suffix=0)
        self.assertIsNotNone(rule.search(normalize("דווח על נפילות")))
        self.assertIsNone(rule.search(normalize("נפילותיהם")))

    def test_prefixes_still_work_with_zero_suffix(self):
        rule = KeywordRule("נפילות", Severity.HIGH, max_suffix=0)
        self.assertIsNotNone(rule.search(normalize("הנפילות נרשמו")))

    def test_feminine_plural_alternation(self):
        # A trailing-letter window cannot reach these: the final ה is replaced.
        for singular, plural in [
            ("רקטה", "רקטות"),
            ("אזעקה", "אזעקות"),
            ("דקירה", "דקירות"),
            ("תקיפה", "תקיפות"),
        ]:
            with self.subTest(word=singular):
                rule = KeywordRule(singular, Severity.HIGH)
                self.assertIsNotNone(rule.search(normalize(singular)))
                self.assertIsNotNone(rule.search(normalize(f"דיווח על {plural}")))

    def test_alternation_respects_exact_rules(self):
        rule = KeywordRule("דקירה", Severity.HIGH, allow_affixes=False)
        self.assertIsNone(rule.search(normalize("דקירות")))


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
