"""The shipped examples are documentation, so they are tested like code.

If a rule change silently stops flagging the vulnerable project, or starts
flagging the hardened one, the README stops being true.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from moat.models import Severity
from moat.scanner import scan

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class TestVulnerableExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(EXAMPLES / "vulnerable-agent-project")

    def test_every_rule_family_fires(self):
        families = {f.rule_id.rsplit("-", 1)[0] for f in self.result.findings}
        self.assertEqual(
            families,
            {
                "MOAT-SECRET",
                "MOAT-PERM",
                "MOAT-SUPPLY",
                "MOAT-HOOK",
                "MOAT-INJECT",
                "MOAT-TRIFECTA",
            },
        )

    def test_the_main_agent_and_the_subagent_both_trip_the_trifecta(self):
        principals = {
            f.meta["principal"] for f in self.result.findings if f.rule_id == "MOAT-TRIFECTA-001"
        }
        self.assertEqual(len(principals), 2)

    def test_worst_finding_is_critical(self):
        self.assertEqual(self.result.worst, Severity.CRITICAL)

    def test_no_credential_appears_in_the_report(self):
        raw = (EXAMPLES / "vulnerable-agent-project" / ".mcp.json").read_text()
        token = next(part for part in raw.split('"') if part.startswith("ghp_"))
        for finding in self.result.findings:
            self.assertNotIn(token, finding.evidence + finding.impact + finding.title)


class TestHardenedExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = scan(EXAMPLES / "hardened-agent-project")

    def test_nothing_above_low(self):
        offenders = [
            f"{f.rule_id}: {f.title}" for f in self.result.findings if f.severity > Severity.LOW
        ]
        self.assertEqual(offenders, [], "the hardened example must stay clean")

    def test_the_read_only_subagent_is_the_teaching_case(self):
        subagent = [
            f
            for f in self.result.findings
            if f.rule_id == "MOAT-TRIFECTA-002" and "issue-triage" in f.meta.get("principal", "")
        ]
        self.assertEqual(len(subagent), 1)
        self.assertEqual(subagent[0].meta["missing"], ["exfil"])


if __name__ == "__main__":
    unittest.main()
