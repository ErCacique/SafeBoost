"""Servicios de fabricantes (HP, NVIDIA, Adobe). Condición: que el servicio exista en el equipo.

Solo se tocan servicios de telemetría o de comprobación de licencia, y siempre a Manual: siguen
arrancando si su programa los necesita. Los actualizadores de navegadores y antivirus no se tocan.
"""

from __future__ import annotations

from collections.abc import Callable

from core.constants import SERVICES_KEY
from core.context import HandlerContext


def _service_present(name: str) -> Callable[[HandlerContext], bool]:
    def check(ctx: HandlerContext) -> bool:
        return ctx.registry.key_exists("HKLM", f"{SERVICES_KEY}\\{name}")

    check.__name__ = f"present_{name}"
    return check


hp_analytics_present = _service_present("HpTouchpointAnalyticsService")
nvidia_telemetry_present = _service_present("NvTelemetryContainer")
adobe_genuine_present = _service_present("AGSService")
adobe_updater_present = _service_present("AdobeARMservice")
