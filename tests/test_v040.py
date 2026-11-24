"""v0.4.0: diagnóstico, Windows Update, Windows 11, Windows.old, recomendación por RAM,
prioridad de procesos, aviso de versión nueva y asistente de primer arranque."""

from __future__ import annotations

import io
import urllib.error
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core import diagnostics, process
from core.constants import (
    CLEANMGR_PREVIOUS_INSTALLS_KEY,
    WU_REBOOT_KEYS,
)
from core.diagnostics import (
    DiagnosticReport,
    HardwareInfo,
    ProcessUsage,
    analyze,
    read_hardware,
    sample_processes,
    win11_requirements,
)
from core.engine import Engine
from core.environment import (
    EnvironmentDetector,
    EnvironmentInfo,
    UpdateStatus,
    read_update_status,
)
from core.metrics import GIB, Snapshot, recommend_profile
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.update_check import ReleaseInfo, check_latest, parse_version
from tests.conftest import FakeRunner

EngineFactory = Callable[..., Engine]


def snapshot(
    ram_total: float = 16 * GIB,
    ram_percent: float = 40,
    cpu: float = 10,
    disk_total: float = 500 * GIB,
    disk_free: float = 200 * GIB,
) -> Snapshot:
    used = ram_total * ram_percent / 100
    return Snapshot(
        "2026-11-21T10:00:00",
        int(ram_total),
        int(ram_total - used),
        ram_percent,
        cpu,
        int(disk_total),
        int(disk_free),
        150,
    )


def report(
    env: EnvironmentInfo | None = None,
    snap: Snapshot | None = None,
    hardware: HardwareInfo | None = None,
    top_cpu: list[ProcessUsage] | None = None,
    top_memory: list[ProcessUsage] | None = None,
    updates: UpdateStatus | None = None,
) -> DiagnosticReport:
    env = env or EnvironmentInfo(build=22631, edition="pro", disk_type="ssd")
    snap = snap or snapshot()
    rep = DiagnosticReport(
        env=env,
        snapshot=snap,
        disk_total=snap.disk_total,
        top_cpu=top_cpu or [],
        top_memory=top_memory or [],
        hardware=hardware,
        updates=updates or UpdateStatus(last_update_days=5),
    )
    rep.win11 = win11_requirements(rep)
    return rep


def titles(rep: DiagnosticReport) -> list[str]:
    return [f.title for f in analyze(rep)]


# --------------------------------------------------------------------------- 1. diagnóstico


def test_low_ram_with_free_slot_recommends_adding_a_module() -> None:
    hw = HardwareInfo(threads=4, slots=2, modules=[int(3.5 * GIB)], max_capacity=16 * GIB)
    findings = analyze(report(snap=snapshot(ram_total=3.4 * GIB, ram_percent=90), hardware=hw))
    assert findings[0].level == "critical"
    assert findings[0].title == "Poca memoria RAM"
    assert "1 ranura(s) libre(s)" in findings[0].detail
    assert "16.0 GB" in findings[0].detail


def test_low_ram_with_full_slots_recommends_replacing() -> None:
    hw = HardwareInfo(threads=4, slots=1, modules=[4 * GIB])
    findings = analyze(report(snap=snapshot(ram_total=3.8 * GIB), hardware=hw))
    assert "sustituir un módulo" in findings[0].detail


def test_memory_pressure_names_the_biggest_consumer() -> None:
    chrome = ProcessUsage("chrome.exe", 5, 3 * GIB, count=14)
    findings = analyze(report(snap=snapshot(ram_percent=92), top_memory=[chrome]))
    pressure = next(f for f in findings if f.title == "Memoria casi llena")
    assert "chrome.exe (14 procesos)" in pressure.detail


def test_process_hog_explains_known_windows_process() -> None:
    tiworker = ProcessUsage("TiWorker.exe", 70, 200 * 1024**2)
    findings = analyze(report(snap=snapshot(cpu=95), top_cpu=[tiworker]))
    hog = next(f for f in findings if f.title == "Proceso acaparando la CPU")
    assert hog.level == "warning"
    assert "Windows Update" in hog.detail


def test_reboot_pending_and_stale_updates() -> None:
    assert "Reinicio pendiente de Windows Update" in titles(
        report(updates=UpdateStatus(reboot_pending=True))
    )
    assert "Windows sin actualizar" in titles(report(updates=UpdateStatus(last_update_days=200)))


def test_hdd_weak_cpu_and_low_disk() -> None:
    env = EnvironmentInfo(build=22631, edition="pro", disk_type="hdd")
    hw = HardwareInfo(cpu_name="Celeron N3060", threads=2, slots=1, modules=[8 * GIB])
    found = titles(report(env=env, hardware=hw, snap=snapshot(disk_free=20 * GIB)))
    assert {"Disco mecánico (HDD)", "Procesador modesto", "Poco espacio en disco"} <= set(found)


