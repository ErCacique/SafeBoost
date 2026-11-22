"""Inventario de programas instalados (claves Uninstall del registro). Solo lee.

Lo usan la foto antes/después de instalar y la lista de programas por tamaño.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core.registry import Registry

UNINSTALL_KEYS: tuple[tuple[str, str], ...] = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
)


@dataclass(frozen=True)
class Program:
    key: str  # hive\ruta\subclave: identifica la entrada aunque se repita el nombre
    name: str
    version: str = ""
    publisher: str = ""
    size_kb: int = 0  # EstimatedSize: lo declara el instalador, puede faltar o ser inexacto
    install_date: str = ""  # YYYYMMDD
    system_component: bool = False
    install_location: str = ""
    uninstall_string: str = ""

    @property
    def installed_on(self) -> date | None:
        try:
            return date(
                int(self.install_date[:4]), int(self.install_date[4:6]), int(self.install_date[6:8])
            )
        except (ValueError, IndexError):
            return None


def _text(registry: Registry, hive: str, path: str, name: str) -> str:
    value = registry.read(hive, path, name)
    return str(value.data).strip() if value and value.data is not None else ""


def list_programs(registry: Registry, include_system: bool = False) -> list[Program]:
    """Programas con nombre visible. Las actualizaciones y componentes de sistema se omiten."""
    seen: dict[str, Program] = {}
    for hive, root in UNINSTALL_KEYS:
        for sub in registry.subkeys(hive, root):
            path = f"{root}\\{sub}"
            name = _text(registry, hive, path, "DisplayName")
            if not name:
                continue
            system = _text(registry, hive, path, "SystemComponent") == "1"
            parent = _text(registry, hive, path, "ParentKeyName")  # parches de otro programa
            if (system or parent) and not include_system:
                continue
            size = _text(registry, hive, path, "EstimatedSize")
            program = Program(
                key=f"{hive}\\{path}",
                name=name,
                version=_text(registry, hive, path, "DisplayVersion"),
                publisher=_text(registry, hive, path, "Publisher"),
                size_kb=int(size) if size.isdigit() else 0,
                install_date=_text(registry, hive, path, "InstallDate"),
                system_component=system,
                install_location=_text(registry, hive, path, "InstallLocation").strip('"'),
                uninstall_string=_text(registry, hive, path, "UninstallString"),
            )
            # El mismo programa puede aparecer en HKLM y WOW6432Node: se queda el primero.
            seen.setdefault(name.lower(), program)
    return sorted(seen.values(), key=lambda p: p.name.lower())


def last_used(program: Program, by_exe: dict[str, float]) -> float | None:
    """Último uso aproximado: el .exe de su carpeta de instalación que se ejecutó más tarde
    (datos de Prefetch). None si no se sabe dónde está instalado o nunca se ha ejecutado."""
    if not program.install_location or not by_exe:
        return None
    root = Path(program.install_location)
    try:
        exes = [p.name.lower() for p in root.glob("*.exe")] + [
            p.name.lower() for p in root.glob("*/*.exe")
        ]
    except OSError:
        return None
    times = [by_exe[e] for e in exes if e in by_exe]
    return max(times) if times else None
