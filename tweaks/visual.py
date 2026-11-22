"""Efectos visuales: notificación de cambios para que se apliquen sin cerrar sesión."""

from __future__ import annotations

import ctypes
import sys

from core.context import HandlerContext
from core.logger import get_logger

log = get_logger("tweaks.visual")

HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002
BROADCAST_TIMEOUT_MS = 5000


def broadcast_settings_change(ctx: HandlerContext) -> bool:
    """Envía WM_SETTINGCHANGE a todas las ventanas de nivel superior.

    Explorer relee parte de los ajustes al recibirlo; la máscara UserPreferencesMask completa
    solo se aplica al cerrar e iniciar sesión, por eso se avisa al usuario.
    Devuelve False: notificar no cuenta como cambio del sistema.
    """
    if ctx.dry_run:
        ctx.plan("Notificar el cambio de configuración a Explorer (WM_SETTINGCHANGE)")
        return False
    if sys.platform != "win32":
        return False
    result = ctypes.c_size_t()
    for area in ("WindowMetrics", "Policy", None):
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            area,
            SMTO_ABORTIFHUNG,
            BROADCAST_TIMEOUT_MS,
            ctypes.byref(result),
        )
    ctx.note("Algunos efectos visuales se aplicarán por completo al cerrar sesión")
    return False
