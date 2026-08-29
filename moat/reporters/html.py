"""Standalone HTML report.

One self-contained file: no server, no build step, no network request when it
is opened. That last property is deliberate rather than incidental — this
report is a security artefact that gets emailed around and opened on machines
that are not the one that produced it, so it must not phone a font CDN or
anything else. Typography comes from system stacks, and the hierarchy is
carried by weight, scale and the sans/mono contrast instead.

Everything rendered here originates in configuration files, which means some of
it is attacker-controlled: a poisoned MCP tool description is exactly what
MOAT-INJECT-002 exists to find. A report that rendered those strings as markup
would hand the attacker the reviewer's browser. So every value is escaped at
the boundary, invisible characters are made visible rather than passed through,
and the page's script never writes markup — it only toggles classes.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from ..models import Finding, Severity
from ..scanner import ScanResult
from ..version import __version__

#: Characters that render as nothing. Displaying them as visible tokens is both
#: the safe choice and the useful one — their invisibility is the finding.
_INVISIBLE = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f"   # C0 controls
    "\u00ad"                                       # soft hyphen
    "\u200b-\u200f\u202a-\u202e"                 # zero-width and bidi
    "\u2060-\u2064\ufeff"                         # joiners and BOM
    "\U000e0000-\U000e007f]"                       # tag characters
)

_SEVERITY_ORDER = (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)

_CAPABILITY_TITLES = {
    "private_data": "Reads private data",
    "untrusted_input": "Ingests untrusted text",
    "exfil": "Sends data outward",
}
_CAPABILITY_NOTES = {
    "private_data": "source, secrets, databases",
    "untrusted_input": "pages, issues, email",
    "exfil": "HTTP, messages, commits",
}
_CAPABILITY_OPEN = {
    "private_data": "No access to private data",
    "untrusted_input": "No untrusted input",
    "exfil": "No outbound channel",
}


def _visible(text: str) -> str:
    """Replace invisible characters with a readable token."""

    def token(match: re.Match[str]) -> str:
        char = match.group(0)
        try:
            name = unicodedata.name(char)
        except ValueError:
            name = f"U+{ord(char):04X}"
        return f"‹{name}›"

    return _INVISIBLE.sub(token, text)


def esc(text: object) -> str:
    """The only way text enters the document."""
    return html.escape(_visible(str(text)), quote=True)


_BACKTICKED = re.compile(r"`([^`]{1,120})`")


def rich(text: object) -> str:
    """Escaped text, with the prose's `backticks` promoted to inline code.

    Findings are written once and rendered to a terminal, JSON and this page, so
    the copy marks identifiers the way prose does. Escaping happens first — by
    the time this substitution runs there is no markup left in the string for a
    tag to escape from, so the only elements in the output are the ones added
    here.
    """
    return _BACKTICKED.sub(r"<code>\1</code>", esc(text))


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def _family(rule_id: str) -> str:
    return rule_id.rsplit("-", 1)[0]


def _chain(finding: Finding) -> str:
    """Render one principal's capability chain.

    The chain is the product's whole argument, so it is drawn rather than
    described: three cells, and a rail between them that is solid where the
    capability is held and broken where it is not.
    """
    witnesses = finding.meta.get("witnesses") or {}
    missing = set(finding.meta.get("missing") or [])
    complete = finding.rule_id == "MOAT-TRIFECTA-001"
    cells: list[str] = []

    order = ("private_data", "untrusted_input", "exfil")
    for index, capability in enumerate(order):
        if index:
            # A rail carries the chain only if both cells it joins are held —
            # the segment downstream of a missing link is not an active path.
            joined = {capability, order[index - 1]}
            broken = " rail--broken" if joined & missing else ""
            cells.append(f'<li class="rail{broken}" aria-hidden="true"></li>')
        if capability in missing:
            cells.append(
                '<li class="cell cell--open">'
                f'<p class="cell-title">{esc(_CAPABILITY_OPEN[capability])}</p>'
                '<p class="cell-note">the chain does not close here</p>'
                "</li>"
            )
        else:
            tool = witnesses.get(capability, "—")
            cells.append(
                '<li class="cell">'
                f'<p class="cell-title">{esc(_CAPABILITY_TITLES[capability])}</p>'
                f'<code class="cell-tool">{esc(tool)}</code>'
                f'<p class="cell-note">{esc(_CAPABILITY_NOTES[capability])}</p>'
                "</li>"
            )

    state = "complete" if complete else "incomplete"
    label = "Complete chain" if complete else "One link short"
    return (
        f'<figure class="chain chain--{state}">'
        '<figcaption class="chain-head">'
        f'<span class="chain-name">{esc(finding.meta.get("principal", "agent"))}</span>'
        f'<span class="chain-state chain-state--{state}">{esc(label)}</span>'
        "</figcaption>"
        f'<ol class="links">{"".join(cells)}</ol>'
        "</figure>"
    )


def _finding(finding: Finding, root: Path) -> str:
    location = f"{_relative(finding.path, root)}:{finding.line}"
    parts = [
        f'<article class="finding" data-severity="{finding.severity.label}" '
        f'data-family="{esc(_family(finding.rule_id))}">',
        '<header class="finding-head">',
        f'<span class="sev sev--{finding.severity.label}">{finding.severity.label}</span>',
        f"<h3>{rich(finding.title)}</h3>",
        "</header>",
        '<p class="meta">',
        f'<code class="loc">{esc(location)}</code>',
        f'<span class="rule">{esc(finding.rule_id)}</span>',
        "</p>",
    ]
    if finding.impact:
        parts.append(f'<p class="impact">{rich(finding.impact)}</p>')
    if finding.evidence:
        parts.append(
            '<div class="evidence"><span class="field-label">Evidence</span>'
            f"<code>{esc(finding.evidence)}</code></div>"
        )
    if finding.remediation:
        parts.append(
            '<div class="fix"><span class="field-label">Fix</span>'
            f"<p>{rich(finding.remediation)}</p></div>"
        )
    parts.append("</article>")
    return "".join(parts)


def _tally(result: ScanResult) -> str:
    counts = result.counts()
    tiles = [
        '<button type="button" class="tile tile--all is-active" data-filter="all">'
        f'<span class="tile-count">{len(result.findings)}</span>'
        '<span class="tile-label">All findings</span></button>'
    ]
    for severity in _SEVERITY_ORDER:
        count = counts.get(severity.label, 0)
        if not count:
            continue
        tiles.append(
            f'<button type="button" class="tile tile--{severity.label}" data-filter="{severity.label}">'
            f'<span class="tile-count">{count}</span>'
            f'<span class="tile-label">{severity.label}</span></button>'
        )
    return f'<div class="tally">{"".join(tiles)}</div>'


STYLE = """
:root {
  color-scheme: light;
  --ground: #f6f7f9;
  --surface: #ffffff;
  --surface-sunk: #f0f2f5;
  --ink: #141a22;
  --muted: #5c6673;
  --line: #e1e5eb;
  --line-strong: #c9d0d9;
  --accent: #2c6e8c;
  --critical: #b01f27;
  --high: #b85c0a;
  --medium: #8a6f00;
  --low: #3f6699;
  --info: #5c6673;
  --ok: #2c7550;
  --sev-ink: #ffffff;
  --shadow: 0 1px 2px rgba(20, 26, 34, .06), 0 8px 24px -16px rgba(20, 26, 34, .25);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #0d1117;
    --surface: #151a21;
    --surface-sunk: #1b212a;
    --ink: #e4e9f0;
    --muted: #8a94a2;
    --line: #242b35;
    --line-strong: #333c48;
    --accent: #5aa8c9;
    --critical: #f1585f;
    --high: #ee8a2c;
    --medium: #d4b42c;
    --low: #7da2d6;
    --info: #8a94a2;
    --ok: #4fae7b;
    --sev-ink: #0d1117;
    --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px -16px rgba(0, 0, 0, .8);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #0d1117;
  --surface: #151a21;
  --surface-sunk: #1b212a;
  --ink: #e4e9f0;
  --muted: #8a94a2;
  --line: #242b35;
  --line-strong: #333c48;
  --accent: #5aa8c9;
  --critical: #f1585f;
  --high: #ee8a2c;
  --medium: #d4b42c;
  --low: #7da2d6;
  --info: #8a94a2;
  --ok: #4fae7b;
  --sev-ink: #0d1117;
  --shadow: 0 1px 2px rgba(0, 0, 0, .4), 0 8px 24px -16px rgba(0, 0, 0, .8);
}

