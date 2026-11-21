"""Navegadores que se quedan en memoria aunque los cierres (Edge Startup boost, segundo plano).

Las condiciones de estos tweaks viven aquí; los cambios son claves de directiva declarativas en
tweaks.json (revertibles con el snapshot del registro).
"""

from __future__ import annotations

import psutil

from core.constants import LOW_RAM_GIB
from core.context import HandlerContext

GIB = 1024**3
_CHROME_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"


def chrome_installed(ctx: HandlerContext) -> bool:
    """Chrome registra su ruta en App Paths al instalarse para todos o para el usuario."""
    return ctx.registry.key_exists("HKLM", _CHROME_APP_PATH) or ctx.registry.key_exists(
        "HKCU", _CHROME_APP_PATH
    )


def low_ram(_ctx: HandlerContext) -> bool:
    """Equipo con poca memoria: aquí cada navegador residente se nota de verdad."""
    return psutil.virtual_memory().total < LOW_RAM_GIB * GIB
