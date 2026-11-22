"""v0.9.0: informes de error, estado de seguridad, página de soporte del modelo, programas del
fabricante y programas de inicio retrasados."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from core import crash
from core.engine import Engine
from core.environment import EnvironmentInfo
from core.logger import export_logs
from core.oem import find_oem_bloat, uninstall_command
from core.programs import Program
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.security import UAC_KEY, evaluate, read_security
from core.session import Session
from core.support import support_url
from core.tasks import TaskManager
from tests.conftest import USER_SID, FakeRunner
from tests.test_startup import APPROVED, RUN
from tests.test_v040 import analyze, report
from tweaks.startup import DELAYED_TASK_FOLDER, StartupManager

EngineFactory = Callable[..., Engine]


# --------------------------------------------------------------------------- informes de error


def test_crash_report_written_and_rotated(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(crash, "MAX_REPORTS", 2)
    for i in range(3):
        try:
            raise RuntimeError(f"fallo {i}")
        except RuntimeError as exc:
            path = crash.write_report(type(exc), exc, exc.__traceback__, "prueba", tmp_path)
    assert path is not None and "fallo 2" in path.read_text(encoding="utf-8")
    assert "Dónde: prueba" in path.read_text(encoding="utf-8")
    assert len(crash.reports(tmp_path)) == 2


def test_crash_hooks_installed(monkeypatch: Any) -> None:
    import threading

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    crash.install()
    assert sys.excepthook is not sys.__excepthook__
    assert threading.excepthook is not threading.__excepthook__


def test_log_export_includes_crash_reports(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "safetrim.jsonl").write_text("{}")
    (tmp_path / "crashes").mkdir()
    (tmp_path / "crashes" / "crash-1.txt").write_text("traza")
    out = export_logs(tmp_path / "out", log_dir=logs)
    assert (out / "crash-1.txt").exists() and (out / "safetrim.jsonl").exists()


# --------------------------------------------------------------------------- seguridad


GOOD = {
    "defender": {"av": True, "rt": True, "age": 1, "mode": "Normal"},
    "firewall": [{"name": "Domain", "on": True}, {"name": "Private", "on": True}],
    "license": 1,
    "bitlocker": "On",
    "system": {"maker": "HP", "model": "HP Laptop 15", "serial": "5CD123"},
}


def checks(data: dict, uac: tuple = (1, 5), env: EnvironmentInfo | None = None) -> dict:
    sec = evaluate(data, uac, env or EnvironmentInfo(last_update_days=5))
    return {c.name: c for c in sec.checks}


def test_security_all_good() -> None:
    found = checks(GOOD)
    assert all(c.ok is not False for c in found.values())
    assert found["Firewall"].ok and found["Antivirus (Windows Defender)"].ok
    assert evaluate(GOOD, (1, 5), EnvironmentInfo()).system.model == "HP Laptop 15"


def test_security_problems() -> None:
    bad = dict(
        GOOD,
        defender={"av": False, "rt": False, "age": 30, "mode": "Normal"},
        firewall=[{"name": "Public", "on": False}],
        license=0,
    )
    found = checks(bad, uac=(0, 5), env=EnvironmentInfo(reboot_pending=True))
    assert found["Antivirus (Windows Defender)"].ok is False
    assert found["Definiciones de virus"].ok is False
    assert "Public" in found["Firewall"].detail
    assert found["Windows activado"].ok is False
    assert found["Control de cuentas (UAC)"].ok is False
    assert found["Actualizaciones"].ok is False


def test_security_passive_defender_and_no_bitlocker() -> None:
    found = checks(dict(GOOD, defender={"mode": "Passive Mode"}, bitlocker="Off"))
    assert found["Antivirus"].ok is None
    assert found["Cifrado del disco (BitLocker)"].ok is None  # recomendación, no fallo


def test_security_critical_problems_reach_verdict() -> None:
    rep = report()
    rep.security = evaluate(dict(GOOD, firewall=[{"name": "Public", "on": False}]), (1, 5), rep.env)
    assert any(f.title == "Seguridad: Firewall" and f.level == "critical" for f in analyze(rep))


def test_read_security_combines_powershell_and_registry() -> None:
    backend = MemoryRegistryBackend()
    backend.seed("HKLM", UAC_KEY, "EnableLUA", RegValue("REG_DWORD", 1))
    backend.seed("HKLM", UAC_KEY, "ConsentPromptBehaviorAdmin", RegValue("REG_DWORD", 0))
    runner = FakeRunner()
    runner.respond_json("Get-MpComputerStatus", GOOD)
    sec = read_security(Registry(backend), runner, EnvironmentInfo(system_drive="C:"))
    uac = next(c for c in sec.checks if c.name.startswith("Control de cuentas"))
    assert uac.ok is False and "sin preguntar" in uac.detail
    assert "Get-NetFirewallProfile" in runner.scripts[-1]


# --------------------------------------------------------------------------- soporte del modelo


def test_support_urls() -> None:
    assert support_url("Dell Inc.", "ABC1234").endswith("/servicetag/ABC1234/drivers")
    assert support_url("Dell Inc.", "To be filled by O.E.M.").endswith("/product-support/")
    assert support_url("HP", "5CD") == "https://support.hp.com/drivers"
    assert "lenovo" in support_url("LENOVO", "PF12AB")
    assert support_url("Fabricante Raro", "1") == ""


# --------------------------------------------------------------------------- fabricante


def test_oem_bloat_detection_and_msi_uninstall() -> None:
    programs = [
        Program("a", "McAfee LiveSafe", uninstall_string=r'"C:\McAfee\uninst.exe"'),
        Program("b", "HP Audio Switch", uninstall_string="x"),  # útil: no está en la lista
        Program("c", "WildTangent Games", uninstall_string="MsiExec.exe /I{1234}"),
        Program("d", "Norton Security"),  # sin desinstalador registrado: no se ofrece
    ]
    found = find_oem_bloat(programs)
    assert [c.program.name for c in found] == ["McAfee LiveSafe", "WildTangent Games"]
    assert uninstall_command(found[1].program) == "MsiExec.exe /X{1234}"
    assert uninstall_command(found[0].program) == r'"C:\McAfee\uninst.exe"'


# --------------------------------------------------------------------------- inicio retrasado


def test_delay_startup_entry_and_undo(
    make_engine: EngineFactory,
    backend: MemoryRegistryBackend,
    runner: FakeRunner,
    env: EnvironmentInfo,
) -> None:
    backend.write(
        "HKU", rf"{USER_SID}\{RUN}", "OneDrive", RegValue("REG_SZ", r'"C:\OD\OneDrive.exe" /bg')
    )
    runner.respond_json("MSFT_TaskLogonTrigger", [])
    engine = make_engine()
    manager = StartupManager(Registry(backend, USER_SID), runner, TaskManager(runner), env)
    entry = next(e for e in manager.list() if e.name == "OneDrive")

    session = Session.new("apply")
    manager.delay(entry, session, "PC\\Ana")
    engine.store.save(session)
    script = runner.scripts[-1]
    assert "-AtLogOn -User 'PC\\Ana'" in script and "'PT90S'" in script
    assert "'C:\\OD\\OneDrive.exe'" in script and "-Argument '/bg'" in script
    assert f"-TaskPath '{DELAYED_TASK_FOLDER}'" in script
    approved = backend.read("HKU", rf"{USER_SID}\{APPROVED}", "OneDrive")
    assert approved is not None and approved.data[0] == 3  # entrada original desactivada

    revert = engine.revert(session.id)
    assert {r.status for r in revert.results.values()} == {"reverted"}
    assert any("Unregister-ScheduledTask" in s and "'OneDrive'" in s for s in runner.scripts)
    assert backend.read("HKU", rf"{USER_SID}\{APPROVED}", "OneDrive") is None


def test_delay_rejects_tasks_and_disabled_entries(
    backend: MemoryRegistryBackend, runner: FakeRunner, env: EnvironmentInfo
) -> None:
    import pytest

    backend.write("HKU", rf"{USER_SID}\{RUN}", "X", RegValue("REG_SZ", r"C:\x.exe"))
    runner.respond_json("MSFT_TaskLogonTrigger", [])
    manager = StartupManager(Registry(backend, USER_SID), runner, TaskManager(runner), env)
    entry = next(e for e in manager.list() if e.name == "X")
    with pytest.raises(ValueError, match="usuario"):
        manager.delay(entry, Session.new("apply"), "")
    entry.enabled = False
    with pytest.raises(ValueError, match="activos"):
        manager.delay(entry, Session.new("apply"), "PC\\Ana")
