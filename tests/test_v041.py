"""v0.4.1: arranque más rápido. Una sola PowerShell para detectar el entorno, dxdiag (HAGS) en
segundo plano, prioridad normal durante la detección y progreso visible por pasos."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from core import engine as engine_module
from core.app import build_context
from core.constants import SLOW_CHECKS, WU_REBOOT_KEYS
from core.engine import Engine
from core.environment import EnvironmentDetector, facts_script
from core.process import CommandError
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.settings import Settings
from tests.conftest import FakeRunner

EngineFactory = Callable[..., Engine]
HAGS = "tweaks.gaming:hags_supported"

FACTS = {
    "sid": "S-1-5-21-1-2-3-1001",
    "disk": {"media": "SSD", "bus": "SATA"},
    "chassis": [10],
    "domain": {"part": False, "domain": "WORKGROUP"},
    "printers": ["HP DeskJet 2700", "Microsoft Print to PDF"],
    "hotfix": 40,
}


def detector(
    facts: Any = FACTS, backend: MemoryRegistryBackend | None = None
) -> tuple[EnvironmentDetector, FakeRunner]:
    runner = FakeRunner()
    runner.respond_json("Win32_SystemEnclosure", facts)
    return EnvironmentDetector(Registry(backend or MemoryRegistryBackend()), runner), runner


# --------------------------------------------------------------------------- una sola PowerShell


def test_detection_uses_a_single_powershell_call() -> None:
    det, runner = detector()
    env = det.detect()
    assert len(runner.scripts) == 1
    assert env.disk_type == "ssd"
    assert env.chassis == "laptop"
    assert env.domain_joined is False
    assert env.printers == ["HP DeskJet 2700"]  # la impresora virtual no cuenta
    assert env.last_update_days == 40
    assert env.interactive_sid == "S-1-5-21-1-2-3-1001"


def test_one_failed_fact_only_affects_that_value() -> None:
    facts = dict(FACTS, printers=None, printers_err="El servicio Spooler no responde")
    env = detector(facts)[0].detect()
    assert env.printers == []
    assert any(w.startswith("printers:") and "Spooler" in w for w in env.warnings)
    assert env.disk_type == "ssd"
    assert env.last_update_days == 40


def test_powershell_failure_keeps_detecting_the_rest() -> None:
    class Broken(FakeRunner):
        def powershell_json(self, script: str, timeout: int = 120) -> Any:
            raise CommandError("PowerShell falló")

    env = EnvironmentDetector(Registry(MemoryRegistryBackend()), Broken()).detect()
    assert any(w.startswith("query_facts:") for w in env.warnings)
    assert env.disk_type == "unknown"
    assert env.fixed_drives is not None  # los pasos sin PowerShell siguen funcionando


def test_reboot_pending_still_read_from_registry() -> None:
    backend = MemoryRegistryBackend()
    backend.seed("HKLM", WU_REBOOT_KEYS[1], "x", RegValue("REG_DWORD", 1))
    env = detector(backend=backend)[0].detect()
    assert env.reboot_pending is True


def test_progress_and_timings_per_step() -> None:
    steps: list[str] = []
    det, _runner = detector()
    det.detect(steps.append)
    assert "Disco, equipo, impresoras y actualizaciones" in steps
    assert steps[0] == "Versión de Windows"
    assert {"windows", "query_facts", "mdm", "updates"} <= set(det.timings)
    assert all(ms >= 0 for ms in det.timings.values())


def test_facts_script_isolates_each_query_and_bounds_printers() -> None:
    script = facts_script("EQUIPO\\O'Brien", "C:")
    for key in ("sid", "disk", "chassis", "domain", "printers", "hotfix"):
        assert f"$r.{key}_err" in script
    assert "'EQUIPO\\O''Brien'" in script  # comilla escapada para PowerShell
    assert "Win32_Printer -OperationTimeoutSec" in script
    assert "Get-Printer" not in script  # puede colgarse con impresoras de red apagadas
    assert facts_script("", "C:").count("NTAccount") == 0


# --------------------------------------------------------------------------- dxdiag diferido


@pytest.fixture
def counted_check(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = engine_module.resolve_handler

    def fake(ref: str) -> Any:
        if ref == HAGS:
            return lambda _ctx: calls.append(ref) or True
        return real(ref)

    monkeypatch.setattr(engine_module, "resolve_handler", fake)
    return calls


def test_hags_is_in_slow_checks() -> None:
    assert HAGS in SLOW_CHECKS


def test_deferred_slow_check_never_runs_synchronously(
    make_engine: EngineFactory, counted_check: list[str]
) -> None:
    engine = make_engine()
    engine.defer_slow_checks = True
    engine.warm_checks()
    assert counted_check == []
    assert engine.check(HAGS) is None
    assert engine.check_pending(HAGS) is True
    reasons = engine.evaluate(engine.catalog.get("gaming.hags")).reasons
    assert any("comprobando compatibilidad" in r for r in reasons)
    assert counted_check == []

    assert engine.run_slow_checks() == [HAGS]
    assert counted_check == [HAGS]
    assert engine.check(HAGS) is True
    assert engine.check_pending(HAGS) is False
    assert engine.run_slow_checks() == []  # ya resuelta: no repite dxdiag


def test_without_deferral_checks_run_inline(
    make_engine: EngineFactory, counted_check: list[str]
) -> None:
    engine = make_engine()  # CLI y tests: comportamiento de siempre
    engine.warm_checks()
    assert counted_check == [HAGS]
    assert engine.check(HAGS) is True


def test_broken_check_counts_as_unsupported(
    make_engine: EngineFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_ref: str) -> Any:
        def handler(_ctx: Any) -> bool:
            raise RuntimeError("dxdiag roto")

        return handler

    monkeypatch.setattr(engine_module, "resolve_handler", boom)
    assert make_engine().check(HAGS) is False


# --------------------------------------------------------------------------- prioridad y progreso


class PriorityRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.low_priority = True
        self.seen: list[bool] = []

    def powershell_json(self, script: str, timeout: int = 120) -> Any:
        self.seen.append(self.low_priority)
        return FACTS if "Win32_SystemEnclosure" in script else None


def test_build_context_detects_at_normal_priority_then_restores(tmp_path: Any) -> None:
    runner = PriorityRunner()
    steps: list[str] = []
    app = build_context(
        settings=Settings(),
        backend=MemoryRegistryBackend(),
        runner=runner,
        defer_slow_checks=True,
        progress=steps.append,
    )
    assert runner.seen and not any(runner.seen)  # nada con prioridad baja durante el arranque
    assert runner.low_priority is True  # restaurada para el resto de la sesión
    assert app.engine.defer_slow_checks is True
    assert "Comprobaciones de hardware" in steps
    assert app.env.disk_type == "ssd"