def test_healthy_machine_says_no_clear_bottleneck() -> None:
    findings = analyze(report())
    assert findings[0].level == "ok"
    assert len(findings) == 1


def test_findings_sorted_by_severity() -> None:
    env = EnvironmentInfo(build=19045, edition="home", disk_type="hdd")
    levels = [f.level for f in analyze(report(env=env, snap=snapshot(ram_total=3 * GIB)))]
    order = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
    assert levels == sorted(levels, key=order.__getitem__)


def test_read_hardware_parses_powershell_output() -> None:
    runner = FakeRunner()
    runner.respond_json(
        "Win32_PhysicalMemoryArray",
        {
            "cpu": " Intel Celeron ",
            "cores": 2,
            "threads": 2,
            "mhz": 1600,
            "slots": 2,
            "max_kb": 8 * 1024 * 1024,
            "modules": 4 * GIB,  # PowerShell aplana un único módulo a escalar
            "tpm": "2.0, 0, 1.16",
            "secure_boot": False,
            "firmware": "UEFI",
        },
    )
    hw = read_hardware(runner)
    assert hw is not None
    assert hw.cpu_name == "Intel Celeron"
    assert hw.modules == [4 * GIB]
    assert hw.free_slots == 1
    assert hw.max_capacity == 8 * GIB
    assert hw.tpm2 is True
    assert hw.secure_boot is False


def test_read_hardware_failure_returns_none() -> None:
    class Failing(FakeRunner):
        def powershell_json(self, script: str, timeout: int = 120) -> Any:
            raise process.CommandError("WMI roto")

    assert read_hardware(Failing()) is None


def test_sample_processes_groups_by_name_and_normalizes_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Proc:
        def __init__(self, pid: int, name: str, cpu: float, rss: int) -> None:
            self.pid = pid
            self.info = {"name": name}
            self._cpu = cpu
            self._rss = rss

        def cpu_percent(self, _interval: Any) -> float:
            return self._cpu

        def memory_info(self) -> SimpleNamespace:
            return SimpleNamespace(rss=self._rss)

    procs = [
        Proc(0, "System Idle Process", 300, 0),
        Proc(10, "chrome.exe", 40, 100),
        Proc(11, "Chrome.exe", 20, 50),
        Proc(12, "explorer.exe", 4, 70),
    ]
    monkeypatch.setattr(diagnostics.psutil, "process_iter", lambda _attrs: procs)
    monkeypatch.setattr(diagnostics.psutil, "cpu_count", lambda: 4)
    result = {p.name.lower(): p for p in sample_processes(0, sleep=lambda _s: None)}
    assert "system idle process" not in result
    assert result["chrome.exe"].count == 2
    assert result["chrome.exe"].cpu_percent == pytest.approx(15)
    assert result["chrome.exe"].memory == 150


def test_collect_builds_report_with_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    env = EnvironmentInfo(build=19045, edition="home", disk_type="ssd", system_drive="C:")
    runner = FakeRunner()
    runner.respond_json("Get-HotFix", 3)
    procs = [ProcessUsage("MsMpEng.exe", 30, 300 * 1024**2)]
    rep = diagnostics.collect(env, Registry(MemoryRegistryBackend()), runner, sampler=lambda: procs)
    assert rep.top_cpu[0].name == "MsMpEng.exe"
    assert rep.snapshot.cpu_percent == 30
    assert rep.updates.last_update_days == 3
    assert rep.win11  # Windows 10: lista de requisitos de Windows 11
    assert rep.findings


# --------------------------------------------------------------------------- 2. Windows Update


def test_read_update_status_detects_reboot_and_age() -> None:
    backend = MemoryRegistryBackend()
    backend.seed("HKLM", WU_REBOOT_KEYS[0], "x", RegValue("REG_DWORD", 1))
    runner = FakeRunner()
    runner.respond_json("Get-HotFix", 75)
    status = read_update_status(Registry(backend), runner)
    assert status.reboot_pending is True
    assert status.last_update_days == 75
    assert status.stale is True
    assert len(status.warnings()) == 2


def test_read_update_status_without_data_is_quiet() -> None:
    status = read_update_status(Registry(MemoryRegistryBackend()), FakeRunner())
    assert status == UpdateStatus()
    assert status.warnings() == []


# --------------------------------------------------------------------------- 8. Windows 10/11


