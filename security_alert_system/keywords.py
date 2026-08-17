"""Hebrew security-keyword matching.

Hebrew text needs a bit more care than a plain substring search:

* Words take attached prefixes (``ב``, ``ה``, ``ו``, ``כ``, ``ל``, ``מ``, ``ש``),
  so "בפיגוע" and "והפיגוע" must both match the keyword "פיגוע".
* Words take inflectional suffixes, so "פיגועים" must match too.
* News copy contains niqqud, geresh/gershayim variants and RTL control marks
  that break naive comparisons.
* Multi-word phrases such as "צבע אדום" may be separated by newlines or
  multiple spaces after HTML stripping.

The matcher below normalises the text once and compiles one regex per rule.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum

# Letters that can be glued to the front of a Hebrew word.
_PREFIX_LETTERS = "בהוכלמש"
# Any Hebrew letter, used for suffix tolerance and word-boundary lookarounds.
_HEBREW_LETTER = r"א-ת"
# Niqqud (vowel points), cantillation marks and Hebrew punctuation.
_NIQQUD = re.compile(r"[֑-ׇ]")
# Bidi control characters, zero-width joiners, BOM.
_INVISIBLE = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
_WHITESPACE = re.compile(r"\s+")


class Severity(IntEnum):
    """How loudly an alert should shout. Higher is more urgent."""

    INFO = 1
    ELEVATED = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def emoji(self) -> str:
        return {
            Severity.INFO: "ℹ️",
            Severity.ELEVATED: "⚠️",
            Severity.HIGH: "🚨",
            Severity.CRITICAL: "🔴",
        }[self]

    @property
    def hebrew(self) -> str:
        return {
            Severity.INFO: "מידע",
            Severity.ELEVATED: "מוגברת",
            Severity.HIGH: "גבוהה",
            Severity.CRITICAL: "קריטית",
        }[self]


def normalize(text: str) -> str:
    """Strip niqqud/invisibles and collapse whitespace, preserving letters."""
    text = unicodedata.normalize("NFKC", text)
    text = _NIQQUD.sub("", text)
    text = _INVISIBLE.sub("", text)
    text = text.replace("׳", "'").replace("״", '"')
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class KeywordRule:
    """A single phrase to watch for.

    Args:
        phrase: The phrase in Hebrew (or any language).
        severity: Urgency assigned to a match.
        allow_affixes: Master switch for loose matching. Turn this off for
            phrases where any fuzziness would produce noise.
        allow_prefixes: Tolerate attached prefix letters on the first word.
            Turn this off for short words where a prefix creates a different
            word entirely — "טילים" with a מ prefix becomes "מטילים" (a verb),
            and "אש" with a ה prefix becomes "האש" but with כ becomes "כאש".
        max_suffix: How many trailing Hebrew letters to tolerate on the final
            word. Set to 0 to require the exact form. Keep it low for short
            words: "מטח" with two tolerated letters also matches "מטחנה".
    """

    phrase: str
    severity: Severity = Severity.HIGH
    allow_affixes: bool = True
    allow_prefixes: bool = True
    max_suffix: int = 3
    pattern: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pattern", self._compile())

    def _compile(self) -> re.Pattern[str]:
        words = normalize(self.phrase).split(" ")
        parts: list[str] = []
        for index, word in enumerate(words):
            escaped = re.escape(word)
            is_first, is_last = index == 0, index == len(words) - 1
            fuzzy = self.allow_affixes and self._is_hebrew(word)
            if fuzzy and is_last and word.endswith("ה") and len(word) > 2:
                # Feminine nouns pluralise by replacing the final ה, which a
                # trailing-letter window can never reach: רקטה → רקטות,
                # אזעקה → אזעקות, דקירה → דקירות.
                escaped = re.escape(word[:-1]) + "(?:ה|ות|ת)"
            if fuzzy and is_first and self.allow_prefixes:
                escaped = f"[{_PREFIX_LETTERS}]{{0,2}}" + escaped
            if fuzzy and is_last and self.max_suffix > 0:
                escaped += f"[{_HEBREW_LETTER}]{{0,{self.max_suffix}}}"
            parts.append(escaped)
        # Words in a phrase may be separated by any run of whitespace.
        body = r"\s+".join(parts)
        # Hebrew has no case and \b misbehaves around Hebrew, so use explicit
        # lookarounds against "letter-ish" characters instead.
        boundary = rf"[{_HEBREW_LETTER}\w]"
        return re.compile(rf"(?<!{boundary}){body}(?!{boundary})", re.IGNORECASE)

    @staticmethod
    def _is_hebrew(word: str) -> bool:
        return bool(re.search(f"[{_HEBREW_LETTER}]", word))

    def search(self, normalized_text: str) -> str | None:
        """Return the matched substring, or ``None``."""
        match = self.pattern.search(normalized_text)
        return match.group(0) if match else None


@dataclass(frozen=True)
class Match:
    rule: KeywordRule
    matched_text: str

    @property
    def phrase(self) -> str:
        return self.rule.phrase

    @property
    def severity(self) -> Severity:
        return self.rule.severity


# --------------------------------------------------------------------------
# Default rule set. Override entirely via the KEYWORDS env var, or edit here.
# --------------------------------------------------------------------------
DEFAULT_RULES: tuple[KeywordRule, ...] = (
    # --- CRITICAL: an attack or incursion is happening -------------------
    # "צבע אדום" is an exact siren phrase — affix tolerance would only add noise.
    KeywordRule("צבע אדום", Severity.CRITICAL, allow_affixes=False),
    KeywordRule("היכנסו למרחב המוגן", Severity.CRITICAL, allow_affixes=False),
    KeywordRule("פיגוע", Severity.CRITICAL),
    KeywordRule("אירוע ביטחוני", Severity.CRITICAL),
    KeywordRule("אירוע ירי", Severity.CRITICAL),
    KeywordRule("אירוע דקירה", Severity.CRITICAL),
    KeywordRule("אירוע דריסה", Severity.CRITICAL),
    KeywordRule("אירוע רב נפגעים", Severity.CRITICAL),
    KeywordRule("מחבל", Severity.CRITICAL),
    KeywordRule("חדירת מחבלים", Severity.CRITICAL),
    KeywordRule("חשד לחדירה", Severity.CRITICAL),
    KeywordRule("חדירה לשטח", Severity.CRITICAL),
    KeywordRule("פריצת גבול", Severity.CRITICAL),
    KeywordRule("ירי לעבר", Severity.CRITICAL),
    KeywordRule("חילופי אש", Severity.CRITICAL),
    KeywordRule("חטיפה", Severity.CRITICAL),
    KeywordRule("כוננות ספיגה", Severity.CRITICAL),

    # --- HIGH: rockets, aircraft, casualties, explosives -----------------
    # These cover their own plurals: אזעקות, שיגורים, רקטות.
    KeywordRule("אזעקה", Severity.HIGH),
    KeywordRule("שיגור", Severity.HIGH),
    KeywordRule("רקטה", Severity.HIGH),
    # "טילים" takes no prefix: מ + טילים = "מטילים", an unrelated verb.
    KeywordRule("טילים", Severity.HIGH, allow_prefixes=False, max_suffix=0),
    KeywordRule("ירי טילים", Severity.HIGH),
    KeywordRule("טיל בליסטי", Severity.HIGH),
    # "מטח" keeps a short suffix window: two letters would also match "מטחנה".
    KeywordRule("מטח", Severity.HIGH, max_suffix=1),
    KeywordRule("מרגמות", Severity.HIGH),
    KeywordRule("פצצת מרגמה", Severity.HIGH),
    KeywordRule("נפילות", Severity.HIGH, max_suffix=0),
    KeywordRule("כלי טיס עוין", Severity.HIGH),
    KeywordRule("כלי טיס חשוד", Severity.HIGH),
    KeywordRule("חדירת כלי טיס", Severity.HIGH),
    KeywordRule("רחפן", Severity.HIGH),
    KeywordRule('כטב"ם', Severity.HIGH),
    KeywordRule("פצוע", Severity.HIGH),
    KeywordRule("הרוג", Severity.HIGH),
    KeywordRule("נפגעים", Severity.HIGH, max_suffix=0),
    KeywordRule("דקירה", Severity.HIGH),
    KeywordRule("דריסה", Severity.HIGH),
    KeywordRule("פיצוץ", Severity.HIGH),
    KeywordRule("פצצה", Severity.HIGH),
    KeywordRule("מטען חבלה", Severity.HIGH),
    KeywordRule("מארב", Severity.HIGH),
    KeywordRule("ירי צלפים", Severity.HIGH),
    KeywordRule("נוטרל", Severity.HIGH),
    KeywordRule("תקיפה", Severity.HIGH),
    KeywordRule("טרור", Severity.HIGH),

    # --- ELEVATED: context, response and precaution ----------------------
    KeywordRule("פיקוד העורף", Severity.ELEVATED),
    KeywordRule("כוחות הביטחון", Severity.ELEVATED),
    KeywordRule("כוחות ההצלה", Severity.ELEVATED),
    KeywordRule("חשד לירי", Severity.ELEVATED),
    KeywordRule("מרחב מוגן", Severity.ELEVATED),
    KeywordRule("מקלט", Severity.ELEVATED),
    KeywordRule('ממ"ד', Severity.ELEVATED),
    KeywordRule("כוננות", Severity.ELEVATED),
    KeywordRule("הסלמה", Severity.ELEVATED),
    KeywordRule("חילוץ", Severity.ELEVATED),
    KeywordRule("סריקות", Severity.ELEVATED, max_suffix=0),
    KeywordRule("זירת האירוע", Severity.ELEVATED),
    KeywordRule("אירוע חריג", Severity.ELEVATED),
    KeywordRule("עוצר", Severity.ELEVATED),
    KeywordRule('מד"א', Severity.ELEVATED),
)


class KeywordMatcher:
    """Matches a collection of :class:`KeywordRule` against free text."""

    def __init__(self, rules: tuple[KeywordRule, ...] | list[KeywordRule] | None = None):
        self.rules = tuple(rules) if rules else DEFAULT_RULES

    def find_all(self, *texts: str | None) -> list[Match]:
        """Return every rule that matches any of ``texts``, most severe first."""
        blob = normalize(" \n ".join(t for t in texts if t))
        if not blob:
            return []
        matches = [
            Match(rule, hit)
            for rule in self.rules
            if (hit := rule.search(blob)) is not None
        ]
        matches.sort(key=lambda m: m.severity, reverse=True)
        return matches

    def top_severity(self, matches: list[Match]) -> Severity:
        return max((m.severity for m in matches), default=Severity.INFO)

    @classmethod
    def from_spec(cls, spec: str) -> "KeywordMatcher":
        """Build a matcher from a config string.

        Format: comma-separated entries, each ``phrase`` or ``phrase:SEVERITY``.
        Wrapping a phrase in quotes disables affix tolerance (exact phrase).

            פיגוע:CRITICAL, "צבע אדום":CRITICAL, אזעקה:HIGH
        """
        rules: list[KeywordRule] = []
        for raw in spec.split(","):
            entry = raw.strip()
            if not entry:
                continue
            phrase, _, sev = entry.rpartition(":")
            if not phrase:
                phrase, sev = entry, "HIGH"
            exact = False
            phrase = phrase.strip()
            if len(phrase) >= 2 and phrase[0] == phrase[-1] and phrase[0] in "\"'":
                phrase, exact = phrase[1:-1], True
            try:
                severity = Severity[sev.strip().upper()]
            except KeyError:
                severity = Severity.HIGH
            rules.append(KeywordRule(phrase, severity, allow_affixes=not exact))
        return cls(rules)