*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--ground);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}

code, .mono {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  font-size: .86em;
}

.wrap { max-width: 1080px; margin: 0 auto; padding: 0 24px; }

/* ---- banner ---------------------------------------------------------- */
.banner {
  border-bottom: 1px solid var(--line);
  background: var(--surface);
}
.banner-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 24px 24px;
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.brand-mark {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -.02em;
  color: var(--ink);
}
.brand-version {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: var(--muted);
}
h1 {
  margin: 6px 0 0;
  font-size: 26px;
  line-height: 1.2;
  font-weight: 600;
  letter-spacing: -.015em;
  text-wrap: balance;
}
.scan-meta {
  display: grid;
  grid-template-columns: auto auto;
  gap: 2px 16px;
  margin: 0;
  font-size: 12px;
}
.scan-meta dt {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .09em;
  color: var(--muted);
  align-self: center;
}
.scan-meta dd {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.theme-toggle {
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--muted);
  border-radius: 4px;
  padding: 4px 9px;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.theme-toggle:hover { color: var(--ink); border-color: var(--accent); }

/* ---- section furniture ----------------------------------------------- */
section { margin-top: 40px; }
.eyebrow {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .12em;
  color: var(--muted);
  margin: 0 0 4px;
}
h2 {
  margin: 0 0 6px;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -.01em;
}
.lede {
  margin: 0 0 18px;
  max-width: 68ch;
  color: var(--muted);
  font-size: 14px;
}

/* ---- tally ------------------------------------------------------------ */
.tally {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
}
.tile {
  flex: 1 1 110px;
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong);
  border-radius: 3px;
  background: var(--surface);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color .12s ease, background .12s ease;
}
.tile:hover { border-color: var(--line-strong); }
.tile.is-active { background: var(--surface-sunk); border-color: var(--line-strong); }
.tile:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.tile-count {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 24px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.tile-label {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .1em;
  color: var(--muted);
}
.tile--critical { border-left-color: var(--critical); }
.tile--critical .tile-count { color: var(--critical); }
.tile--high { border-left-color: var(--high); }
.tile--high .tile-count { color: var(--high); }
.tile--medium { border-left-color: var(--medium); }
.tile--medium .tile-count { color: var(--medium); }
.tile--low { border-left-color: var(--low); }
.tile--low .tile-count { color: var(--low); }
.tile--info { border-left-color: var(--info); }
.tile--all { border-left-color: var(--accent); }

/* ---- capability chains ------------------------------------------------ */
.chain {
  margin: 0 0 14px;
  padding: 16px 18px 18px;
  border: 1px solid var(--line);
  border-radius: 3px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.chain-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 14px;
}
.chain-name { font-weight: 600; font-size: 15px; }
.chain-state {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: .1em;
  padding: 3px 8px;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.chain-state--complete { color: var(--critical); }
.chain-state--incomplete { color: var(--ok); }
.links {
  display: grid;
  grid-template-columns: 1fr 24px 1fr 24px 1fr;
  align-items: stretch;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.cell {
  padding: 12px 13px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  background: var(--surface-sunk);
}
.cell--open {
  border-style: dashed;
  border-color: var(--ok);
  background: transparent;
}
.cell-title { margin: 0; font-size: 13px; font-weight: 600; line-height: 1.3; }
.cell--open .cell-title { color: var(--ok); }
.cell-tool {
  display: block;
  margin: 7px 0 0;
  color: var(--accent);
  overflow-wrap: anywhere;
}
.cell-note {
  margin: 6px 0 0;
  font-size: 11px;
  color: var(--muted);
  line-height: 1.4;
}
.rail {
  align-self: center;
  height: 2px;
  background: var(--critical);
  position: relative;
}
.rail::after {
  content: "";
  position: absolute;
  right: -1px;
  top: -3px;
  border-left: 6px solid var(--critical);
  border-top: 4px solid transparent;
  border-bottom: 4px solid transparent;
}
.rail--broken {
  background: repeating-linear-gradient(90deg, var(--ok) 0 3px, transparent 3px 6px);
}
.rail--broken::after { display: none; }

/* ---- controls --------------------------------------------------------- */
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}
.search {
  flex: 1 1 240px;
  padding: 7px 11px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  background: var(--surface);
  color: var(--ink);
  font: inherit;
  font-size: 13px;
}
.search:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; border-color: var(--accent); }
.result-count {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* ---- findings --------------------------------------------------------- */
.findings { display: flex; flex-direction: column; gap: 10px; }
.finding {
  padding: 15px 18px 16px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--line-strong);
  border-radius: 3px;
  background: var(--surface);
}
.finding[hidden] { display: none; }
.finding[data-severity="critical"] { border-left-color: var(--critical); }
.finding[data-severity="high"] { border-left-color: var(--high); }
.finding[data-severity="medium"] { border-left-color: var(--medium); }
.finding[data-severity="low"] { border-left-color: var(--low); }
.finding[data-severity="info"] { border-left-color: var(--info); }
.finding-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.finding-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  letter-spacing: -.005em;
  flex: 1 1 320px;
  text-wrap: pretty;
}
.finding-head h3 code {
  padding: 0 3px;
  border-radius: 2px;
  background: var(--surface-sunk);
  color: var(--accent);
  font-weight: 500;
  overflow-wrap: anywhere;
}
.sev {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: .1em;
  padding: 3px 7px;
  border-radius: 2px;
  color: var(--sev-ink);
  white-space: nowrap;
}
.sev--critical { background: var(--critical); }
.sev--high { background: var(--high); }
.sev--medium { background: var(--medium); }
.sev--low { background: var(--low); }
.sev--info { background: var(--info); }
.meta { margin: 7px 0 0; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.loc { color: var(--muted); overflow-wrap: anywhere; }
.rule {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px;
  letter-spacing: .04em;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 2px;
  padding: 1px 5px;
}
.impact { margin: 10px 0 0; max-width: 74ch; }
.impact code, .fix code {
  padding: 0 3px;
  border-radius: 2px;
  background: var(--surface-sunk);
  color: var(--accent);
  overflow-wrap: anywhere;
}
.evidence, .fix { margin-top: 11px; }
.field-label {
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: .11em;
  color: var(--muted);
  margin-bottom: 3px;
}
.evidence code {
  display: block;
  padding: 8px 10px;
  border-radius: 3px;
  background: var(--surface-sunk);
  border: 1px solid var(--line);
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  color: var(--muted);
}
.fix p { margin: 0; max-width: 74ch; }

.empty {
  padding: 40px 24px;
  text-align: center;
  border: 1px dashed var(--line-strong);
  border-radius: 3px;
  color: var(--muted);
}
.empty strong { display: block; color: var(--ok); font-size: 17px; margin-bottom: 4px; }

footer {
  margin: 48px 0 32px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
  font-size: 12px;
  color: var(--muted);
}
footer code { color: var(--muted); }

@media (max-width: 720px) {
  .links { grid-template-columns: 1fr; gap: 8px; }
  .rail { height: 18px; width: 2px; justify-self: center; }
  .rail::after { right: -3px; top: auto; bottom: -1px;
    border-left: 4px solid transparent; border-right: 4px solid transparent;
    border-top: 6px solid var(--critical); border-bottom: none; }
  .rail--broken { background: repeating-linear-gradient(180deg, var(--ok) 0 3px, transparent 3px 6px); }
  .banner-inner { padding-bottom: 20px; }
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""

SCRIPT = """
(function () {
  var root = document.documentElement;
  var toggle = document.getElementById('theme-toggle');
  try {
    var saved = localStorage.getItem('moat-theme');
    if (saved === 'dark' || saved === 'light') root.setAttribute('data-theme', saved);
  } catch (e) { /* storage can throw; the page works without it */ }

  toggle.addEventListener('click', function () {
    var dark = root.getAttribute('data-theme') === 'dark'
      || (!root.hasAttribute('data-theme')
          && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var next = dark ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try { localStorage.setItem('moat-theme', next); } catch (e) {}
  });

  var findings = Array.prototype.slice.call(document.querySelectorAll('.finding'));
  var tiles = Array.prototype.slice.call(document.querySelectorAll('.tile'));
  var search = document.getElementById('search');
  var counter = document.getElementById('result-count');
  var severity = 'all';

  function apply() {
    var needle = search.value.trim().toLowerCase();
    var shown = 0;
    findings.forEach(function (node) {
      var bySeverity = severity === 'all' || node.dataset.severity === severity;
      var byText = !needle || node.textContent.toLowerCase().indexOf(needle) !== -1;
      var visible = bySeverity && byText;
      node.hidden = !visible;
      if (visible) shown++;
    });
    counter.textContent = shown === findings.length
      ? findings.length + ' shown'
      : shown + ' of ' + findings.length + ' shown';
  }

  tiles.forEach(function (tile) {
    tile.addEventListener('click', function () {
      severity = tile.dataset.filter;
      tiles.forEach(function (other) { other.classList.toggle('is-active', other === tile); });
      apply();
    });
  });
  search.addEventListener('input', apply);
  apply();
})();
"""


def render_html(result: ScanResult, root: Path) -> str:
    root = Path(root)
    name = root.resolve().name or str(root)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    chains = [f for f in result.findings if f.rule_id.startswith("MOAT-TRIFECTA")]
    others = [f for f in result.findings if not f.rule_id.startswith("MOAT-TRIFECTA")]
    ordered = chains + others

    if result.findings:
        body_sections = [_tally(result)]
    else:
        body_sections = [
            '<div class="empty"><strong>No findings</strong>'
            "Nothing in this project's agent configuration grants more than it should.</div>"
        ]

    if chains:
        body_sections.append(
            "<section>"
            '<p class="eyebrow">Capability analysis</p>'
            "<h2>What each agent can actually do</h2>"
            '<p class="lede">An agent that can reach private data, ingest text an attacker '
            "wrote, and send data outward can be made to leak without any software "
            "vulnerability. These are the principals in this project and the state of "
            "that chain for each.</p>"
            + "".join(_chain(f) for f in chains)
            + "</section>"
        )

    if result.findings:
        body_sections.append(
            "<section>"
            '<p class="eyebrow">Findings</p>'
            f"<h2>{len(result.findings)} to review</h2>"
            '<div class="controls">'
            '<input id="search" class="search" type="search" '
            'placeholder="Filter by rule, file, tool or text…" aria-label="Filter findings">'
            '<span id="result-count" class="result-count"></span>'
            "</div>"
            f'<div class="findings">{"".join(_finding(f, root) for f in ordered)}</div>'
            "</section>"
        )

    suppressed = (
        f" &middot; {result.suppressed} suppressed by baseline" if result.suppressed else ""
    )
    errors = (
        f" &middot; {len(result.errors)} file(s) could not be fully analysed"
        if result.errors
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta name="generator" content="moat {esc(__version__)}">
<title>moat report — {esc(name)}</title>
<style>{STYLE}</style>
</head>
<body>
<header class="banner">
  <div class="banner-inner">
    <div>
      <div class="brand">
        <span class="brand-mark">moat</span>
        <span class="brand-version">v{esc(__version__)}</span>
      </div>
      <h1>Agent configuration report</h1>
    </div>
    <div style="display:flex;align-items:flex-end;gap:16px">
      <dl class="scan-meta">
        <dt>Scope</dt><dd>{esc(root)}</dd>
        <dt>Files</dt><dd>{len(result.targets)}</dd>
        <dt>Generated</dt><dd>{esc(generated)}</dd>
      </dl>
      <button type="button" id="theme-toggle" class="theme-toggle">Theme</button>
    </div>
  </div>
</header>
<main class="wrap">
{"".join(body_sections)}
<footer>
  Generated by <code>moat {esc(__version__)}</code>, a security scanner for AI agent and MCP
  configuration.{suppressed}{errors}
  <br>This file is self-contained and makes no network requests when opened.
</footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""
