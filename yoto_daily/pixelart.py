"""Pixel art for the tracks on a card.

The Yoto app and the player show a little 16x16 picture next to each
track.  It is called a display icon, and it is a 16x16 PNG with a 24-bit
RGBA colour format and alpha transparency.

They are drawn here rather than shipped as files: a card's icons are a
small, obvious part of its identity, and it is easier to change what a
story looks like than to open an image editor.

The shapes are laid out on a grid of sixteen cells, drawn eight times
larger, and then reduced -- one pixel per cell -- which is how you get
clean pixels out of a curve.

Positions and widths are written in grid cells, so ``12.0`` is three
quarters of the way across the icon and a stroke of ``1.0`` is one pixel
wide once the drawing has been reduced.
"""

from __future__ import annotations

import io
import math
from typing import Any

#: The size the player expects.
ICON_SIZE = 16

#: The size the shapes are drawn at before being reduced.
SUPERSAMPLE = 8

#: The size of the drawing canvas, in pixels.
CANVAS = ICON_SIZE * SUPERSAMPLE

#: The colours the icons are drawn with.
INK = (24, 26, 43, 255)
PAPER = (247, 243, 233, 255)
GOLD = (247, 181, 56, 255)
SKY = (86, 156, 214, 255)
ROSE = (214, 106, 118, 255)
MINT = (108, 190, 160, 255)
LAVENDER = (150, 129, 199, 255)


def _canvas() -> Any:
    from PIL import Image

    return Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))


def _unit(value: float) -> float:
    """A position on the sixteen-cell grid, in drawing pixels."""
    return value * SUPERSAMPLE


def _stroke(value: float) -> int:
    """A line width on the sixteen-cell grid, in drawing pixels."""
    return max(1, int(round(value * SUPERSAMPLE)))


def _finish(image: Any) -> bytes:
    """Reduce the drawing to sixteen pixels and encode it as a PNG."""
    from PIL import Image

    small = image.resize((ICON_SIZE, ICON_SIZE), Image.NEAREST)
    buffer = io.BytesIO()
    small.save(buffer, format="PNG")
    return buffer.getvalue()


def _draw_book() -> bytes:
    """An open book: a story."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    # Two pages meeting at a spine.
    draw.polygon(
        [(_unit(1.0), _unit(4.0)), (_unit(7.4), _unit(3.2)),
         (_unit(7.4), _unit(12.0)), (_unit(1.0), _unit(12.6))],
        fill=PAPER,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.polygon(
        [(_unit(15.0), _unit(4.0)), (_unit(8.6), _unit(3.2)),
         (_unit(8.6), _unit(12.0)), (_unit(15.0), _unit(12.6))],
        fill=PAPER,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(8.0), _unit(3.4)), (_unit(8.0), _unit(12.0))],
        fill=INK,
        width=_stroke(1.0),
    )

    # Lines of writing.
    for offset in (5.4, 7.0, 8.6):
        draw.line(
            [(_unit(2.2), _unit(offset)), (_unit(6.4), _unit(offset - 0.25))],
            fill=SKY,
            width=_stroke(1.0),
        )
        draw.line(
            [(_unit(9.6), _unit(offset - 0.25)), (_unit(13.8), _unit(offset))],
            fill=SKY,
            width=_stroke(1.0),
        )
    return _finish(image)


def _draw_note() -> bytes:
    """A musical note: a song."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    draw.ellipse(
        [_unit(1.6), _unit(9.4), _unit(7.4), _unit(13.4)],
        fill=ROSE,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.rectangle(
        [_unit(6.4), _unit(2.2), _unit(7.8), _unit(11.4)],
        fill=ROSE,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.polygon(
        [(_unit(7.8), _unit(2.2)), (_unit(13.4), _unit(4.4)),
         (_unit(13.4), _unit(6.8)), (_unit(7.8), _unit(4.8))],
        fill=ROSE,
    )
    draw.line(
        [(_unit(13.4), _unit(4.4)), (_unit(13.4), _unit(6.8))],
        fill=INK,
        width=_stroke(1.0),
    )
    return _finish(image)


def _draw_star() -> bytes:
    """A star: the facts."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    points = []
    for index in range(10):
        angle = math.pi / 2 + index * math.pi / 5
        radius = _unit(7.0) if index % 2 == 0 else _unit(4.2)
        points.append(
            (
                _unit(8.0) + math.cos(angle) * radius,
                _unit(8.0) - math.sin(angle) * radius,
            )
        )
    draw.polygon(points, fill=GOLD)
    return _finish(image)


def _draw_telescope() -> bytes:
    """A telescope: how we found them."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    draw.polygon(
        [(_unit(2.0), _unit(5.4)), (_unit(12.6), _unit(2.6)),
         (_unit(14.0), _unit(5.4)), (_unit(3.4), _unit(8.2))],
        fill=SKY,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(3.4), _unit(8.2)), (_unit(14.0), _unit(5.4))],
        fill=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(8.4), _unit(6.6)), (_unit(6.4), _unit(13.4))],
        fill=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(8.4), _unit(6.6)), (_unit(11.0), _unit(12.8))],
        fill=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(5.0), _unit(13.4)), (_unit(12.4), _unit(12.4))],
        fill=INK,
        width=_stroke(1.0),
    )
    return _finish(image)


