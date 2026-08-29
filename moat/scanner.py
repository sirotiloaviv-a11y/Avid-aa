"""Orchestration: discover, run every rule, filter, sort."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import collect
from .models import Finding, Severity, Target
from .rules import load_all, load_project_rules


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    suppressed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def worst(self) -> Severity | None:
        return max((f.severity for f in self.findings), default=None)

    def counts(self) -> dict[str, int]:
        tally = {severity.label: 0 for severity in reversed(Severity)}
        for finding in self.findings:
            tally[finding.severity.label] += 1
        return tally


def load_baseline(path: Path | None) -> set[str]:
    """Fingerprints a team has accepted. Missing file means an empty baseline."""
    if path is None or not Path(path).is_file():
        return set()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, dict):
        data = data.get("fingerprints", [])
    return {str(item) for item in data} if isinstance(data, list) else set()


def scan(
    root: Path,
    *,
    baseline: Path | None = None,
    min_severity: Severity = Severity.INFO,
    disabled: set[str] | None = None,
    exclude: tuple[str, ...] = (),
) -> ScanResult:
    result = ScanResult(targets=collect(Path(root), exclude))
    disabled = disabled or set()
    accepted = load_baseline(baseline)
    raw: list[Finding] = []

    for target in result.targets:
        if target.parse_error:
            result.errors.append(f"{target.path}: {target.parse_error}")
            raw.append(
                Finding(
                    rule_id="MOAT-PARSE-001",
                    title=f"{target.path.name} is not valid JSON and is silently ignored",
                    severity=Severity.MEDIUM,
                    path=target.path,
                    impact=(
                        "Hosts skip a config they cannot parse. Every restriction "
                        "written in this file is therefore not in effect, while the "
                        "file's presence suggests otherwise."
                    ),
                    remediation="Fix the syntax, then re-run to see what the file was meant to enforce.",
                    evidence=target.parse_error,
                )
            )
            continue

        for rule in load_all():
            if rule.id in disabled or not rule.applies_to(target):
                continue
            try:
                raw.extend(rule.check(target))
            except Exception as exc:  # a broken rule must not lose the other findings
                result.errors.append(f"{rule.id} failed on {target.path}: {exc}")

    parseable = [t for t in result.targets if not t.parse_error]
    for rule in load_project_rules():
        if rule.id in disabled:
            continue
        try:
            raw.extend(rule.check(parseable))
        except Exception as exc:
            result.errors.append(f"{rule.id} failed: {exc}")

    seen: set[str] = set()
    for finding in raw:
        if finding.rule_id in disabled:
            continue
        if finding.fingerprint in accepted:
            result.suppressed += 1
            continue
        if finding.severity < min_severity:
            continue
        if finding.fingerprint in seen:
            continue
        seen.add(finding.fingerprint)
        result.findings.append(finding)

    result.findings.sort(key=lambda f: (-f.severity, str(f.path), f.line, f.rule_id))
    return result
