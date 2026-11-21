"""Quién ha usado la cámara, el micrófono y la ubicación, y cuándo. Solo lee.

Windows lo anota en CapabilityAccessManager\\ConsentStore (lo mismo que muestra en
Configuración → Privacidad). Para quitar permisos se abre esa página de Windows: es la vía
soportada y la que el usuario ya conoce.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.registry import Registry

CONSENT_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
CAPABILITIES: dict[str, tuple[str, str]] = {
    # clave → (nombre visible, página de Configuración de Windows)
    "webcam": ("Cámara", "ms-settings:privacy-webcam"),
    "microphone": ("Micrófono", "ms-settings:privacy-microphone"),
    "location": ("Ubicación", "ms-settings:privacy-location"),
}
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


def filetime_to_datetime(value: object) -> datetime | None:
    try:
        ticks = int(str(value))
    except (TypeError, ValueError):
        return None
    if ticks <= 0:
        return None
    return _FILETIME_EPOCH + timedelta(microseconds=ticks // 10)


@dataclass
class AppUsage:
    capability: str
    app: str
    path: str  # ruta del .exe (apps de escritorio) o familia del paquete (apps de la Store)
    allowed: bool | None
    last_start: datetime | None
    last_stop: datetime | None

    @property
    def in_use(self) -> bool:
        # Empezó y no ha terminado: la está usando ahora mismo.
        return self.last_start is not None and self.last_stop is None


@dataclass
class CapabilityReport:
    capability: str
    label: str
    settings_uri: str
    globally_allowed: bool | None
    apps: list[AppUsage]


def _allowed(registry: Registry, path: str) -> bool | None:
    value = registry.read("HKCU", path, "Value")
    if value is None:
        return None
    return str(value.data).lower() == "allow"


def _usage(registry: Registry, cap: str, path: str, app: str, raw: str) -> AppUsage | None:
    start = registry.read("HKCU", path, "LastUsedTimeStart")
    stop = registry.read("HKCU", path, "LastUsedTimeStop")
    first = filetime_to_datetime(start.data) if start else None
    if first is None:  # nunca la ha usado: no interesa listarla
        return None
    return AppUsage(
        cap,
        app,
        raw,
        _allowed(registry, path),
        first,
        filetime_to_datetime(stop.data) if stop else None,
    )


def read_privacy(registry: Registry) -> list[CapabilityReport]:
    reports = []
    for cap, (label, uri) in CAPABILITIES.items():
        base = f"{CONSENT_STORE}\\{cap}"
        apps: list[AppUsage] = []
        for sub in registry.subkeys("HKCU", base):
            if sub.lower() == "nonpackaged":
                for exe in registry.subkeys("HKCU", f"{base}\\{sub}"):
                    real = exe.replace("#", "\\")
                    name = real.rsplit("\\", 1)[-1]
                    usage = _usage(registry, cap, f"{base}\\{sub}\\{exe}", name, real)
                    if usage:
                        apps.append(usage)
            else:
                # Apps de la Store: "Microsoft.WindowsCamera_8wekyb3d8bbwe" → "WindowsCamera".
                name = sub.split("_", 1)[0].split(".")[-1]
                usage = _usage(registry, cap, f"{base}\\{sub}", name, sub)
                if usage:
                    apps.append(usage)
        apps.sort(key=lambda a: a.last_start or _FILETIME_EPOCH, reverse=True)
        reports.append(CapabilityReport(cap, label, uri, _allowed(registry, base), apps))
    return reports