def _windows_env(build: int) -> EnvironmentInfo:
    backend = MemoryRegistryBackend()
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    for name, value in (("CurrentBuildNumber", str(build)), ("EditionID", "Core")):
        backend.seed("HKLM", key, name, RegValue("REG_SZ", value))
    env = EnvironmentInfo()
    EnvironmentDetector(Registry(backend), FakeRunner())._windows(env)
    return env


def test_windows10_end_of_support_warning() -> None:
    assert any("dejó de recibir parches" in w for w in _windows_env(19045).warnings)
    assert not any("dejó de recibir parches" in w for w in _windows_env(26100).warnings)


def test_win11_requirements() -> None:
    # 3.4 GB → no; "4 GB" que Windows ve como 3.8 GiB → sí.
    low = {r.name: r for r in win11_requirements(report(snap=snapshot(ram_total=3.4 * GIB)))}
    assert low["Memoria RAM"].ok is False
    ok = {r.name: r for r in win11_requirements(report(snap=snapshot(ram_total=3.8 * GIB)))}
    assert ok["Memoria RAM"].ok is True
    # Con los módulos leídos no hay margen: 3.5 GB instalados no llegan a 4.
    modules = HardwareInfo(modules=[int(3.5 * GIB)])
    exact = {r.name: r for r in win11_requirements(report(hardware=modules))}
    assert exact["Memoria RAM"].ok is False
    four = HardwareInfo(modules=[4 * GIB])
    assert {r.name: r for r in win11_requirements(report(hardware=four))}["Memoria RAM"].ok

    legacy = HardwareInfo(tpm_version="1.2, 2, 3", firmware="Legacy")
    reqs = {r.name: r for r in win11_requirements(report(hardware=legacy))}
    assert reqs["TPM 2.0"].ok is False
    assert reqs["Arranque UEFI con arranque seguro"].ok is False
    assert reqs["Procesador compatible"].ok is None


def test_windows10_finding_reports_win11_verdict() -> None:
    env = EnvironmentInfo(build=19045, edition="home", disk_type="ssd")
    rep = report(env=env, snap=snapshot(ram_total=3 * GIB))
    eol = next(f for f in analyze(rep) if f.title == "Windows 10 sin soporte")
    assert "No cumple" in eol.detail


# --------------------------------------------------------------------------- 3. Windows.old


