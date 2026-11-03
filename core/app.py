"""Composición de dependencias: construye el motor real (Windows) o uno simulado (desarrollo)."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from core.appx import AppxManager
from core.catalog import Catalog
from core.engine import Engine
from core.environment import EnvironmentDetector, EnvironmentInfo
from core.metrics import MetricsStore
from core.process import Runner, SubprocessRunner
from core.registry import MemoryRegistryBackend, Registry, RegistryBackend, WinRegBackend
from core.restore import RestoreManager
from core.services import ServiceManager
from core.session import SessionStore
from core.settings import Settings
from core.tasks import TaskManager


@dataclass
class AppContext:
    engine: Engine
    env: EnvironmentInfo
    runner: Runner
    registry: Registry
    settings: Settings
    metrics: MetricsStore
    store: SessionStore


def build_context(
    settings: Settings | None = None,
    backend: RegistryBackend | None = None,
    runner: Runner | None = None,
    env: EnvironmentInfo | None = None,
    catalog: Catalog | None = None,
    warm_checks: bool = True,
) -> AppContext:
    """Construye el contexto completo. Llamar desde un hilo de trabajo, nunca desde Tk:
    detecta el entorno y ejecuta las comprobaciones de hardware (lentas)."""
    settings = settings or Settings.load()
    runner = runner or SubprocessRunner()
    if backend is None:
        backend = WinRegBackend() if sys.platform == "win32" else MemoryRegistryBackend()
    base_registry = Registry(backend)
    if env is None:
        env = EnvironmentDetector(base_registry, runner).detect()
    registry = Registry(backend, env.interactive_sid)
    services = ServiceManager(registry, runner)
    store = SessionStore()
    engine = Engine(
        catalog=catalog or Catalog.load(),
        env=env,
        registry=registry,
        runner=runner,
        services=services,
        appx=AppxManager(runner, env.interactive_sid, _run_as(env)),
        tasks=TaskManager(runner),
        restore=RestoreManager(registry, runner, env.system_drive),
        store=store,
        settings=settings,
    )
    if warm_checks:
        engine.warm_checks()
    return AppContext(engine, env, runner, registry, settings, MetricsStore(), store)


def _run_as(env: EnvironmentInfo) -> str | None:
    """Usuario de la sesión si WinTune se elevó con otra cuenta; None si es la misma."""
    interactive = (env.interactive_user or "").lower()
    elevated = (env.elevated_user or "").lower()
    if interactive and elevated and interactive != elevated:
        return env.interactive_user
    return None
