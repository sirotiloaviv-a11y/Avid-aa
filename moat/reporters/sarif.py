"""SARIF 2.1.0 output.

GitHub code scanning, Azure DevOps and most IDEs consume SARIF, so emitting it
is what turns a scanner into something that annotates a pull request instead of
something a developer has to remember to run.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Severity
from ..scanner import ScanResult
from ..version import __version__

#: SARIF only has three levels, so severity is also carried as a numeric score.
_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}
_SCORE = {
    Severity.CRITICAL: "9.5",
    Severity.HIGH: "8.0",
    Severity.MEDIUM: "5.0",
    Severity.LOW: "3.0",
    Severity.INFO: "1.0",
}


def render_sarif(result: ScanResult, root: Path) -> str:
    root = Path(root).resolve()
    rules: dict[str, dict] = {}

    for finding in result.findings:
        rules.setdefault(
            finding.rule_id,
            {
                "id": finding.rule_id,
                "name": finding.rule_id.replace("-", ""),
                "shortDescription": {"text": finding.title[:120]},
                "fullDescription": {"text": finding.impact or finding.title},
                "help": {
                    "text": finding.remediation or "",
                    "markdown": f"**Impact**\n\n{finding.impact}\n\n**Fix**\n\n{finding.remediation}",
                },
                "defaultConfiguration": {"level": _LEVEL[finding.severity]},
                "properties": {
                    "security-severity": _SCORE[finding.severity],
                    "tags": ["security", "ai-agent", "mcp"],
                },
            },
        )

    def uri(path: Path) -> str:
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "moat",
                        "informationUri": "https://github.com/sirotiloaviv-a11y/avid-aa",
                        "version": __version__,
                        "rules": list(rules.values()),
                    }
                },
                "results": [
                    {
                        "ruleId": finding.rule_id,
                        "level": _LEVEL[finding.severity],
                        "message": {"text": f"{finding.title}. {finding.impact}"},
                        "partialFingerprints": {"moatFingerprint/v1": finding.fingerprint},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": uri(finding.path)},
                                    "region": {"startLine": max(finding.line, 1)},
                                }
                            }
                        ],
                    }
                    for finding in result.findings
                ],
            }
        ],
    }
    return json.dumps(document, indent=2, ensure_ascii=False)