@pytest.fixture
def windows_old(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import tweaks.cleanup as cleanup

    folder = tmp_path / "Windows.old"
    (folder / "Windows" / "System32").mkdir(parents=True)
    (folder / "Windows" / "System32" / "big.dll").write_bytes(b"x" * (3 * 1024 * 1024))
    monkeypatch.setattr(cleanup, "windows_old_path", lambda: folder)
    return folder


def test_windows_old_detected_and_measured(make_engine: EngineFactory, windows_old: Path) -> None:
    engine = make_engine()
    tweak = engine.catalog.get("cleanup.windows_old")
    assert engine.evaluate(tweak).applicable
    result = engine.detect(tweak)
    assert result.state.value == "not_applied"
    assert "3.0 MB" in result.detail
    assert "aún puedes volver" in result.detail


def test_windows_old_not_applicable_when_absent(
    make_engine: EngineFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tweaks.cleanup as cleanup

    monkeypatch.setattr(cleanup, "windows_old_path", lambda: tmp_path / "nope")
    engine = make_engine()
    assert not engine.evaluate(engine.catalog.get("cleanup.windows_old")).applicable


def test_windows_old_is_optional_and_needs_confirmation(make_engine: EngineFactory) -> None:
    tweak = make_engine().catalog.get("cleanup.windows_old")
    assert tweak.is_action and not tweak.auto_profile and not tweak.reversible


def test_windows_old_runs_cleanmgr_profile(
    make_engine: EngineFactory,
    windows_old: Path,
    runner: FakeRunner,
    backend: MemoryRegistryBackend,
) -> None:
    engine = make_engine()
    session = engine.apply(["cleanup.windows_old"], confirmed={"cleanup.windows_old"})
    result = session.results["cleanup.windows_old"]
    assert any(
        c[0].lower().endswith("cleanmgr.exe") and c[1] == "/sagerun:42" for c in runner.calls
    )
    flag = backend.read("HKLM", CLEANMGR_PREVIOUS_INSTALLS_KEY, "StateFlags0042")
    assert flag == RegValue("REG_DWORD", 2)
    # El runner simulado no borra: la sesión avisa de lo que queda.
    assert any("Quedan" in d for d in result.details)


def test_windows_old_simulation_plans_without_running(
    make_engine: EngineFactory, windows_old: Path, runner: FakeRunner
) -> None:
    items = make_engine().plan(["cleanup.windows_old"])
    assert any("Windows.old" in step for step in items[0].lines)
    assert not any("cleanmgr" in " ".join(c).lower() for c in runner.calls)


# --------------------------------------------------------------------------- 4. recomendación


def test_recommendation_notes_low_ram_on_laptops(env: EnvironmentInfo) -> None:
    env.chassis = "laptop"
    level, why = recommend_profile(env, snapshot(ram_total=3.4 * GIB))
    assert level == 2
    assert "ampliar memoria" in why
    _level, why = recommend_profile(env, snapshot(ram_total=16 * GIB))
    assert "ampliar memoria" not in why


def test_no_recommendation_while_reboot_pending(env: EnvironmentInfo) -> None:
    env.reboot_pending = True
    level, why = recommend_profile(env, snapshot())
    assert level is None
    assert "reinicia" in why


# --------------------------------------------------------------------------- 6. procesos


def test_powershell_calls_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def fake_run(self: Any, args: list[str], timeout: int = 0, encoding: Any = None) -> Any:
        # Dentro de la llamada el único hueco está ocupado.
        seen.append(process._POWERSHELL_SLOTS.acquire(blocking=False))
        return process.CommandResult(tuple(args), 0, "", "")

    monkeypatch.setattr(process.SubprocessRunner, "run", fake_run)
    process.SubprocessRunner().powershell("Get-Date")
    assert seen == [False]
    assert process._POWERSHELL_SLOTS.acquire(blocking=False)  # liberado al terminar
    process._POWERSHELL_SLOTS.release()


@pytest.mark.parametrize("low", [True, False])
def test_child_process_priority(monkeypatch: pytest.MonkeyPatch, low: bool) -> None:
    captured: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process.sys, "platform", "win32")
    monkeypatch.setattr(process.subprocess, "run", fake_run)
    process.SubprocessRunner(low_priority=low).run(["x.exe"])
    flags = captured["creationflags"]
    assert flags & process.CREATE_NO_WINDOW
    assert bool(flags & process.BELOW_NORMAL_PRIORITY_CLASS) is low


# --------------------------------------------------------------------------- 5. versión nueva


class FakeResponse(io.BytesIO):
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def opener_for(payload: str) -> Callable[..., FakeResponse]:
    def opener(request: Any, timeout: float = 0) -> FakeResponse:
        assert request.full_url.startswith("https://api.github.com/")
        assert request.get_header("User-agent").startswith("SafeBoost/")
        return FakeResponse(payload.encode())

    return opener


RELEASE = '{"tag_name": "v0.5.0", "html_url": "https://github.com/x/y/releases/tag/v0.5.0"}'


def test_parse_version() -> None:
    assert parse_version("v0.4.0") == (0, 4, 0)
    assert parse_version("1.2") is None
    assert parse_version("v1.2.x") is None


def test_newer_release_is_reported() -> None:
    info = check_latest("0.4.0", opener=opener_for(RELEASE))
    assert info == ReleaseInfo("0.5.0", "https://github.com/x/y/releases/tag/v0.5.0")


def test_same_or_older_release_is_ignored() -> None:
    assert check_latest("0.5.0", opener=opener_for(RELEASE)) is None
    assert check_latest("1.0.0", opener=opener_for(RELEASE)) is None


def test_prerelease_and_bad_payloads_are_ignored() -> None:
    pre = RELEASE[:-1] + ', "prerelease": true}'
    assert check_latest("0.1.0", opener=opener_for(pre)) is None
    assert check_latest("0.1.0", opener=opener_for("no es json")) is None
    bad_url = '{"tag_name": "v9.0.0", "html_url": "javascript:alert(1)"}'
    assert check_latest("0.1.0", opener=opener_for(bad_url)) is None


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("u", 404, "Not Found", {}, None),  # repo privado
        urllib.error.URLError("sin red"),
        TimeoutError("lento"),
    ],
)
def test_network_errors_are_silent(error: Exception) -> None:
    def opener(_request: Any, timeout: float = 0) -> Any:
        raise error

    assert check_latest("0.1.0", opener=opener) is None


def test_non_https_url_is_refused() -> None:
    assert check_latest("0.1.0", opener=opener_for(RELEASE), url="http://x") is None


# --------------------------------------------------------------------------- 7. asistente


def test_welcome_wizard_has_three_steps_and_explains_simulation() -> None:
    from ui.dialogs import WELCOME_STEPS

    assert len(WELCOME_STEPS) == 3
    text = " ".join(" ".join(p) for _t, p in WELCOME_STEPS)
    assert "MODO SIMULACIÓN" in text
    assert "punto de restauración" in text
    assert "Revisar y aplicar" in text


def test_settings_defaults_for_new_options() -> None:
    from core.settings import Settings

    settings = Settings()
    assert settings.first_run is True
    assert settings.check_updates is True