def _draw_two_suns() -> bytes:
    """Two suns: a planet with a family of two."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    # The bigger sun.
    draw.ellipse(
        [_unit(1.2), _unit(1.2), _unit(8.6), _unit(8.6)],
        fill=GOLD,
        outline=INK,
        width=_stroke(1.0),
    )

    # The smaller one, drawn over it, so the big one keeps a crescent.
    draw.ellipse(
        [_unit(7.6), _unit(7.6), _unit(13.8), _unit(13.8)],
        fill=GOLD,
        outline=INK,
        width=_stroke(1.0),
    )
    return _finish(image)


def _draw_clock() -> bytes:
    """A clock: a year that goes round."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    draw.ellipse(
        [_unit(1.6), _unit(1.6), _unit(14.4), _unit(14.4)],
        fill=MINT,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(8.0), _unit(8.0)), (_unit(8.0), _unit(3.6))],
        fill=INK,
        width=_stroke(1.0),
    )
    draw.line(
        [(_unit(8.0), _unit(8.0)), (_unit(11.4), _unit(9.6))],
        fill=INK,
        width=_stroke(1.0),
    )
    return _finish(image)


def _draw_planet() -> bytes:
    """A planet: the topic itself."""
    from PIL import ImageDraw

    image = _canvas()
    draw = ImageDraw.Draw(image)

    # A moon, tucked up in the corner.
    draw.ellipse(
        [_unit(10.6), _unit(1.2), _unit(14.8), _unit(5.4)],
        fill=GOLD,
        outline=INK,
        width=_stroke(1.0),
    )

    # The planet, with a couple of marks on it.
    draw.ellipse(
        [_unit(1.4), _unit(3.6), _unit(11.8), _unit(14.0)],
        fill=LAVENDER,
        outline=INK,
        width=_stroke(1.0),
    )
    draw.ellipse(
        [_unit(3.6), _unit(6.0), _unit(5.8), _unit(8.2)],
        fill=MINT,
    )
    draw.ellipse(
        [_unit(7.0), _unit(9.6), _unit(9.0), _unit(11.6)],
        fill=MINT,
    )
    return _finish(image)


#: The icons that can be drawn, by name.
SHAPES = {
    "book": _draw_book,
    "note": _draw_note,
    "star": _draw_star,
    "telescope": _draw_telescope,
    "suns": _draw_two_suns,
    "clock": _draw_clock,
    "planet": _draw_planet,
}

#: Which shape each kind of segment gets, when it does not say.
BY_KIND = {
    "story": "book",
    "song": "note",
    "facts": "star",
    "explainer": "telescope",
}


