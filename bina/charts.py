"""Inline-SVG chart builders.

Self-contained on purpose: the report has to open from a file:// path with no
network and no JS library. Marks are thin, gridlines are hairlines, every chart
carries a table view, and values are direct-labelled selectively rather than on
every point.
"""

from __future__ import annotations

import html
from typing import Callable, Optional, Sequence

Formatter = Callable[[float], str]

# Categorical slots 1-3 of the reference palette. Validated all-pairs in both
# modes (worst CVD delta-E 9.2 light / 9.4 dark), which is why scatter series
# are capped at three.
SERIES_ROLES = ("--series-1", "--series-2", "--series-3")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _tooltip_attrs(label: str, value: str, extra: str = "") -> str:
    attrs = f'class="mark" tabindex="0" data-label="{esc(label)}" data-value="{esc(value)}"'
    if extra:
        attrs += f' data-extra="{esc(extra)}"'
    return attrs


def figure(
    title: str,
    subtitle: str,
    svg: str,
    table: str,
    legend: str = "",
    note: str = "",
) -> str:
    """Wrap a chart in its card: title, optional legend, plot, table view."""
    parts = [
        '<figure class="card">',
        f"<figcaption><h3>{esc(title)}</h3>",
        f"<p class=\"sub\">{esc(subtitle)}</p>" if subtitle else "",
        "</figcaption>",
        legend,
        f'<div class="plot">{svg}</div>',
        f'<p class="note">{esc(note)}</p>' if note else "",
        f"<details class=\"table-view\"><summary>Show data</summary>{table}</details>",
        "</figure>",
    ]
    return "".join(parts)


def empty_figure(title: str, reason: str) -> str:
    return (
        '<figure class="card">'
        f"<figcaption><h3>{esc(title)}</h3></figcaption>"
        f'<p class="empty">{esc(reason)}</p>'
        "</figure>"
    )


def legend(entries: Sequence[tuple[str, str]]) -> str:
    """``entries`` is ``[(label, css-var-role)]``. Always shown for 2+ series."""
    if len(entries) < 2:
        return ""
    items = "".join(
        f'<li><span class="swatch" style="background:var({role})"></span>{esc(label)}</li>'
        for label, role in entries
    )
    return f'<ul class="legend">{items}</ul>'


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# --- horizontal bars --------------------------------------------------------


