"""Server-rendered SVG charts (29).

No charting library: the shapes are simple, the data volume is small, and SVG
rendered on the server means the dashboard paints its charts in the first
response with no client work and no third-party script to allow in the CSP.

Colours come from CSS custom properties so a chart re-themes with the rest of
the page (women / men / admin) instead of hard-coding hex values.
"""

from __future__ import annotations

from typing import Sequence

from .primitives import esc, join


def _points(values: Sequence[float], width: float, height: float, top: float, bottom: float) -> list[tuple[float, float]]:
    if not values:
        return []
    high = max(values)
    low = min(values)
    span = (high - low) or 1
    plot_height = height - top - bottom
    if len(values) == 1:
        return [(width / 2, top + plot_height / 2)]
    step = width / (len(values) - 1)
    return [
        (index * step, top + plot_height * (1 - (value - low) / span))
        for index, value in enumerate(values)
    ]


def _path(points: Sequence[tuple[float, float]]) -> str:
    if not points:
        return ""
    return "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in points)


def line_chart(
    series: Sequence[dict],
    labels: Sequence[str],
    *,
    height: int = 220,
    width: int = 640,
    show_area: bool = True,
) -> str:
    """series = [{"name": str, "values": [...], "tone": "female"|"male"|"brand"}]"""
    if not series or not any(entry.get("values") for entry in series):
        return '<div class="chart-empty">אין עדיין מספיק נתונים לגרף</div>'

    top, bottom = 14.0, 26.0
    all_values = [value for entry in series for value in entry.get("values", [])]
    high = max(all_values) if all_values else 1
    low = min(all_values) if all_values else 0
    grid_lines = join(
        [
            f'<line class="chart-grid" x1="0" y1="{top + (height - top - bottom) * fraction:.1f}" '
            f'x2="{width}" y2="{top + (height - top - bottom) * fraction:.1f}"/>'
            for fraction in (0, 0.25, 0.5, 0.75, 1)
        ]
    )

    body: list[str] = []
    for entry in series:
        values = entry.get("values", [])
        tone = entry.get("tone", "brand")
        points = _points(values, width, height, top, bottom)
        if not points:
            continue
        if show_area and len(points) > 1:
            area = _path(points) + f" L {points[-1][0]:.1f} {height - bottom:.1f} L {points[0][0]:.1f} {height - bottom:.1f} Z"
            body.append(f'<path class="chart-area chart-tone-{esc(tone)}" d="{area}"/>')
        body.append(f'<path class="chart-line chart-tone-{esc(tone)}" d="{_path(points)}"/>')
        body.extend(
            f'<circle class="chart-dot chart-tone-{esc(tone)}" cx="{x:.1f}" cy="{y:.1f}" r="3.5"/>'
            for x, y in points
        )

    label_step = max(1, len(labels) // 7)
    axis = join(
        [
            f'<text class="chart-label" x="{index * (width / max(1, len(labels) - 1)):.1f}" '
            f'y="{height - 6}" text-anchor="middle">{esc(label)}</text>'
            for index, label in enumerate(labels)
            if index % label_step == 0
        ]
    )
    legend = join(
        [
            f'<span class="chart-legend-item chart-tone-{esc(entry.get("tone", "brand"))}">'
            f'<span class="chart-legend-dot"></span>{esc(entry.get("name", ""))}</span>'
            for entry in series
        ]
    )
    return f"""
    <div class="chart">
      <div class="chart-legend">{legend}</div>
      <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" class="chart-svg" role="img"
           aria-label="גרף מגמה. ערך מרבי {high}, ערך מזערי {low}.">
        {grid_lines}{join(body)}{axis}
      </svg>
    </div>
    """


def donut_chart(segments: Sequence[dict], *, center_value: str = "", center_label: str = "", size: int = 190) -> str:
    """segments = [{"label": str, "value": number, "tone": str}]"""
    total = sum(max(0, segment.get("value", 0)) for segment in segments)
    if total <= 0:
        return '<div class="chart-empty">אין עדיין נתונים</div>'

    radius = size / 2 - 16
    circumference = 2 * 3.14159265 * radius
    center = size / 2
    offset = 0.0
    arcs: list[str] = []
    legend: list[str] = []
    for segment in segments:
        value = max(0, segment.get("value", 0))
        share = value / total
        length = circumference * share
        arcs.append(
            f'<circle class="donut-arc chart-tone-{esc(segment.get("tone", "brand"))}" cx="{center}" cy="{center}" '
            f'r="{radius:.1f}" fill="none" stroke-width="16" stroke-linecap="round" '
            f'stroke-dasharray="{max(0.0, length - 3):.1f} {circumference - length + 3:.1f}" '
            f'stroke-dashoffset="{-offset:.1f}" transform="rotate(-90 {center} {center})"/>'
        )
        offset += length
        legend.append(
            f'<li class="donut-legend-item chart-tone-{esc(segment.get("tone", "brand"))}">'
            f'<span class="chart-legend-dot"></span>'
            f'<span class="donut-legend-label">{esc(segment.get("label", ""))}</span>'
            f'<span class="donut-legend-value">{round(share * 100)}%</span></li>'
        )

    return f"""
    <div class="donut">
      <div class="donut-figure" style="--donut-size:{size}px">
        <svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" aria-label="{esc(center_label)}">
          <circle class="donut-track" cx="{center}" cy="{center}" r="{radius:.1f}" fill="none" stroke-width="16"/>
          {join(arcs)}
        </svg>
        <div class="donut-center">
          <span class="donut-value">{esc(center_value)}</span>
          <span class="donut-label">{esc(center_label)}</span>
        </div>
      </div>
      <ul class="donut-legend">{join(legend)}</ul>
    </div>
    """


def bar_chart(items: Sequence[dict], *, height: int = 190, tone: str = "brand") -> str:
    """items = [{"label": str, "value": number}]"""
    if not items:
        return '<div class="chart-empty">אין עדיין נתונים</div>'
    high = max(max(0, item.get("value", 0)) for item in items) or 1
    bars = join(
        [
            f'<div class="bar-col"><div class="bar-fill chart-tone-{esc(tone)}" '
            f'style="height:{max(4, round(100 * max(0, item.get("value", 0)) / high))}%" '
            f'title="{esc(item.get("label", ""))}: {esc(item.get("value", 0))}"></div>'
            f'<span class="bar-label">{esc(item.get("label", ""))}</span></div>'
            for item in items
        ]
    )
    return f'<div class="bar-chart" style="--bar-height:{height}px">{bars}</div>'


def week_strip(days: Sequence[dict]) -> str:
    """days = [{"label": str, "state": "done"|"today"|"rest"|"todo"}]"""
    cells = join(
        [
            f'<div class="week-cell is-{esc(day.get("state", "todo"))}">'
            f'<span class="week-day">{esc(day.get("label", ""))}</span>'
            f'<span class="week-dot">{"✓" if day.get("state") == "done" else ""}</span></div>'
            for day in days
        ]
    )
    return f'<div class="week-strip">{cells}</div>'
