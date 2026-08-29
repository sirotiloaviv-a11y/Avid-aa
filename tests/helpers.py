"""Shared fixtures: build a throwaway project tree and scan it."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from moat.discovery import load_target
from moat.models import Target
from moat.scanner import scan


class ProjectTestCase(unittest.TestCase):
    """Writes agent config into a temporary project and scans it."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="moat-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, relative: str, content) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (dict, list)):
            content = json.dumps(content, indent=2)
        path.write_text(content, encoding="utf-8")
        return path

    def target(self, relative: str, content) -> Target:
        target = load_target(self.write(relative, content))
        assert target is not None, f"{relative} was not recognised as agent config"
        return target

    def findings(self, **kwargs):
        return scan(self.root, **kwargs).findings

    def rule_ids(self, **kwargs) -> list[str]:
        return [f.rule_id for f in self.findings(**kwargs)]

    def assertFinds(self, rule_id: str, findings=None, msg: str = ""):
        found = [f.rule_id for f in (findings if findings is not None else self.findings())]
        self.assertIn(rule_id, found, msg or f"expected {rule_id}, got {found}")

    def assertClean(self, rule_id: str, findings=None):
        found = [f.rule_id for f in (findings if findings is not None else self.findings())]
        self.assertNotIn(rule_id, found, f"false positive: {rule_id} in {found}")


def run_rule(rule_fn, target: Target) -> list:
    return list(rule_fn(target))
