"""Discovery, parsing, filtering and output formats."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from moat.discovery import classify, discover
from moat.loader import load_frontmatter, load_json, strip_jsonc
from moat.models import MCP_CONFIG, Severity
from moat.reporters import render_json, render_sarif, render_terminal
from moat.scanner import scan
from tests.helpers import ProjectTestCase


class TestLoader(unittest.TestCase):
    def test_strips_line_and_block_comments(self):
        data, error = load_json('{\n  // note\n  "a": 1, /* x */ "b": 2\n}')
        self.assertIsNone(error)
        self.assertEqual(data, {"a": 1, "b": 2})

    def test_tolerates_trailing_commas(self):
        data, _ = load_json('{"a": [1, 2,],}')
        self.assertEqual(data, {"a": [1, 2]})

    def test_does_not_strip_slashes_inside_strings(self):
        data, _ = load_json('{"url": "https://example.com//path"}')
        self.assertEqual(data["url"], "https://example.com//path")

    def test_reports_unparseable_input(self):
        data, error = load_json("{ not json at all")
        self.assertEqual(data, {})
        self.assertIsNotNone(error)

    def test_frontmatter_split(self):
        data, body = load_frontmatter("---\nname: x\ntools: Read, Bash\n---\nBody text\n")
        self.assertEqual(data["name"], "x")
        self.assertEqual(body.strip(), "Body text")

    def test_no_frontmatter_keeps_the_whole_body(self):
        data, body = load_frontmatter("Just markdown.\n")
        self.assertEqual(data, {})
        self.assertEqual(body, "Just markdown.\n")


class TestDiscovery(ProjectTestCase):
    def test_recognises_each_config_flavour(self):
        self.assertEqual(classify(Path(".mcp.json")), "mcp_config")
        self.assertEqual(classify(Path("claude_desktop_config.json")), "mcp_config")
        self.assertEqual(classify(Path("p/.claude/settings.json")), "agent_settings")
        self.assertEqual(classify(Path("p/.claude/agents/a.md")), "agent_definition")
        self.assertEqual(classify(Path("p/.claude/skills/s/SKILL.md")), "skill_definition")
        self.assertIsNone(classify(Path("package.json")))

    def test_skips_dependency_directories(self):
        self.write("node_modules/pkg/.mcp.json", {"mcpServers": {}})
        self.write(".mcp.json", {"mcpServers": {}})
        self.assertEqual([p.name for p in discover(self.root)], [".mcp.json"])

    def test_scanning_a_single_file_works(self):
        path = self.write(".mcp.json", {"mcpServers": {}})
        self.assertEqual(discover(path), [path])

    def test_unparseable_config_is_reported_not_skipped(self):
        # A config the host cannot parse enforces nothing, which is worth saying.
        self.write(".claude/settings.json", "{ oops")
        result = scan(self.root)
        self.assertIn("MOAT-PARSE-001", [f.rule_id for f in result.findings])
        self.assertTrue(result.errors)


class TestFiltering(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.write(
            ".claude/settings.json",
            {"permissions": {"defaultMode": "bypassPermissions", "allow": ["Bash(*)"]}},
        )
        # A subagent with no tool list is MEDIUM, so the fixture spans severities.
        self.write(".claude/agents/a.md", "---\nname: a\ndescription: d\n---\n\nBody.\n")

    def test_min_severity_hides_lower_findings(self):
        everything = scan(self.root)
        critical_only = scan(self.root, min_severity=Severity.CRITICAL)
        self.assertTrue(len(critical_only.findings) < len(everything.findings))
        self.assertTrue(all(f.severity == Severity.CRITICAL for f in critical_only.findings))

    def test_disabling_a_rule_removes_it(self):
        result = scan(self.root, disabled={"MOAT-PERM-001"})
        self.assertNotIn("MOAT-PERM-001", [f.rule_id for f in result.findings])

    def test_baseline_suppresses_known_findings(self):
        first = scan(self.root)
        baseline = self.write(
            "baseline.json", {"fingerprints": [f.fingerprint for f in first.findings]}
        )
        second = scan(self.root, baseline=baseline)
        self.assertEqual(second.findings, [])
        self.assertEqual(second.suppressed, len(first.findings))

    def test_fingerprint_survives_reformatting(self):
        before = {f.fingerprint for f in scan(self.root).findings}
        self.write(
            ".claude/settings.json",
            "\n\n{\n\n  // reformatted\n"
            '  "permissions": { "defaultMode": "bypassPermissions", "allow": ["Bash(*)"] }\n}\n',
        )
        after = {f.fingerprint for f in scan(self.root).findings}
        self.assertTrue(before & after, "reformatting should not invalidate a baseline")

    def test_findings_are_sorted_worst_first(self):
        severities = [f.severity for f in scan(self.root).findings]
        self.assertEqual(severities, sorted(severities, reverse=True))

    def test_a_failing_rule_does_not_lose_the_others(self):
        from moat.rules import REGISTRY, load_all

        load_all()
        broken = type(REGISTRY[0])(
            id="MOAT-TEST-BOOM",
            name="explodes",
            kinds=("agent_settings",),
            check=lambda target: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        REGISTRY.append(broken)
        self.addCleanup(REGISTRY.remove, broken)
        result = scan(self.root)
        self.assertTrue(result.findings)
        self.assertTrue(any("boom" in e for e in result.errors))


class TestReporters(ProjectTestCase):
    def setUp(self):
        super().setUp()
        self.write(
            ".claude/settings.json",
            {"permissions": {"defaultMode": "bypassPermissions", "allow": ["Bash(*)"]}},
        )
        self.result = scan(self.root)

    def test_json_is_valid_and_complete(self):
        payload = json.loads(render_json(self.result, self.root))
        self.assertEqual(payload["summary"]["findings"], len(self.result.findings))
        self.assertTrue(all("fingerprint" in f for f in payload["findings"]))
        self.assertTrue(all(f["remediation"] for f in payload["findings"]))

    def test_sarif_shape_matches_the_spec(self):
        document = json.loads(render_sarif(self.result, self.root))
        self.assertEqual(document["version"], "2.1.0")
        run = document["runs"][0]
        self.assertEqual(run["tool"]["driver"]["name"], "moat")
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        for item in run["results"]:
            self.assertIn(item["ruleId"], rule_ids)
            self.assertIn(item["level"], ("error", "warning", "note"))
            self.assertGreaterEqual(
                item["locations"][0]["physicalLocation"]["region"]["startLine"], 1
            )

    def test_sarif_paths_are_relative_to_the_scan_root(self):
        document = json.loads(render_sarif(self.result, self.root))
        uri = document["runs"][0]["results"][0]["locations"][0]["physicalLocation"][
            "artifactLocation"
        ]["uri"]
        self.assertFalse(uri.startswith("/"))

    def test_terminal_output_is_plain_without_a_tty(self):
        text = render_terminal(self.result, self.root, stream=io.StringIO())
        self.assertNotIn("\033[", text)
        self.assertIn("MOAT-PERM-001", text)

    def test_clean_scan_says_so(self):
        empty_dir = self.root / "empty"
        empty_dir.mkdir()
        text = render_terminal(scan(empty_dir), empty_dir, stream=io.StringIO())
        self.assertIn("No findings", text)


if __name__ == "__main__":
    unittest.main()
