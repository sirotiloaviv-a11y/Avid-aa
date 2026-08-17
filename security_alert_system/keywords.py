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
        allow_affixes: Tolerate Hebrew prefix letters and inflectional
            suffixes. Turn this off for phrases where a loose match would
            produce noise.
        max_suffix: How many trailing Hebrew letters to tolerate on the final
            word when ``allow_affixes`` is set.
    """

    phrase: str
    severity: Severity = Severity.HIGH
    allow_affixes: bool = True
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
            if self.allow_affixes and is_first and self._is_hebrew(word):
                escaped = f"[{_PREFIX_LETTERS}]{{0,2}}" + escaped
            if self.allow_affixes and is_last and self._is_hebrew(word):
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
    # "צבע אדום" is an exact siren phrase — affix tolerance would only add noise.
    KeywordRule("צבע אדום", Severity.CRITICAL, allow_affixes=False),
    KeywordRule("פיגוע", Severity.CRITICAL),
    KeywordRule("אירוע ביטחוני", Severity.CRITICAL),
    KeywordRule("חדירת מחבלים", Severity.CRITICAL),
    KeywordRule("חשד לחדירה", Severity.CRITICAL),
    KeywordRule("ירי לעבר", Severity.CRITICAL),
    KeywordRule("אזעקה", Severity.HIGH),
    KeywordRule("אזעקות", Severity.HIGH),
    KeywordRule("שיגור", Severity.HIGH),
    KeywordRule("שיגורים", Severity.HIGH),
    KeywordRule("כלי טיס עוין", Severity.HIGH),
    KeywordRule("חדירת כלי טיס", Severity.HIGH),
    KeywordRule("רחפן", Severity.HIGH),
    KeywordRule("פצוע", Severity.HIGH),
    KeywordRule("הרוג", Severity.HIGH),
    KeywordRule("דקירה", Severity.HIGH),
    KeywordRule("פיצוץ", Severity.HIGH),
    KeywordRule("מטען חבלה", Severity.HIGH),
    KeywordRule("היכנסו למרחב המוגן", Severity.CRITICAL, allow_affixes=False),
    KeywordRule("פיקוד העורף", Severity.ELEVATED),
    KeywordRule("כוחות הביטחון", Severity.ELEVATED),
    KeywordRule("חשד לירי", Severity.ELEVATED),
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
