"""Paleta, tipografía y medidas de la interfaz."""

from __future__ import annotations

from typing import Final

APPEARANCE: Final = "dark"
COLOR_THEME: Final = "blue"

WINDOW_TITLE: Final = "SafeBoost"
# Tamaño preferido y mínimo en píxeles lógicos (CustomTkinter aplica el escalado de Windows).
# Un portátil de 1366x768 al 125 % solo ofrece ~1090x614 lógicos: ahí se maximiza la ventana.
WINDOW_SIZE: Final = (1280, 820)
WINDOW_MIN: Final = (900, 560)
# Margen para la barra de tareas y el borde de la ventana.
SCREEN_MARGIN: Final = (40, 90)
SIDEBAR_WIDTH: Final = 224

PAD: Final = 12
PAD_S: Final = 6
RADIUS: Final = 14

FONT_FAMILY: Final = "Segoe UI"
FONT_TITLE: Final = (FONT_FAMILY, 24, "bold")
FONT_HERO: Final = (FONT_FAMILY, 22, "bold")
FONT_SCORE: Final = (FONT_FAMILY, 44, "bold")
FONT_BIG: Final = (FONT_FAMILY, 26, "bold")
FONT_H2: Final = (FONT_FAMILY, 16, "bold")
FONT_NAV: Final = (FONT_FAMILY, 14)
FONT_CHIP: Final = (FONT_FAMILY, 11, "bold")
FONT_BODY: Final = (FONT_FAMILY, 13)
FONT_SMALL: Final = (FONT_FAMILY, 11)
FONT_METRIC: Final = (FONT_FAMILY, 24, "bold")
FONT_MONO: Final = ("Cascadia Mono", 11)

# Colores (modo claro, modo oscuro) según convención de CustomTkinter.
# v0.12: paleta azul marino con tarjetas con borde fino (ver la maqueta del rediseño).
BG_APP: Final = ("#f4f6f9", "#0e1117")
BG_CARD: Final = ("#ffffff", "#121821")
BG_CARD_HI: Final = ("#eef3fb", "#141b25")
BG_SIDEBAR: Final = ("#e9edf2", "#0a0d12")
BORDER: Final = ("#d9dee6", "#1f2733")
NAV_ACTIVE: Final = ("#d6e3f8", "#18202c")
NAV_HOVER: Final = ("#dfe5ee", "#141a23")
TEXT: Final = ("#1b1f24", "#e6e9ef")
TEXT_MUTED: Final = ("#5b6270", "#9aa3b2")
ACCENT: Final = ("#2563eb", "#2f7bf5")
ACCENT_HOVER: Final = ("#1d4ed8", "#2563eb")
DANGER: Final = ("#b3261e", "#ff8a80")

# Semáforo: (texto/icono, fondo del chip o del icono), cada uno (claro, oscuro). Además del color,
# cada estado lleva siempre su palabra (BIEN, ATENCIÓN…) para no depender solo del tono.
TONES: Final[dict[str, tuple[tuple[str, str], tuple[str, str]]]] = {
    "ok": (("#1e7d46", "#6ee7a0"), ("#dcf5e6", "#13301f")),
    "warning": (("#9a6200", "#f2b84b"), ("#fdf0d5", "#3a2a10")),
    "critical": (("#b3261e", "#ff8a80"), ("#fde3e1", "#3a1d1d")),
    "info": (("#1d4ed8", "#7db4ff"), ("#dbe6fb", "#17263f")),
    "neutral": (("#5b6270", "#9aa3b2"), ("#e9edf2", "#18202c")),
    "purple": (("#6d28d9", "#c4a5ff"), ("#ede4fd", "#2a1f3d")),
}

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
    "border_color": ("#c3cad5", "#2a3240"),
    "hover_color": NAV_HOVER,
    "text_color": ("gray10", "gray90"),
}
PRIMARY_BUTTON: Final[dict[str, object]] = {
    "fg_color": ACCENT,
    "hover_color": ACCENT_HOVER,
    "text_color": ("#ffffff", "#ffffff"),
    "corner_radius": 12,
}

POLL_MS: Final = 100
LOG_POLL_MS: Final = 250
METRICS_REFRESH_MS: Final = 3000
LOG_MAX_LINES: Final = 2000
# Ancho máximo de los textos largos: cabe en la zona de contenido de una pantalla 1366x768 al 125 %.
WRAP: Final = 760
