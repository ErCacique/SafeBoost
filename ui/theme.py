"""Paleta, tipografía y medidas de la interfaz."""

from __future__ import annotations

from typing import Final

APPEARANCE: Final = "dark"
COLOR_THEME: Final = "blue"

WINDOW_TITLE: Final = "WinTune"
WINDOW_SIZE: Final = "1280x820"
WINDOW_MIN: Final = (1100, 700)
SIDEBAR_WIDTH: Final = 210

PAD: Final = 12
PAD_S: Final = 6
RADIUS: Final = 10

FONT_FAMILY: Final = "Segoe UI"
FONT_TITLE: Final = (FONT_FAMILY, 22, "bold")
FONT_H2: Final = (FONT_FAMILY, 16, "bold")
FONT_BODY: Final = (FONT_FAMILY, 13)
FONT_SMALL: Final = (FONT_FAMILY, 11)
FONT_METRIC: Final = (FONT_FAMILY, 24, "bold")
FONT_MONO: Final = ("Cascadia Mono", 11)

# Colores (modo claro, modo oscuro) según convención de CustomTkinter.
BG_CARD: Final = ("#f2f3f5", "#20232a")
BG_SIDEBAR: Final = ("#e6e8eb", "#16181d")
TEXT_MUTED: Final = ("#5b6270", "#9aa3b2")
ACCENT: Final = ("#2f6fed", "#3b82f6")
DANGER: Final = ("#c62828", "#ef5350")

RISK_COLORS: Final[dict[str, tuple[str, str]]] = {
    "bajo": ("#2e7d32", "#4caf50"),
    "medio": ("#b26a00", "#ffa726"),
    "alto": ("#c62828", "#ef5350"),
}

STATE_COLORS: Final[dict[str, tuple[str, str]]] = {
    "applied": ("#2e7d32", "#4caf50"),
    "not_applied": ("#5b6270", "#9aa3b2"),
    "partial": ("#b26a00", "#ffa726"),
    "not_applicable": ("#8a8f99", "#6b7280"),
    "unknown": ("#8a8f99", "#6b7280"),
}

STATUS_LABELS: Final[dict[str, str]] = {
    "applied": "Aplicado",
    "skipped": "Omitido",
    "failed": "Fallido",
    "partial": "Parcial",
    "reverted": "Revertido",
    "irreversible": "Irreversible",
}

# Botón secundario (contorno). text_color explícito: el de serie es blanco y no se ve en claro.
SECONDARY_BUTTON: Final[dict[str, object]] = {
    "fg_color": "transparent",
    "border_width": 1,
    "text_color": ("gray10", "gray90"),
}

POLL_MS: Final = 100
LOG_POLL_MS: Final = 250
METRICS_REFRESH_MS: Final = 3000
LOG_MAX_LINES: Final = 2000