def icon_for(kind: str, subject: str = "", title: str = "", icon: str = "") -> bytes:
    """The icon for a segment.

    A segment may name the picture it wants -- ``clock``, ``suns`` and so
    on -- and that always wins.  When it does not, the kind of segment
    decides, and the words of the segment get the last word: a piece
    about a year gets the clock, one about two suns gets the suns.
    """
    name = icon if icon in SHAPES else BY_KIND.get(kind, "star")
    haystack = f"{subject} {title}".lower()
    if icon in SHAPES:
        return SHAPES[name]()
    if "sun" in haystack:
        name = "suns"
    elif "year" in haystack or "six days" in haystack or "clock" in haystack:
        name = "clock"
    elif "found" in haystack or "transit" in haystack or "discover" in haystack:
        name = "telescope"
    return SHAPES[name]()


def names() -> list[str]:
    """The shapes that can be drawn."""
    return sorted(SHAPES)


#: How each colour is drawn in :func:`preview`.
_PREVIEW_CHARS = {
    "ink": "#",
    "paper": ".",
    "gold": "*",
    "sky": "=",
    "rose": "@",
    "mint": "o",
    "lavender": "%",
}


def preview(png: bytes) -> str:
    """A shape as text, for looking at one without an image viewer.

    Each pixel is drawn with the character that stands for its colour, so
    the shape can be judged on a terminal.
    """
    from PIL import Image

    palette = {
        "ink": INK,
        "paper": PAPER,
        "gold": GOLD,
        "sky": SKY,
        "rose": ROSE,
        "mint": MINT,
        "lavender": LAVENDER,
    }
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    rows = []
    for y in range(image.height):
        row = ""
        for x in range(image.width):
            pixel = image.getpixel((x, y))
            if pixel[3] < 40:
                row += " "
                continue
            best = min(
                palette,
                key=lambda name: sum(
                    abs(a - b) for a, b in zip(pixel[:3], palette[name][:3])
                ),
            )
            row += _PREVIEW_CHARS[best]
        rows.append(row)
    return "\n".join(rows)


#: The size a cover image is drawn at.
COVER_SIZE = 512

#: The night sky a cover is drawn on.
NIGHT = (20, 24, 48, 255)
NIGHT_LIGHT = (32, 38, 74, 255)
STARLIGHT = (247, 243, 233, 255)


def cover(kind: str = "story", subject: str = "", title: str = "", icon: str = "") -> bytes:
    """A cover image for a card.

    The same picture as the track icons, drawn large on a night sky, so a
    card looks like it was made for the thing it is about rather than like
    a list of files.
    """
    from PIL import Image, ImageDraw

    size = COVER_SIZE
    image = Image.new("RGBA", (size, size), NIGHT)
    draw = ImageDraw.Draw(image)

    # A soft band across the middle, so the sky is not flat.
    draw.ellipse([-size // 2, size // 3, size + size // 2, size + size // 3], fill=NIGHT_LIGHT)

    # Stars.
    for index in range(90):
        angle = index * 2.399963
        distance = size * (0.12 + 0.40 * ((index * 37) % 100) / 100.0)
        x = size / 2 + math.cos(angle) * distance
        y = size / 2 + math.sin(angle) * distance * 0.92
        radius = 1 + (index % 3)
        draw.ellipse(
            [x - radius, y - radius, x + radius, y + radius],
            fill=STARLIGHT if index % 4 else GOLD,
        )

    # The theme's picture, blown up.
    name = icon if icon in SHAPES else BY_KIND.get(kind, "star")
    haystack = f"{subject} {title}".lower()
    if not icon:
        if "sun" in haystack:
            name = "suns"
        elif "year" in haystack or "six days" in haystack:
            name = "clock"
        elif "found" in haystack or "transit" in haystack:
            name = "telescope"
    glyph = Image.open(io.BytesIO(SHAPES[name]())).convert("RGBA")
    glyph = glyph.resize((size // 2, size // 2), Image.NEAREST)
    image.alpha_composite(glyph, (size // 4, size // 4))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = [
    "BY_KIND",
    "CANVAS",
    "COVER_SIZE",
    "ICON_SIZE",
    "SHAPES",
    "cover",
    "icon_for",
    "names",
    "preview",
]
