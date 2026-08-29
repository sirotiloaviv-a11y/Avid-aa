"""Machine-readable output for pipelines and dashboards."""

from __future__ import annotations

import json
from pathlib import Path

from ..scanner import ScanResult
from ..version import __version__


def render_json(result: ScanResult, root: Path) -> str:
    payload = {
        "tool": "moat",
        "version": __version__,
        "root": str(Path(root).resolve()),
        "summary": {
            "files_scanned": len(result.targets),
            "findings": len(result.findings),
            "suppressed": result.suppressed,
            "by_severity": result.counts(),
            "worst": result.worst.label if result.worst else None,
        },
        "findings": [
            {
                "rule": finding.rule_id,
                "title": finding.title,
                "severity": finding.severity.label,
                "file": str(finding.path),
                "line": finding.line,
                "impact": finding.impact,
                "remediation": finding.remediation,
                "evidence": finding.evidence,
                "fingerprint": finding.fingerprint,
                **({"details": finding.meta} if finding.meta else {}),
            }
            for finding in result.findings
        ],
        "errors": result.errors,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)
