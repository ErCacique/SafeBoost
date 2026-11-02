"""Contexto que reciben los handlers de tweaks/ y tipos de resultado de detección."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.catalog import Tweak
from core.environment import EnvironmentInfo
from core.logger import get_logger
from core.process import Runner
from core.protection import ProtectionGuard
from core.registry import Registry, RegValue, export_key, values_equal
from core.services import ServiceManager
from core.session import Change, ChangeKind, Session

log = get_logger("context")

HANDLER_PACKAGE = "tweaks"


class DetectState(StrEnum):
    APPLIED = "applied"
    NOT_APPLIED = "not_applied"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


DETECT_LABELS: dict[DetectState, str] = {
    DetectState.APPLIED: "Aplicado",
    DetectState.NOT_APPLIED: "No aplicado",
    DetectState.PARTIAL: "Parcial",
    DetectState.NOT_APPLICABLE: "No aplicable",
    DetectState.UNKNOWN: "Desconocido",
}


@dataclass(frozen=True)
class DetectResult:
    state: DetectState
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class HandlerError(RuntimeError):
    pass


class SkipOperation(Exception):
    """Un handler u operación indica que no hay nada que hacer (no es un fallo)."""


@dataclass
class HandlerContext:
    tweak: Tweak
    env: EnvironmentInfo
    registry: Registry
    runner: Runner
    services: ServiceManager
    guard: ProtectionGuard
    dry_run: bool
    params: dict[str, Any] = field(default_factory=dict)
    session: Session | None = None
    state: dict[str, Any] = field(default_factory=dict)
    prior_state: dict[str, Any] = field(default_factory=dict)
    prior_session: Session | None = None
    planned: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ utilidades

    def plan(self, message: str) -> None:
        self.planned.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)
        log.info(message, extra={"tweak": self.tweak.id})

    def record(self, kind: ChangeKind, target: dict[str, Any], before: Any, after: Any) -> None:
        if self.session is not None:
            self.session.changes.append(Change(self.tweak.id, kind, target, before, after))

    def backup_key(self, hive: str, path: str) -> None:
        if self.dry_run or self.session is None:
            return
        exported = export_key(
            self.runner, self.registry.locate(hive, path), self.session.backup_dir
        )
        if exported:
            self.session.backups.append(str(exported))

    def set_registry(self, hive: str, path: str, name: str, value: RegValue) -> bool:
        """Escribe con snapshot del valor previo. Devuelve False si ya tenía ese valor."""
        self.guard.check_registry(hive, path)
        current = self.registry.read(hive, path, name)
        loc = self.registry.locate(hive, path)
        if values_equal(current, value):
            return False
        before = current.display() if current else "(no existe)"
        if self.dry_run:
            self.plan(f"Registro {loc}\\{name}: {before} → {value.display()}")
            return True
        key_existed = self.registry.key_exists(hive, path)
        self.registry.write(hive, path, name, value)
        self.record(
            "registry",
            {"hive": hive, "path": path, "name": name, "key_existed": key_existed},
            current.to_json() if current else None,
            value.to_json(),
        )
        return True

    def run_checked(self, args: list[str], what: str, timeout: int = 60) -> str:
        """Ejecuta un comando o lo planifica en dry-run. Lanza HandlerError si falla."""
        if self.dry_run:
            self.plan(f"Ejecutar: {what}")
            return ""
        result = self.runner.run(args, timeout=timeout)
        if not result.ok:
            raise HandlerError(f"{what}: {result.error_text()}")
        return result.stdout


Handler = Callable[[HandlerContext], Any]
_cache: dict[str, Handler] = {}


def resolve_handler(ref: str) -> Handler:
    """'tweaks.modulo:funcion' → callable. Solo se permiten módulos del paquete tweaks."""
    if ref in _cache:
        return _cache[ref]
    module_name, _, func_name = ref.partition(":")
    if not module_name.startswith(HANDLER_PACKAGE + ".") or not func_name:
        raise HandlerError(f"Referencia de handler no válida: {ref}")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise HandlerError(f"No se pudo importar {module_name}: {exc}") from exc
    func = getattr(module, func_name, None)
    if not callable(func):
        raise HandlerError(f"{ref} no existe o no es invocable")
    _cache[ref] = func
    return func
