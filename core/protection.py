"""Lista de protección aplicada en tiempo de ejecución, independiente del catálogo."""

from __future__ import annotations

from core.appx import is_protected_package
from core.constants import (
    ALLOWED_COMMAND_EXES,
    PRINT_SERVICES,
    PROTECTED_REGISTRY_PREFIXES,
    PROTECTED_SERVICES,
    SERVICES_KEY,
)
from core.environment import EnvironmentInfo
from core.services import ServiceManager


class ProtectionError(PermissionError):
    """Operación bloqueada por la lista de protección."""


class ProtectionGuard:
    def __init__(self, env: EnvironmentInfo, services: ServiceManager) -> None:
        self.env = env
        self.services = services

    def check_service(self, name: str) -> None:
        key = name.lower()
        if key in PROTECTED_SERVICES:
            raise ProtectionError(f"El servicio {name} está protegido y no se modifica")
        if key in PRINT_SERVICES and self.env.has_printers:
            printers = ", ".join(self.env.printers)
            raise ProtectionError(
                f"{name} se conserva porque hay impresoras instaladas: {printers}"
            )
        state = self.services.state(name)
        if state.exists and state.is_driver:
            raise ProtectionError(f"{name} es un driver y WinTune no modifica drivers")

    def check_appx(self, package: str) -> None:
        if is_protected_package(package):
            raise ProtectionError(f"El paquete {package} está protegido")

    def check_registry(self, hive: str, path: str) -> None:
        if hive != "HKLM":
            return
        lowered = path.strip("\\").lower()
        for prefix in PROTECTED_REGISTRY_PREFIXES:
            if lowered.startswith(prefix):
                raise ProtectionError(f"La clave HKLM\\{path} está protegida")
        services_prefix = SERVICES_KEY.lower() + "\\"
        if lowered.startswith(services_prefix):
            service = lowered[len(services_prefix) :].split("\\")[0]
            # Tcpip\Parameters\Interfaces es configuración de red, no el servicio en sí.
            if service != "tcpip":
                self.check_service(service)

    def check_command(self, exe: str) -> None:
        if exe not in ALLOWED_COMMAND_EXES:
            raise ProtectionError(f"Ejecutable no permitido en el catálogo: {exe}")
