"""v0.5.0: pantallas pequeñas, instalador + portable, qué retrasa el arranque, navegadores en
segundo plano y kit de rescate (--undo-all)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import core.app
import core.constants as constants
from core.boot import BootReport, aggregate, read_boot_culprits
from core.engine import Engine
from core.metrics import GIB
from core.process import CommandError
from core.registry import MemoryRegistryBackend, RegValue
from tests.conftest import USER_SID, FakeRunner
from tests.test_v040 import analyze, report

EngineFactory = Callable[..., Engine]
ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- pantallas pequeñas


def test_window_fits_small_laptop_at_125_percent() -> None:
    from ui.app import fit_window

    geometry, minimum, maximize = fit_window(1366, 768, 1.25)
    width, rest = geometry.split("x")
    height = rest.split("+")[0]
    assert int(width) <= 1366 / 1.25 and int(height) <= 768 / 1.25
    assert minimum[0] <= int(width) and minimum[1] <= int(height)
    assert maximize is True


def test_window_keeps_preferred_size_on_big_screens() -> None:
    from ui.app import fit_window

    geometry, _minimum, maximize = fit_window(1920, 1080, 1.0)
    assert geometry.startswith("1280x820")
    assert maximize is False


# --------------------------------------------------------------------------- portable


def test_portable_marker_moves_data_next_to_exe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "SafeTrim.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv("SAFETRIM_HOME", raising=False)
    monkeypatch.delenv("WINTUNE_HOME", raising=False)
    assert constants._portable_home() is None
    (tmp_path / constants.PORTABLE_MARKER).write_text("x")
    assert constants._portable_home() == tmp_path / "SafeTrimData"
    assert constants._home_override() == str(tmp_path / "SafeTrimData")
    monkeypatch.setenv("SAFETRIM_HOME", str(tmp_path / "otra"))
    assert constants._home_override() == str(tmp_path / "otra")  # la variable manda


def test_not_portable_when_running_from_source() -> None:
    assert getattr(sys, "frozen", False) is False
    assert constants._portable_home() is None


def test_installer_and_spec_are_onedir_with_rescue_shortcut() -> None:
    spec = (ROOT / "packaging" / "SafeTrim.spec").read_text(encoding="utf-8")
    assert "COLLECT(" in spec and "exclude_binaries=True" in spec
    iss = (ROOT / "packaging" / "SafeTrim.iss").read_text(encoding="utf-8")
    assert 'Parameters: "--undo-all"' in iss
    assert "PrivilegesRequired=admin" in iss
    assert "PostRebootMetrics" in iss  # la desinstalación quita la tarea temporal
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "portable.txt" in workflow and "SafeTrim-Setup-" in workflow


# --------------------------------------------------------------- qué retrasa el arranque


ONEDRIVE = "Microsoft OneDrive"
EVENTS = {
    "boots": 6,
    "items": [
        {
            "id": 101,
            "name": "OneDrive.exe",
            "friendly": "Microsoft OneDrive",
            "degradation": "6000",
        },
        {
            "id": 101,
            "name": "onedrive.exe",
            "friendly": "Microsoft OneDrive",
            "degradation": "4000",
        },
        {"id": 103, "name": "HpSvc", "friendly": "HP Service", "total": "3500", "degradation": ""},
        {"id": 102, "name": "fast.sys", "friendly": "Driver rápido", "degradation": "300"},
        {"id": 999, "name": "raro", "degradation": "99999"},
        "basura",
    ],
}


def test_boot_culprits_grouped_sorted_and_filtered() -> None:
    boot = aggregate(EVENTS)
    assert boot.boots == 6
    names = [c.name for c in boot.culprits]
    assert names == ["Microsoft OneDrive", "HP Service"]  # el driver de 0,3 s no se muestra
    onedrive = boot.culprits[0]
    assert onedrive.count == 2 and onedrive.avg_ms == 5000 and onedrive.max_ms == 6000
    assert onedrive.kind == "programa" and "Inicio" in onedrive.advice
    hp = boot.culprits[1]
    assert hp.kind == "servicio" and hp.avg_ms == 3500  # sin DegradationTime usa TotalTime


def test_boot_culprits_unreadable_log() -> None:
    class Broken(FakeRunner):
        def powershell_json(self, script: str, timeout: int = 120) -> Any:
            raise CommandError("acceso denegado")

    assert read_boot_culprits(Broken()).available is False
    empty = read_boot_culprits(FakeRunner())
    assert empty.available is True and empty.culprits == []


def test_boot_culprit_script_reads_events_101_to_110() -> None:
    runner = FakeRunner()
    runner.respond_json("DegradationTime", EVENTS)
    read_boot_culprits(runner)
    script = runner.scripts[-1]
    assert "Id=101,102,103,104,105,106,107,108,109,110" in script
    assert "AddDays(-60)" in script


def test_slow_boot_culprit_appears_in_verdict() -> None:
    rep = report()
    rep.boot = aggregate(EVENTS)
    finding = next(f for f in analyze(rep) if f.title == "Algo retrasa el arranque")
    assert "Microsoft OneDrive" in finding.detail
    assert "en 2 de 6 arranques" in finding.detail
    rep.boot = BootReport(boots=6)
    assert "Algo retrasa el arranque" not in [f.title for f in analyze(rep)]


# --------------------------------------------------------------------------- navegadores


@pytest.mark.parametrize("ram_gib, preselected", [(3.4, True), (16, False)])
def test_browser_tweaks_preselected_only_with_low_ram(
    make_engine: EngineFactory,
    monkeypatch: pytest.MonkeyPatch,
    ram_gib: float,
    preselected: bool,
) -> None:
    import tweaks.browsers as browsers

    monkeypatch.setattr(
        browsers.psutil, "virtual_memory", lambda: SimpleNamespace(total=int(ram_gib * GIB))
    )
    engine = make_engine()
    applicability = engine.evaluate(engine.catalog.get("performance.edge_startup_boost"), level=2)
    assert applicability.applicable
    assert applicability.preselect is preselected


def test_chrome_tweak_requires_chrome(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    tweak = engine.catalog.get("performance.chrome_background")
    assert not engine.evaluate(tweak).applicable
    path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    backend.seed("HKU", rf"{USER_SID}\{path}", "", RegValue("REG_SZ", "chrome.exe"))
    assert make_engine().evaluate(tweak).applicable  # instalado solo para el usuario


def test_browser_policies_skipped_on_managed_devices(make_engine: EngineFactory) -> None:
    engine = make_engine(domain_joined=True)
    session = engine.apply(["performance.edge_background"])
    assert session.results["performance.edge_background"].status != "applied"


def test_edge_policy_applies_and_reverts(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    session = engine.apply(["performance.edge_startup_boost"])
    key = r"SOFTWARE\Policies\Microsoft\Edge"
    assert backend.read("HKLM", key, "StartupBoostEnabled") == RegValue("REG_DWORD", 0)
    engine.revert(session.id)
    assert backend.read("HKLM", key, "StartupBoostEnabled") is None


# --------------------------------------------------------------------------- kit de rescate


@pytest.fixture
def rescue(make_engine: EngineFactory, monkeypatch: pytest.MonkeyPatch) -> Engine:
    engine = make_engine()
    monkeypatch.setattr(
        core.app,
        "build_context",
        lambda **_kw: SimpleNamespace(engine=engine, store=engine.store),
    )
    return engine


def test_undo_all_with_nothing_to_undo(rescue: Engine, capsys: pytest.CaptureFixture) -> None:
    import main

    assert main.undo_all_cli(yes=True, demo=True) == 0
    assert "No hay cambios" in capsys.readouterr().out


def test_undo_all_asks_and_can_be_cancelled(rescue: Engine, backend: MemoryRegistryBackend) -> None:
    import main

    rescue.apply(["performance.edge_startup_boost"])
    asked: list[str] = []
    code = main.undo_all_cli(yes=False, demo=True, ask=lambda q: asked.append(q) or False)
    assert code == 2 and asked
    key = r"SOFTWARE\Policies\Microsoft\Edge"
    assert backend.read("HKLM", key, "StartupBoostEnabled") is not None  # nada deshecho


def test_undo_all_reverts_every_session_newest_first(
    rescue: Engine, backend: MemoryRegistryBackend, capsys: pytest.CaptureFixture
) -> None:
    import main

    first = rescue.apply(["performance.edge_startup_boost"])
    second = rescue.apply(["performance.edge_background"])
    assert main.undo_all_cli(yes=True, demo=True) == 0
    out = capsys.readouterr().out
    assert out.index(second.id) < out.index(first.id)
    key = r"SOFTWARE\Policies\Microsoft\Edge"
    assert backend.read("HKLM", key, "StartupBoostEnabled") is None
    assert backend.read("HKLM", key, "BackgroundModeEnabled") is None
    pending = [s for s in rescue.store.list() if s.kind == "apply" and not s.reverted_by]
    assert pending == []


def test_undo_all_flag_is_parsed() -> None:
    import main

    assert main._parse_args(["--undo-all", "--yes"]).undo_all is True


def test_boot_log_missing_is_reported_as_unavailable() -> None:
    boot = aggregate({"available": False, "boots": 0, "items": []})
    assert boot.available is False and boot.error == ""


def test_boot_culprit_accepts_file_name_field_and_full_paths() -> None:
    boot = aggregate(
        {
            "boots": 2,
            "items": [
                {"id": 101, "file_name": r"C:\Apps\Lento.exe", "degradation": "5000"},
                {"id": 101, "name": r"C:\Apps\lento.exe", "degradation": "3000"},
            ],
        }
    )
    assert len(boot.culprits) == 1
    assert boot.culprits[0].file == "Lento.exe" and boot.culprits[0].count == 2


def test_boot_script_survives_missing_log() -> None:
    from core.boot import _script

    script = _script(60)
    assert "-ListLog" in script and "IsEnabled" in script
    assert script.count("catch") >= 2  # cada Get-WinEvent en su try/catch


def test_boot_query_failure_keeps_error_text() -> None:
    class Broken(FakeRunner):
        def powershell_json(self, script: str, timeout: int = 120) -> Any:
            raise CommandError("PowerShell falló: algo")

    assert "algo" in read_boot_culprits(Broken()).error
