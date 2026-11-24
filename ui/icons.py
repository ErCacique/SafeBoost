"""Iconos de línea dibujados con Pillow (sin archivos de imagen ni fuentes de iconos).

Cada icono se describe en una cuadrícula de 96×96 con trazos redondeados; se dibuja a 4× y se
reduce con Lanczos para que quede suavizado. `icon(nombre, color, tamaño)` devuelve un CTkImage
con una versión para el modo claro y otra para el oscuro (colores (claro, oscuro) del tema).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import customtkinter as ctk
from PIL import Image, ImageDraw

GRID = 96
SCALE = 4
STROKE = 7

Point = tuple[float, float]
Painter = Callable[["_Pen"], None]


class _Pen:
    """Trazos en coordenadas de la cuadrícula de 96, ya escalados y con extremos redondeados."""

    def __init__(self, draw: ImageDraw.ImageDraw, color: str) -> None:
        self.draw = draw
        self.color = color
        self.width = STROKE * SCALE

    def _p(self, pts: list[Point]) -> list[tuple[float, float]]:
        return [(x * SCALE, y * SCALE) for x, y in pts]

    def _dot(self, x: float, y: float) -> None:
        r = self.width / 2
        self.draw.ellipse(
            (x * SCALE - r, y * SCALE - r, x * SCALE + r, y * SCALE + r), fill=self.color
        )

    def line(self, *pts: Point) -> None:
        self.draw.line(self._p(list(pts)), fill=self.color, width=self.width, joint="curve")
        for x, y in (pts[0], pts[-1]):
            self._dot(x, y)

    def poly(self, *pts: Point) -> None:
        self.line(*pts, pts[0])

    def rect(self, x0: float, y0: float, x1: float, y1: float, r: float = 8) -> None:
        self.draw.rounded_rectangle(
            (x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE),
            radius=r * SCALE,
            outline=self.color,
            width=self.width,
        )

    def circle(self, cx: float, cy: float, r: float) -> None:
        self.draw.ellipse(
            ((cx - r) * SCALE, (cy - r) * SCALE, (cx + r) * SCALE, (cy + r) * SCALE),
            outline=self.color,
            width=self.width,
        )

    def arc(self, cx: float, cy: float, r: float, start: float, end: float) -> None:
        self.draw.arc(
            ((cx - r) * SCALE, (cy - r) * SCALE, (cx + r) * SCALE, (cy + r) * SCALE),
            start,
            end,
            fill=self.color,
            width=self.width,
        )

    def dot(self, x: float, y: float, r: float = 5) -> None:
        self.draw.ellipse(
            ((x - r) * SCALE, (y - r) * SCALE, (x + r) * SCALE, (y + r) * SCALE), fill=self.color
        )


def _home(p: _Pen) -> None:
    p.line((12, 48), (48, 18), (84, 48))
    p.line((22, 42), (22, 82), (40, 82), (40, 60), (56, 60), (56, 82), (74, 82), (74, 42))


def _pulse(p: _Pen) -> None:
    p.line((8, 50), (26, 50), (36, 24), (56, 76), (66, 50), (88, 50))


def _clock(p: _Pen) -> None:
    p.circle(48, 54, 32)
    p.line((48, 36), (48, 54), (62, 62))
    p.line((38, 10), (58, 10))


def _drive(p: _Pen) -> None:
    p.rect(12, 24, 84, 72, 10)
    p.dot(28, 56)
    p.line((44, 56), (68, 56))


def _trash(p: _Pen) -> None:
    p.line((14, 26), (82, 26))
    p.line((36, 26), (38, 14), (58, 14), (60, 26))
    p.line((24, 26), (30, 84), (66, 84), (72, 26))


def _undo(p: _Pen) -> None:
    p.arc(50, 50, 32, 200, 500)
    p.line((14, 22), (18, 42), (36, 38))


def _refresh(p: _Pen) -> None:
    # Círculo abierto arriba a la derecha con la punta de flecha arriba, en el sentido del reloj.
    p.arc(48, 52, 32, -30, 270)
    p.line((40, 10), (50, 20), (40, 30))


def _chart(p: _Pen) -> None:
    p.line((14, 12), (14, 84), (86, 84))
    p.line((28, 66), (46, 46), (58, 58), (80, 30))


def _lock(p: _Pen) -> None:
    p.rect(20, 44, 76, 86, 8)
    p.arc(48, 40, 18, 180, 360)
    p.line((30, 40), (30, 44))
    p.line((66, 40), (66, 44))


def _gear(p: _Pen) -> None:
    p.circle(48, 48, 12)
    p.circle(48, 48, 28)
    for a, b in (
        ((48, 8), (48, 18)),
        ((48, 78), (48, 88)),
        ((8, 48), (18, 48)),
        ((78, 48), (88, 48)),
        ((20, 20), (27, 27)),
        ((69, 69), (76, 76)),
        ((20, 76), (27, 69)),
        ((69, 27), (76, 20)),
    ):
        p.line(a, b)


def _bolt(p: _Pen) -> None:
    p.poly((54, 8), (18, 56), (46, 56), (40, 88), (78, 38), (50, 38))


def _shield(p: _Pen) -> None:
    p.poly((48, 10), (80, 22), (80, 46), (48, 86), (16, 46), (16, 22))
    p.line((32, 48), (44, 60), (64, 38))


def _memory(p: _Pen) -> None:
    p.rect(10, 30, 86, 66, 6)
    for x in (24, 40, 56, 72):
        p.line((x, 66), (x, 78))
    p.line((26, 44), (26, 52))
    p.line((48, 44), (48, 52))
    p.line((70, 44), (70, 52))


def _gamepad(p: _Pen) -> None:
    p.rect(8, 30, 88, 70, 20)
    p.line((22, 50), (38, 50))
    p.line((30, 42), (30, 58))
    p.dot(62, 46, 4)
    p.dot(72, 56, 4)


def _battery(p: _Pen) -> None:
    p.rect(8, 30, 78, 66, 8)
    p.line((86, 42), (86, 54))
    p.line((22, 42), (22, 54))
    p.line((34, 42), (34, 54))


def _apps(p: _Pen) -> None:
    for x, y in ((14, 14), (54, 14), (14, 54), (54, 54)):
        p.rect(x, y, x + 28, y + 28, 7)


def _sparkle(p: _Pen) -> None:
    p.poly((44, 10), (52, 36), (78, 44), (52, 52), (44, 78), (36, 52), (10, 44), (36, 36))
    p.line((76, 70), (76, 86))
    p.line((68, 78), (84, 78))


def _sliders(p: _Pen) -> None:
    for y, x in ((24, 62), (48, 30), (72, 54)):
        p.line((12, y), (84, y))
        p.circle(x, y, 7)


def _server(p: _Pen) -> None:
    p.rect(12, 14, 84, 44, 8)
    p.rect(12, 52, 84, 82, 8)
    p.dot(28, 29, 4)
    p.dot(28, 67, 4)


def _check(p: _Pen) -> None:
    p.line((18, 50), (40, 72), (80, 26))


def _alert(p: _Pen) -> None:
    p.circle(48, 48, 36)
    p.line((48, 28), (48, 54))
    p.dot(48, 68, 5)


def _back(p: _Pen) -> None:
    p.line((60, 18), (30, 48), (60, 78))


def _rocket(p: _Pen) -> None:
    p.poly((48, 8), (66, 30), (66, 64), (30, 64), (30, 30))
    p.line((30, 50), (16, 66), (30, 66))
    p.line((66, 50), (80, 66), (66, 66))
    p.line((40, 76), (40, 88))
    p.line((56, 76), (56, 88))
    p.circle(48, 36, 6)


PAINTERS: dict[str, Painter] = {
    "home": _home,
    "pulse": _pulse,
    "clock": _clock,
    "drive": _drive,
    "trash": _trash,
    "undo": _undo,
    "refresh": _refresh,
    "chart": _chart,
    "lock": _lock,
    "gear": _gear,
    "bolt": _bolt,
    "shield": _shield,
    "memory": _memory,
    "gamepad": _gamepad,
    "battery": _battery,
    "apps": _apps,
    "sparkle": _sparkle,
    "sliders": _sliders,
    "server": _server,
    "check": _check,
    "alert": _alert,
    "back": _back,
    "rocket": _rocket,
}


def render(name: str, color: str, px: int) -> Image.Image:
    """Icono como imagen RGBA de px×px. Función pura: la usan los tests y `icon`."""
    if name not in PAINTERS:
        raise KeyError(f"Icono desconocido: {name}")
    big = Image.new("RGBA", (GRID * SCALE, GRID * SCALE), (0, 0, 0, 0))
    PAINTERS[name](_Pen(ImageDraw.Draw(big), color))
    return big.resize((px, px), Image.Resampling.LANCZOS)


@lru_cache(maxsize=256)
def icon(name: str, color: tuple[str, str], size: int = 20) -> ctk.CTkImage:
    """CTkImage del icono para los dos modos de color. Se dibuja al doble para pantallas HiDPI."""
    return ctk.CTkImage(
        light_image=render(name, color[0], size * 2),
        dark_image=render(name, color[1], size * 2),
        size=(size, size),
    )
