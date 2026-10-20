"""
Ícones desenhados com Pillow (sem arquivos nem emojis): renderizados em 4x e reduzidos,
com variantes para tema claro e escuro.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Callable, Dict, Tuple

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

from . import theme

SCALE = 4
_BOLD_FONTS = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")

Painter = Callable[[ImageDraw.ImageDraw, int, str], None]


@lru_cache(maxsize=None)
def _bold_font(size: int) -> ImageFont.FreeTypeFont:
    for name in _BOLD_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def tile_image(label: str, color: str, px: int) -> Image.Image:
    """Quadrado arredondado colorido com a sigla da ferramenta."""
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, px - 1, px - 1), radius=int(px * 0.26), fill=color)
    size = int(px * (0.5 if len(label) <= 1 else 0.42 if len(label) == 2 else 0.32))
    while size > 8 and draw.textlength(label, font=_bold_font(size)) > px * 0.8:
        size -= 2
    draw.text((px / 2, px / 2 + px * 0.01), label, font=_bold_font(size), fill="white", anchor="mm")
    return image


@lru_cache(maxsize=None)
def tool_icon(label: str, color: str, size: int = 40) -> ctk.CTkImage:
    image = tile_image(label, color, size * SCALE).resize((size * 2, size * 2), Image.LANCZOS)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


@lru_cache(maxsize=None)
def dot(color: str, size: int = 10) -> ctk.CTkImage:
    px = size * SCALE
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((0, 0, px - 1, px - 1), fill=color)
    image = image.resize((size * 2, size * 2), Image.LANCZOS)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def app_icon_image(px: int = 256) -> Image.Image:
    return tile_image("26", theme.ACCENT[0], px)


# ----------------------------------------------------------------------------- pictogramas
def _line_width(px: int) -> int:
    return max(2, round(px * 0.085))


def _p(px: int, *coords: float) -> Tuple[float, ...]:
    return tuple(value * px for value in coords)


def _arrow_left(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.8, 0.5, 0.22, 0.5), fill=color, width=w)
    draw.line(_p(px, 0.46, 0.25, 0.22, 0.5, 0.46, 0.75), fill=color, width=w, joint="curve")


def _chevron(direction: str) -> Painter:
    points = {
        "left": (0.62, 0.22, 0.35, 0.5, 0.62, 0.78),
        "right": (0.38, 0.22, 0.65, 0.5, 0.38, 0.78),
        "up": (0.22, 0.62, 0.5, 0.35, 0.78, 0.62),
        "down": (0.22, 0.38, 0.5, 0.65, 0.78, 0.38),
    }[direction]

    def paint(draw, px, color):
        draw.line(_p(px, *points), fill=color, width=_line_width(px), joint="curve")

    return paint


def _plus(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.5, 0.2, 0.5, 0.8), fill=color, width=w)
    draw.line(_p(px, 0.2, 0.5, 0.8, 0.5), fill=color, width=w)


def _minus(draw, px, color):
    draw.line(_p(px, 0.2, 0.5, 0.8, 0.5), fill=color, width=_line_width(px))


def _close(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.25, 0.25, 0.75, 0.75), fill=color, width=w)
    draw.line(_p(px, 0.75, 0.25, 0.25, 0.75), fill=color, width=w)


def _star(filled: bool) -> Painter:
    def paint(draw, px, color):
        cx, cy, outer, inner = px / 2, px * 0.53, px * 0.42, px * 0.18
        points = [(cx + (outer if i % 2 == 0 else inner) * math.sin(i * math.pi / 5), cy - (outer if i % 2 == 0 else inner) * math.cos(i * math.pi / 5)) for i in range(10)]
        if filled:
            draw.polygon(points, fill=color)
        else:
            draw.line(points + [points[0]], fill=color, width=_line_width(px), joint="curve")

    return paint


def _gear(draw, px, color):
    w = _line_width(px)
    cx = cy = px / 2
    for i in range(8):
        angle = i * math.pi / 4
        draw.line((cx + px * 0.24 * math.cos(angle), cy + px * 0.24 * math.sin(angle), cx + px * 0.42 * math.cos(angle), cy + px * 0.42 * math.sin(angle)), fill=color, width=int(w * 1.6))
    draw.ellipse(_p(px, 0.24, 0.24, 0.76, 0.76), outline=color, width=w, fill=None)
    draw.ellipse(_p(px, 0.4, 0.4, 0.6, 0.6), outline=color, width=w)


def _search(draw, px, color):
    w = _line_width(px)
    draw.ellipse(_p(px, 0.18, 0.18, 0.64, 0.64), outline=color, width=w)
    draw.line(_p(px, 0.58, 0.58, 0.84, 0.84), fill=color, width=int(w * 1.2))


def _folder(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.12, 0.28, 0.4, 0.28, 0.48, 0.36, 0.88, 0.36, 0.88, 0.78, 0.12, 0.78, 0.12, 0.28), fill=color, width=w, joint="curve")


def _file(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.24, 0.12, 0.6, 0.12, 0.78, 0.3, 0.78, 0.88, 0.24, 0.88, 0.24, 0.12), fill=color, width=w, joint="curve")
    draw.line(_p(px, 0.58, 0.12, 0.58, 0.32, 0.78, 0.32), fill=color, width=w, joint="curve")


def _trash(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.18, 0.28, 0.82, 0.28), fill=color, width=w)
    draw.line(_p(px, 0.4, 0.28, 0.42, 0.16, 0.58, 0.16, 0.6, 0.28), fill=color, width=w, joint="curve")
    draw.line(_p(px, 0.26, 0.28, 0.3, 0.86, 0.7, 0.86, 0.74, 0.28), fill=color, width=w, joint="curve")


def _rotate(clockwise: bool) -> Painter:
    def paint(draw, px, color):
        w = _line_width(px)
        box = _p(px, 0.2, 0.2, 0.8, 0.8)
        if clockwise:
            draw.arc(box, start=200, end=500, fill=color, width=w)
            draw.line(_p(px, 0.83, 0.18, 0.8, 0.42, 0.57, 0.38), fill=color, width=w, joint="curve")
        else:
            draw.arc(box, start=40, end=340, fill=color, width=w)
            draw.line(_p(px, 0.17, 0.18, 0.2, 0.42, 0.43, 0.38), fill=color, width=w, joint="curve")

    return paint


def _undo(draw, px, color):
    w = _line_width(px)
    draw.arc(_p(px, 0.22, 0.3, 0.84, 0.86), start=200, end=420, fill=color, width=w)
    draw.line(_p(px, 0.2, 0.28, 0.24, 0.56, 0.48, 0.48), fill=color, width=w, joint="curve")


def _save(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.16, 0.16, 0.7, 0.16, 0.84, 0.3, 0.84, 0.84, 0.16, 0.84, 0.16, 0.16), fill=color, width=w, joint="curve")
    draw.rectangle(_p(px, 0.32, 0.56, 0.68, 0.84), outline=color, width=w)
    draw.line(_p(px, 0.32, 0.16, 0.32, 0.36, 0.62, 0.36, 0.62, 0.16), fill=color, width=w)


def _grid(draw, px, color):
    w = _line_width(px)
    for x, y in ((0.16, 0.16), (0.56, 0.16), (0.16, 0.56), (0.56, 0.56)):
        draw.rounded_rectangle(_p(px, x, y, x + 0.28, y + 0.28), radius=px * 0.05, outline=color, width=w)


def _clock(draw, px, color):
    w = _line_width(px)
    draw.ellipse(_p(px, 0.14, 0.14, 0.86, 0.86), outline=color, width=w)
    draw.line(_p(px, 0.5, 0.28, 0.5, 0.5, 0.66, 0.62), fill=color, width=w, joint="curve")


def _check(draw, px, color):
    draw.line(_p(px, 0.18, 0.52, 0.42, 0.74, 0.84, 0.28), fill=color, width=int(_line_width(px) * 1.3), joint="curve")


def _copy(draw, px, color):
    w = _line_width(px)
    draw.rounded_rectangle(_p(px, 0.34, 0.34, 0.84, 0.84), radius=px * 0.06, outline=color, width=w)
    draw.line(_p(px, 0.22, 0.66, 0.16, 0.66, 0.16, 0.16, 0.66, 0.16, 0.66, 0.22), fill=color, width=w, joint="curve")


def _fit_width(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.1, 0.5, 0.9, 0.5), fill=color, width=w)
    draw.line(_p(px, 0.28, 0.32, 0.1, 0.5, 0.28, 0.68), fill=color, width=w, joint="curve")
    draw.line(_p(px, 0.72, 0.32, 0.9, 0.5, 0.72, 0.68), fill=color, width=w, joint="curve")


def _fit_page(draw, px, color):
    w = _line_width(px)
    draw.rounded_rectangle(_p(px, 0.24, 0.12, 0.76, 0.88), radius=px * 0.05, outline=color, width=w)
    draw.line(_p(px, 0.36, 0.4, 0.64, 0.4), fill=color, width=w)
    draw.line(_p(px, 0.36, 0.6, 0.64, 0.6), fill=color, width=w)


def _copy_page(draw, px, color):
    _copy(draw, px, color)
    w = _line_width(px)
    draw.line(_p(px, 0.59, 0.46, 0.59, 0.72), fill=color, width=w)
    draw.line(_p(px, 0.46, 0.59, 0.72, 0.59), fill=color, width=w)


def _swap(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.2, 0.34, 0.8, 0.34), fill=color, width=w)
    draw.line(_p(px, 0.64, 0.2, 0.8, 0.34, 0.64, 0.48), fill=color, width=w, joint="curve")
    draw.line(_p(px, 0.8, 0.66, 0.2, 0.66), fill=color, width=w)
    draw.line(_p(px, 0.36, 0.52, 0.2, 0.66, 0.36, 0.8), fill=color, width=w, joint="curve")


def _edit(draw, px, color):
    w = _line_width(px)
    draw.line(_p(px, 0.2, 0.8, 0.26, 0.6, 0.66, 0.2, 0.8, 0.34, 0.4, 0.74, 0.2, 0.8), fill=color, width=w, joint="curve")


PAINTERS: Dict[str, Painter] = {
    "back": _arrow_left,
    "prev": _chevron("left"),
    "next": _chevron("right"),
    "up": _chevron("up"),
    "down": _chevron("down"),
    "plus": _plus,
    "minus": _minus,
    "close": _close,
    "star": _star(True),
    "star_outline": _star(False),
    "gear": _gear,
    "search": _search,
    "folder": _folder,
    "file": _file,
    "trash": _trash,
    "rotate_cw": _rotate(True),
    "rotate_ccw": _rotate(False),
    "undo": _undo,
    "save": _save,
    "grid": _grid,
    "clock": _clock,
    "check": _check,
    "copy": _copy,
    "duplicate": _copy_page,
    "fit_width": _fit_width,
    "fit_page": _fit_page,
    "swap": _swap,
    "edit": _edit,
}


def _render(name: str, color: str, size: int) -> Image.Image:
    px = size * SCALE
    image = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    PAINTERS[name](ImageDraw.Draw(image), px, color)
    return image.resize((size * 2, size * 2), Image.LANCZOS)


@lru_cache(maxsize=None)
def icon(name: str, size: int = 18, colors: Tuple[str, str] = theme.TEXT) -> ctk.CTkImage:
    """Pictograma com cor para tema claro e escuro (padrão: cor do texto)."""
    light, dark = (colors, colors) if isinstance(colors, str) else colors
    return ctk.CTkImage(light_image=_render(name, light, size), dark_image=_render(name, dark, size), size=(size, size))
