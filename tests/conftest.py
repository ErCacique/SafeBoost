"""Fixtures comunes: registro en memoria, runner falso, entorno y motor configurables."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Debe fijarse ANTES de importar core: las rutas de datos se calculan al importar.
os.environ.setdefault("WINTUNE_HOME", tempfile.mkdtemp(prefix="wintune-tests-"))

import pytest

from core.appx import AppxManager
from core.catalog import Catalog, Tweak
from core.constants import SERVICES_KEY
from core.engine import Engine
from core.environment import EnvironmentInfo
from core.process import CommandResult
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.restore import RestoreManager
from core.services import ServiceManager
from core.session import SessionStore
from core.settings import Settings
from core.tasks import TaskManager

USER_SID = "S-1-5-21-111-222-333-1001"

Responder = Callable[[str], Any]


class FakeRunner:
    """Registra cada llamada. Las respuestas se configuran por subcadena del comando/script."""

    def __init__(self, backend: MemoryRegistryBackend | None = None) -> None:
        # Con backend, "sc config" escribe el Start del servicio como hace Windows de verdad.
        self.backend = backend
        self.calls: list[list[str]] = []
        self.scripts: list[str] = []
        self.json_responses: list[tuple[str, Any]] = []
        self.fail_on: list[str] = []
        self.restore_sequence = 0
        self.create_restore_points = True
        self.task_states: dict[str, str] = {}
        self.appx_installed: list[str] = []

    # -- configuración
    def respond_json(self, needle: str, value: Any) -> None:
        self.json_responses.append((needle, value))

    # -- interfaz Runner
    def run(self, args: list[str], timeout: int = 60, encoding: str | None = None) -> CommandResult:
        self.calls.append(list(args))
        joined = " ".join(args)
        if any(needle in joined for needle in self.fail_on):
            return CommandResult(tuple(args), 5, "", "Acceso denegado.")
        if self.backend is not None and len(args) >= 5 and args[1:2] == ["config"]:
            start = {"auto": 2, "delayed-auto": 2, "demand": 3, "disabled": 4}[args[4]]
            key = f"{SERVICES_KEY}\\{args[2]}"
            self.backend.write("HKLM", key, "Start", RegValue("REG_DWORD", start))
            delayed = 1 if args[4] == "delayed-auto" else 0
            self.backend.write("HKLM", key, "DelayedAutostart", RegValue("REG_DWORD", delayed))
        return CommandResult(tuple(args), 0, "", "")

    def powershell(self, script: str, timeout: int = 120) -> CommandResult:
        self.scripts.append(script)
        if any(needle in script for needle in self.fail_on):
            return CommandResult(("powershell",), 1, "", "Error simulado")
        if "Checkpoint-Computer" in script and self.create_restore_points:
            self.restore_sequence += 1
        for verb, state in (
            ("Disable-ScheduledTask", "Disabled"),
            ("Enable-ScheduledTask", "Ready"),
        ):
            if script.startswith(verb):
                path = script.split("'")[1] + script.split("'")[3]
                self.task_states[path] = state
        if "Remove-AppxPackage" in script:
            full = script.split("'")[1]
            self.appx_installed = [n for n in self.appx_installed if not full.startswith(n + "_")]
        return CommandResult(("powershell",), 0, "", "")

    def powershell_json(self, script: str, timeout: int = 120) -> Any:
        self.scripts.append(script)
        for needle, value in self.json_responses:
            if needle in script:
                return value(script) if callable(value) else value
        if "SequenceNumber" in script:
            return self.restore_sequence or None
        if "Get-ScheduledTask -TaskPath" in script:
            path = script.split("'")[1] + script.split("'")[3]
            return {"state": self.task_states.get(path, "Ready")}
        if "Get-AppxPackage" in script:
            return {
                "installed": [
                    {"Name": n, "PackageFullName": f"{n}_1.0_x64__x"} for n in self.appx_installed
                ],
                "provisioned": [],
            }
        return None


@pytest.fixture
def backend() -> MemoryRegistryBackend:
    b = MemoryRegistryBackend()
    for name, start in {
        "DiagTrack": 2,
        "Fax": 3,
        "MapsBroker": 2,
        "SysMain": 2,
        "WinDefend": 2,
        "Spooler": 2,
    }.items():
        b.seed("HKLM", f"{SERVICES_KEY}\\{name}", "Start", RegValue("REG_DWORD", start))
        b.seed("HKLM", f"{SERVICES_KEY}\\{name}", "Type", RegValue("REG_DWORD", 16))
    return b


@pytest.fixture
def runner(backend: MemoryRegistryBackend) -> FakeRunner:
    return FakeRunner(backend)


@pytest.fixture
def env() -> EnvironmentInfo:
    return EnvironmentInfo(
        build=22631,
        edition="pro",
        edition_id="Professional",
        disk_type="ssd",
        chassis="desktop",
        is_admin=True,
        interactive_sid=USER_SID,
        system_drive="C:",
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(dry_run=False, export_reg_backups=True)


@pytest.fixture
def make_engine(
    backend: MemoryRegistryBackend,
    runner: FakeRunner,
    env: EnvironmentInfo,
    settings: Settings,
    tmp_path: Path,
) -> Callable[..., Engine]:
    def factory(catalog: Catalog | None = None, **env_overrides: Any) -> Engine:
        for key, value in env_overrides.items():
            setattr(env, key, value)
        registry = Registry(backend, env.interactive_sid)
        services = ServiceManager(registry, runner)
        return Engine(
            catalog=catalog or Catalog.load(),
            env=env,
            registry=registry,
            runner=runner,
            services=services,
            appx=AppxManager(runner),
            tasks=TaskManager(runner),
            restore=RestoreManager(registry, runner, env.system_drive),
            store=SessionStore(tmp_path / "sessions"),
            settings=settings,
        )

    return factory


def make_tweak(**overrides: Any) -> Tweak:
    """Tweak mínimo válido para catálogos de prueba."""
    base: dict[str, Any] = {
        "id": "test.sample",
        "name": "Tweak de prueba",
        "description": "Descripción de prueba suficientemente larga.",
        "rationale": "Justificación de prueba suficientemente larga.",
        "category": "privacy",
        "level": 1,
        "risk": "bajo",
        "windows": {
            "min_build": 19045,
            "max_build": None,
            "editions": ["home", "pro", "enterprise", "education"],
        },
        "kind": "tweak",
        "reversible": True,
        "auto_profile": True,
        "confirm_double": False,
        "reboot_required": False,
        "requires": {},
        "auto_when": {},
        "apply": [],
        "revert": [{"op": "restore_snapshot"}],
        "detect": [{"op": "match_apply"}],
    }
    base.update(overrides)
    return Tweak.from_dict(base)