def hbar(
    rows: Sequence[tuple[str, float, str]],
    fmt: Formatter,
    width: int = 660,
    label_width: int = 150,
    row_height: int = 30,
) -> str:
    """Horizontal bars, one series. ``rows`` is ``[(label, value, extra)]``."""
    from .stats import nice_ticks

    top, bottom, right = 10, 34, 70
    height = top + row_height * len(rows) + bottom
    plot_left = label_width
    plot_width = width - plot_left - right
    maximum = max((value for _, value, _ in rows), default=0)
    ticks = nice_ticks(maximum)
    scale_max = ticks[-1] or 1

    def x_of(value: float) -> float:
        return plot_left + plot_width * (value / scale_max)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]

    baseline_y = top + row_height * len(rows)
    for tick in ticks:
        x = x_of(tick)
        parts.append(
            f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{baseline_y}"/>'
        )
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{baseline_y + 18}" text-anchor="middle">'
            f"{esc(fmt(tick))}</text>"
        )

    # Bars: 4px rounded data-end, anchored to the baseline at x=plot_left, and a
    # 2px surface gap between neighbours (bar height 20 inside a 30px row).
    bar_height = row_height - 10
    for index, (label, value, extra) in enumerate(rows):
        y = top + index * row_height + 5
        bar_width = max(x_of(value) - plot_left, 1.5)
        parts.append(
            f'<g {_tooltip_attrs(label, fmt(value), extra)}>'
            f'<rect class="hit" x="{plot_left}" y="{y - 5}" width="{plot_width}" '
            f'height="{row_height}"/>'
            f'<rect class="bar" x="{plot_left}" y="{y}" width="{bar_width:.1f}" '
            f'height="{bar_height}" rx="4"/>'
            f'<text class="value" x="{plot_left + bar_width + 8:.1f}" '
            f'y="{y + bar_height - 5}">{esc(fmt(value))}</text>'
            f'<text class="cat" x="{plot_left - 10}" y="{y + bar_height - 5}" '
            f'text-anchor="end">{esc(label)}</text>'
            f"</g>"
        )

    parts.append(
        f'<line class="axis" x1="{plot_left}" y1="{top}" x2="{plot_left}" y2="{baseline_y}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


# --- vertical bars ----------------------------------------------------------


def vbar(
    rows: Sequence[tuple[str, float, str]],
    fmt: Formatter,
    width: int = 660,
    height: int = 300,
    direct_labels: bool = True,
    rotate_labels: bool = False,
) -> str:
    """Vertical bars, one series. ``rows`` is ``[(label, value, extra)]``."""
    from .stats import nice_ticks

    top, bottom, left, right = 24, 54 if rotate_labels else 40, 62, 16
    plot_height = height - top - bottom
    plot_width = width - left - right
    maximum = max((value for _, value, _ in rows), default=0)
    ticks = nice_ticks(maximum)
    scale_max = ticks[-1] or 1
    baseline = top + plot_height

    def y_of(value: float) -> float:
        return baseline - plot_height * (value / scale_max)

    slot = plot_width / max(len(rows), 1)
    bar_width = max(min(slot - 6, 48), 3)  # the 6px keeps a >= 2px surface gap

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    for tick in ticks:
        y = y_of(tick)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{esc(fmt(tick))}</text>"
        )

    for index, (label, value, extra) in enumerate(rows):
        centre = left + slot * (index + 0.5)
        y = y_of(value)
        bar_height = max(baseline - y, 1.5)
        parts.append(
            f'<g {_tooltip_attrs(label, fmt(value), extra)}>'
            f'<rect class="hit" x="{centre - slot / 2:.1f}" y="{top}" width="{slot:.1f}" '
            f'height="{plot_height}"/>'
            f'<rect class="bar" x="{centre - bar_width / 2:.1f}" y="{y:.1f}" '
            f'width="{bar_width:.1f}" height="{bar_height:.1f}" rx="4"/>'
        )
        if direct_labels and len(rows) <= 14:
            parts.append(
                f'<text class="value" x="{centre:.1f}" y="{y - 7:.1f}" text-anchor="middle">'
                f"{esc(fmt(value))}</text>"
            )
        if rotate_labels:
            parts.append(
                f'<text class="cat" x="{centre:.1f}" y="{baseline + 14}" '
                f'text-anchor="end" transform="rotate(-45 {centre:.1f} {baseline + 14})">'
                f"{esc(label)}</text>"
            )
        else:
            parts.append(
                f'<text class="cat" x="{centre:.1f}" y="{baseline + 17}" '
                f'text-anchor="middle">{esc(label)}</text>'
            )
        parts.append("</g>")

    parts.append(
        f'<line class="axis" x1="{left}" y1="{baseline}" x2="{left + plot_width}" y2="{baseline}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


# --- line -------------------------------------------------------------------


def line(
    rows: Sequence[tuple[str, float, str]],
    fmt: Formatter,
    width: int = 660,
    height: int = 300,
    every_nth_label: int = 1,
) -> str:
    """A single 2px line with >= 8px markers and a labelled endpoint.

    The scale is fitted to the data rather than anchored at zero: this form
    shows a level changing over time, where a zero baseline would flatten
    every real movement into a straight line.
    """
    from .stats import nice_ticks_between

    top, bottom, left, right = 24, 44, 62, 54
    plot_height = height - top - bottom
    plot_width = width - left - right
    values = [value for _, value, _ in rows]
    low, high = (min(values), max(values)) if values else (0.0, 1.0)
    padding = (high - low) * 0.2 or max(abs(high) * 0.05, 1.0)
    ticks = nice_ticks_between(max(low - padding, 0.0), high + padding)
    scale_min, scale_max = ticks[0], ticks[-1]
    span = (scale_max - scale_min) or 1
    baseline = top + plot_height

    def y_of(value: float) -> float:
        return baseline - plot_height * ((value - scale_min) / span)

    def x_of(index: int) -> float:
        if len(rows) == 1:
            return left + plot_width / 2
        return left + plot_width * index / (len(rows) - 1)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    for tick in ticks:
        y = y_of(tick)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{esc(fmt(tick))}</text>"
        )

    points = " ".join(f"{x_of(i):.1f},{y_of(v):.1f}" for i, v in enumerate(values))
    parts.append(f'<polyline class="line" points="{points}"/>')

    for index, (label, value, extra) in enumerate(rows):
        x, y = x_of(index), y_of(value)
        parts.append(
            f'<g {_tooltip_attrs(label, fmt(value), extra)}>'
            f'<circle class="hit-dot" cx="{x:.1f}" cy="{y:.1f}" r="14"/>'
            f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="4.5"/>'
            f"</g>"
        )
        if index % every_nth_label == 0 or index == len(rows) - 1:
            parts.append(
                f'<text class="cat" x="{x:.1f}" y="{baseline + 18}" text-anchor="middle">'
                f"{esc(label)}</text>"
            )

    if rows:
        last_x, last_y = x_of(len(rows) - 1), y_of(values[-1])
        parts.append(
            f'<text class="value" x="{last_x + 8:.1f}" y="{last_y + 4:.1f}">'
            f"{esc(fmt(values[-1]))}</text>"
        )

    parts.append(
        f'<line class="axis" x1="{left}" y1="{baseline}" x2="{left + plot_width}" y2="{baseline}"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


# --- scatter ----------------------------------------------------------------


def scatter(
    series: Sequence[tuple[str, Sequence[tuple[float, float, str]]]],
    x_fmt: Formatter,
    y_fmt: Formatter,
    x_label: str,
    y_label: str,
    width: int = 660,
    height: int = 340,
) -> str:
    """Up to three series of ``(x, y, tooltip-extra)`` points."""
    from .stats import nice_ticks

    top, bottom, left, right = 24, 48, 70, 18
    plot_height = height - top - bottom
    plot_width = width - left - right

    xs = [x for _, points in series for x, _, _ in points]
    ys = [y for _, points in series for _, y, _ in points]
    x_ticks = nice_ticks(max(xs, default=0))
    y_ticks = nice_ticks(max(ys, default=0))
    x_max = x_ticks[-1] or 1
    y_max = y_ticks[-1] or 1
    baseline = top + plot_height

    def px(value: float) -> float:
        return left + plot_width * (value / x_max)

    def py(value: float) -> float:
        return baseline - plot_height * (value / y_max)

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet">'
    ]
    for tick in y_ticks:
        y = py(tick)
        parts.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_width}" y2="{y:.1f}"/>'
        )
        parts.append(
            f'<text class="tick" x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">'
            f"{esc(y_fmt(tick))}</text>"
        )
    for tick in x_ticks:
        x = px(tick)
        parts.append(
            f'<text class="tick" x="{x:.1f}" y="{baseline + 18}" text-anchor="middle">'
            f"{esc(x_fmt(tick))}</text>"
        )

    for slot, (name, points) in enumerate(series[: len(SERIES_ROLES)]):
        role = SERIES_ROLES[slot]
        for x, y, extra in points:
            parts.append(
                f'<circle class="point" cx="{px(x):.1f}" cy="{py(y):.1f}" r="4" '
                f'style="fill:var({role})" tabindex="0" '
                f'data-label="{esc(name)}" data-value="{esc(y_fmt(y))}" '
                f'data-extra="{esc(extra)}"/>'
            )

    parts.append(
        f'<line class="axis" x1="{left}" y1="{baseline}" x2="{left + plot_width}" y2="{baseline}"/>'
    )
    parts.append(
        f'<text class="axis-label" x="{left + plot_width / 2:.1f}" y="{height - 6}" '
        f'text-anchor="middle">{esc(x_label)}</text>'
    )
    parts.append(
        f'<text class="axis-label" x="14" y="{top + plot_height / 2:.1f}" '
        f'text-anchor="middle" transform="rotate(-90 14 {top + plot_height / 2:.1f})">'
        f"{esc(y_label)}</text>"
    )
    parts.append("</svg>")
    return "".join(parts)


# --- stat tile --------------------------------------------------------------


def stat_tile(label: str, value: str, detail: str = "") -> str:
    return (
        '<div class="tile">'
        f'<p class="tile-label">{esc(label)}</p>'
        f'<p class="tile-value">{esc(value)}</p>'
        + (f'<p class="tile-detail">{esc(detail)}</p>' if detail else "")
        + "</div>"
    )
