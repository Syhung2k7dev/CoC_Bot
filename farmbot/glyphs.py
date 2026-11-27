"""COCFARM's own line icons, drawn as SVG in code: the few things Fluent's
icon set has no clear picture for (a hammer for the builder base, a
crosshair for the red line, a flask for spells...). Original drawings, no
game artwork.

One style, the same as Fluent's regular icons beside them: 24×24, round
1.9 px lines (about 1.3 px at 16), no fill except for small dots. Black in the light theme and
white in the dark one, like Fluent's. Each is a :class:`Glyph`, usable
wherever a Fluent icon is (``FluentIconBase``). Needs Qt."""

from __future__ import annotations

import math
from enum import Enum

from PySide6.QtGui import QColor, QIcon
from qfluentwidgets import FluentIconBase, Theme
from qfluentwidgets.common.icon import SvgIconEngine, drawSvgIcon, getIconColor


def _star(cx: float, cy: float, r: float) -> str:
    """A five-pointed star of radius ``r``, a point up."""
    points = []
    for i in range(10):
        radius = r if i % 2 == 0 else r * 0.45
        points.append(f"{cx + radius * math.sin(math.pi * i / 5):.1f} {cy - radius * math.cos(math.pi * i / 5):.1f}")
    return f'<path d="M{"L".join(points)}z"/>'


# Each icon's drawing: SVG elements in a 24×24 box. "{c}" is the colour.
SHAPES = {
    # Builder base: a hammer, handle bottom left, head top right.
    "hammer": '<path d="M3.5 20.5l8.7-8.7"/><path d="M11.9 4.3l7.8 7.8-3.6 3.6-7.8-7.8z"/>',
    # Follow the red line: a crosshair.
    "crosshair": '<circle cx="12" cy="12" r="7"/><path d="M12 2.5v5M12 16.5v5M2.5 12h5M16.5 12h5"/>'
                 '<circle cx="12" cy="12" r="1.2" fill="{c}" stroke="none"/>',
    # The spot spells go on: a target.
    "target": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.8"/>'
              '<circle cx="12" cy="12" r="1.3" fill="{c}" stroke="none"/>',
    # Spells spread over the base: a dot and dots around it.
    "spread": '<circle cx="12" cy="12" r="1.8" fill="{c}" stroke="none"/>'
              + "".join(f'<circle cx="{12 + 7 * x:.1f}" cy="{12 + 7 * y:.1f}" r="1.3" fill="{{c}}" stroke="none"/>'
                        for x, y in ((0, -1), (0.87, -0.5), (0.87, 0.5), (0, 1), (-0.87, 0.5), (-0.87, -0.5))),
    # Collecting: a coin dropping into a tray.
    "collect": '<circle cx="12" cy="5.5" r="3"/><path d="M12 10.5v5.5M9.5 13.5l2.5 2.5 2.5-2.5"/>'
               '<path d="M4 14.5v3.5a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3.5"/>',
    # Which collectors: a coin and a drop.
    "coin_drop": '<circle cx="8" cy="14" r="4.5"/><path d="M6.5 14h3"/>'
                 '<path d="M17 4c2.4 3 3.8 5.2 3.8 7a3.8 3.8 0 0 1-7.6 0c0-1.8 1.4-4 3.8-7z"/>',
    # Spells: a flask.
    "flask": '<path d="M9 3h6M10 3v5.5L5.2 17.2A2.4 2.4 0 0 0 7.3 21h9.4a2.4 2.4 0 0 0 2.1-3.8L14 8.5V3"/>'
             '<path d="M7.4 14.5h9.2"/>',
    # Abilities: a lightning bolt.
    "bolt": '<path d="M13.5 2.5L5.5 13.5h6l-1 8 8-11h-6z"/>',
    # Heroes: a crown.
    "crown": '<path d="M3.5 8l4.5 4 4-6.5 4 6.5 4.5-4-1.8 10.5H5.3z"/><path d="M5.5 21h13"/>',
    # Play at 4x: fast forward.
    "fast": '<path d="M3.5 6.5l7.5 5.5-7.5 5.5z"/><path d="M12.5 6.5l7.5 5.5-7.5 5.5z"/>',
    # Clan wars: two crossed swords.
    "swords": '<path d="M4 4l11 11M13 18l5-5M16 16l4 4"/><path d="M20 4L9 15M11 18l-5-5M8 16l-4 4"/>',
    # Clan Capital raids: a castle tower.
    "castle": '<path d="M4.5 21V6.5h3v2.5h3V6.5h3v2.5h3V6.5h3V21z"/><path d="M10 21v-4a2 2 0 0 1 4 0v4"/>',
    # Ranked battles: a cup.
    "trophy": '<path d="M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4.5v1.5A3 3 0 0 0 7.5 10.5M17 6h2.5v1.5'
              'A3 3 0 0 1 16.5 10.5"/><path d="M12 14v3.5M8 20.5h8M9.5 20.5l.8-3h3.4l.8 3"/>',
    # Look at the result: three stars.
    "stars": "".join(_star(*star) for star in ((5.5, 15, 3.6), (12, 9.5, 4.6), (18.5, 15, 3.6))),
    # Rest: a crescent moon.
    "moon": '<path d="M19.5 14.5A8 8 0 1 1 9.5 4.5a6.3 6.3 0 0 0 10 10z"/>',
}

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" '
       'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


class Glyph(FluentIconBase, Enum):
    """COCFARM's own icons (see SHAPES)."""

    HAMMER = "hammer"
    CROSSHAIR = "crosshair"
    TARGET = "target"
    SPREAD = "spread"
    COLLECT = "collect"
    COIN_DROP = "coin_drop"
    FLASK = "flask"
    BOLT = "bolt"
    CROWN = "crown"
    FAST = "fast"
    SWORDS = "swords"
    CASTLE = "castle"
    TROPHY = "trophy"
    STARS = "stars"
    MOON = "moon"

    def svg(self, theme=Theme.AUTO, color: str | None = None) -> str:
        c = color or ("#ffffff" if getIconColor(theme) == "white" else "#000000")
        return SVG.format(c=c, body=SHAPES[self.value].replace("{c}", c))

    def path(self, theme=Theme.AUTO) -> str:  # (no file: drawn from svg())
        return ""

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        return QIcon(SvgIconEngine(self.svg(theme, QColor(color).name() if color else None)))

    def render(self, painter, rect, theme=Theme.AUTO, indexes=None, **attributes) -> None:
        fill = attributes.get("fill")
        drawSvgIcon(self.svg(theme, QColor(fill).name() if fill else None).encode(), painter, rect)
