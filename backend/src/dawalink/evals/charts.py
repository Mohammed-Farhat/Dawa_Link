"""The report's chart: one bar per contender, with its 95% interval (docs/08 §5).

Written as plain SVG, so the report needs no plotting library and the file reads the same
on every machine. One color per contender, the same everywhere; the interval is a black
whisker, so it shows on any bar.
"""

from collections.abc import Sequence
from html import escape

from dawalink.evals.stats import Estimate

WIDTH, BAR, GAP, LEFT, TOP, HEIGHT = 720, 34, 14, 250, 44, 300
COLORS = ("#1f3a5f", "#3d7ea6", "#8fb9d6", "#c9a227", "#7a7a7a")


def bars(title: str, rows: Sequence[tuple[str, Estimate]]) -> str:
    """A horizontal bar per row, from 0% to 100%, with the interval as a whisker."""
    scale = WIDTH - LEFT - 70
    height = TOP + len(rows) * (BAR + GAP) + 36
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" font-family="sans-serif" font-size="13">',
        f'<rect width="{WIDTH}" height="{height}" fill="white"/>',
        f'<text x="12" y="24" font-size="15" font-weight="bold">{escape(title)}</text>',
    ]
    for tick in range(0, 101, 25):
        x = LEFT + scale * tick / 100
        parts.append(
            f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" y2="{height - 30}" stroke="#dddddd"/>'
        )
        parts.append(
            f'<text x="{x:.1f}" y="{height - 12}" text-anchor="middle" fill="#555555">'
            f"{tick}%</text>"
        )
    for position, (label, estimate) in enumerate(rows):
        y = TOP + position * (BAR + GAP)
        middle = y + BAR / 2
        color = COLORS[position % len(COLORS)]
        low, high = LEFT + scale * estimate.low, LEFT + scale * estimate.high
        parts += [
            f'<text x="{LEFT - 10}" y="{middle + 4:.1f}" text-anchor="end">{escape(label)}</text>',
            f'<rect x="{LEFT}" y="{y}" width="{scale * estimate.value:.1f}" height="{BAR}" '
            f'fill="{color}"/>',
            f'<line x1="{low:.1f}" y1="{middle:.1f}" x2="{high:.1f}" y2="{middle:.1f}" '
            'stroke="black" stroke-width="2"/>',
            f'<line x1="{low:.1f}" y1="{middle - 6:.1f}" x2="{low:.1f}" y2="{middle + 6:.1f}" '
            'stroke="black" stroke-width="2"/>',
            f'<line x1="{high:.1f}" y1="{middle - 6:.1f}" x2="{high:.1f}" y2="{middle + 6:.1f}" '
            'stroke="black" stroke-width="2"/>',
            f'<text x="{high + 8:.1f}" y="{middle + 4:.1f}">{estimate.value:.0%}</text>',
        ]
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
