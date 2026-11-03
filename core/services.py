"""Consulta y cambio del tipo de inicio de servicios de Windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.constants import (
    DRIVER_SERVICE_TYPE_MASK,
    SC_START_ARG,
    SERVICE_START_VALUES,
    SERVICES_KEY,
)
from core.logger import get_logger
from core.process import CommandError, Runner, resolve_exe
from core.registry import Registry

log = get_logger("services")

StartType = Literal["automatic", "automatic_delayed", "manual", "disabled", "boot", "system"]

# sc.exe: el servicio ya estaba detenido / no está iniciado.
_SC_NOT_STARTED = 1062


class ServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceState:
    name: str
    exists: bool
    start: StartType | None
    service_type: int | None

    @property
    def is_driver(self) -> bool:
        return bool(self.service_type is not None and self.service_type & DRIVER_SERVICE_TYPE_MASK)


class ServiceManager:
    """Lee el estado desde el registro (rápido, sin procesos) y modifica con sc.exe."""

    def __init__(self, registry: Registry, runner: Runner) -> None:
        self.registry = registry
        self.runner = runner

    def state(self, name: str) -> ServiceState:
        key = f"{SERVICES_KEY}\\{name}"
        if not self.registry.key_exists("HKLM", key):
            return ServiceState(name, False, None, None)
        start_val = self.registry.read("HKLM", key, "Start")
        delayed = self.registry.read("HKLM", key, "DelayedAutostart")
        svc_type = self.registry.read("HKLM", key, "Type")
        start: StartType | None = None
        if start_val is not None and isinstance(start_val.data, int):
            start = {
                0: "boot",
                1: "system",
                2: "automatic",
                3: "manual",
                4: "disabled",
            }.get(start_val.data)  # type: ignore[assignment]
            if start == "automatic" and delayed is not None and delayed.data == 1:
                start = "automatic_delayed"
        type_int = (
            svc_type.data if svc_type is not None and isinstance(svc_type.data, int) else None
        )
        return ServiceState(name, True, start, type_int)

    def set_start(self, name: str, start: str) -> None:
        if start not in SC_START_ARG:
            raise ServiceError(f"Tipo de inicio no válido: {start}")
        # "start=" y el valor van como argumentos separados: es la sintaxis exacta de sc.exe.
        try:
            result = self.runner.run(
                [resolve_exe("sc.exe"), "config", name, "start=", SC_START_ARG[start]]
            )
        except CommandError as exc:
            raise ServiceError(str(exc)) from exc
        if not result.ok:
            raise ServiceError(f"sc config {name}: {result.error_text()}")
        log.info("service_start_set", extra={"service": name, "start": start})

    def stop(self, name: str) -> None:
        try:
            result = self.runner.run([resolve_exe("sc.exe"), "stop", name])
        except CommandError as exc:
            raise ServiceError(str(exc)) from exc
        if not result.ok and result.returncode != _SC_NOT_STARTED:
            # No se aborta: el cambio de tipo de inicio ya surtirá efecto en el próximo arranque.
            log.warning("service_stop_failed", extra={"service": name, "err": result.error_text()})

    def start(self, name: str) -> None:
        try:
            self.runner.run([resolve_exe("sc.exe"), "start", name])
        except CommandError as exc:
            log.warning("service_start_failed", extra={"service": name, "err": str(exc)})

    @staticmethod
    def start_matches(current: str | None, target: str) -> bool:
        return current is not None and current == target and target in SERVICE_START_VALUES
