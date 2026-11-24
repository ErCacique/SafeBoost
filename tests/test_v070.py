"""v0.7.0: vigilancia. Programas nuevos al inicio, historial de salud y tendencia del arranque,
foto antes/después de instalar, mantenimiento mensual y privacidad (cámara, micro, ubicación)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.watch as watch
from core.constants import SERVICES_KEY
from core.engine import Engine, PreflightError
from core.privacy import CONSENT_STORE, filetime_to_datetime, read_privacy
from core.programs import UNINSTALL_KEYS, list_programs
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.watch import (
    EventLog,
    HealthHistory,
    HealthRecord,
    MaintenanceReport,
    MaintenanceStore,
    SnapshotStore,
    StartupItem,
    StartupWatch,
    boot_trend,
    diff_snapshots,
    schedule_maintenance,
    take_snapshot,
)
from tests.conftest import USER_SID, FakeRunner

EngineFactory = Callable[..., Engine]


# --------------------------------------------------------------------------- programas de inicio


def test_startup_watch_baseline_then_detects_new(tmp_path: Path) -> None:
    w = StartupWatch(tmp_path)
    assert w.check([StartupItem("run:a", "A")]) == []  # primera vez: solo referencia
    assert w.check([StartupItem("run:a", "A")]) == []
    new = w.check([StartupItem("run:a", "A"), StartupItem("run:b", "Spotify")])
    assert new == [StartupItem("run:b", "Spotify")]
    assert EventLog(tmp_path).all()[-1]["text"] == "Spotify"
    assert w.check([StartupItem("run:b", "Spotify")]) == []  # ya conocido


def test_program_watch_uses_its_own_file_and_event(tmp_path: Path) -> None:
    w = StartupWatch(tmp_path, name="programs_known.json", kind="program_installed")
    w.check([])
    w.check([StartupItem("k", "VLC")])
    assert EventLog(tmp_path).all()[-1]["kind"] == "program_installed"
    assert (tmp_path / "programs_known.json").exists()


# --------------------------------------------------------------------------- historial y tendencia


def record(day: int, boot_ms: int | None) -> HealthRecord:
    stamp = f"2026-11-{day:02d}"
    return HealthRecord(f"{stamp}T09:00:00", boot_ms, stamp, 4, 2, 100, 120, 8)


def test_history_one_record_per_boot(tmp_path: Path) -> None:
    history = HealthHistory(tmp_path)
    assert history.add(record(1, 40000)) is True
    assert history.add(record(1, 41000)) is False  # mismo arranque
    assert history.add(record(2, 39000)) is True
    assert [r.boot_ms for r in history.load()] == [40000, 39000]


def test_trend_finds_when_it_got_slower_and_why() -> None:
    records = [record(d, 42000) for d in range(1, 10)] + [record(d, 72000) for d in range(10, 13)]
    events = [
        {"when": "2026-11-09T20:00:00", "kind": "startup_added", "text": "Spotify"},
        {"when": "2026-11-02T20:00:00", "kind": "startup_added", "text": "Antiguo"},
    ]
    trend = boot_trend(records, events)
    assert trend is not None
    assert trend.since == "2026-11-10"
    assert trend.before_ms == 42000 and trend.after_ms == 72000
    assert trend.causes == ["Spotify"]


def test_no_trend_when_stable_or_too_few_records() -> None:
    stable = [record(d, 40000 + (d % 3) * 2000) for d in range(1, 15)]
    assert boot_trend(stable, []) is None
    assert boot_trend([record(1, 1000), record(2, 90000)], []) is None


# --------------------------------------------------------------------------- foto antes/después


def test_snapshot_and_diff(backend: MemoryRegistryBackend) -> None:
    registry = Registry(backend, USER_SID)
    runner = FakeRunner()
    runner.respond_json("Get-ScheduledTask", ["\\Microsoft\\A"])
    before = take_snapshot(registry, runner, [StartupItem("run:a", "A")])
    # El registro simulado devuelve las subclaves en minúsculas; el de Windows no.
    services = {k.lower(): v for k, v in before["services"].items()}
    assert services["diagtrack"] == "auto"

    backend.seed("HKLM", f"{SERVICES_KEY}\\NuevoSvc", "Type", RegValue("REG_DWORD", 16))
    backend.seed("HKLM", f"{SERVICES_KEY}\\NuevoSvc", "Start", RegValue("REG_DWORD", 2))
    backend.write("HKLM", f"{SERVICES_KEY}\\Fax", "Start", RegValue("REG_DWORD", 2))
    path = f"{UNINSTALL_KEYS[0][1]}\\Spotify"
    backend.seed("HKLM", path, "DisplayName", RegValue("REG_SZ", "Spotify"))
    runner.json_responses.clear()
    runner.respond_json("Get-ScheduledTask", ["\\Microsoft\\A", "\\SpotifyUpdate"])
    after = take_snapshot(
        registry, runner, [StartupItem("run:a", "A"), StartupItem("run:s", "Spotify")]
    )
    diff = diff_snapshots(before, after)
    assert diff.programs_added == ["Spotify"]
    assert diff.startup_added == ["Spotify"]
    assert [s.lower() for s in diff.services_added] == ["nuevosvc"]
    assert [s.lower() for s in diff.services_changed] == ["fax: manual → auto"]
    assert diff.tasks_added == ["\\SpotifyUpdate"]
    assert not diff.empty
    assert diff_snapshots(after, after).empty


def test_snapshot_store_roundtrip(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path)
    assert store.load() is None
    store.save({"taken": "x", "services": {}})
    assert store.load() == {"taken": "x", "services": {}}


# --------------------------------------------------------------------------- mantenimiento


def test_maintenance_store_and_seen_flag(tmp_path: Path) -> None:
    store = MaintenanceStore(tmp_path)
    store.save(MaintenanceReport("2026-11-21T12:00:00", freed_bytes=10, drift=["X"]))
    assert store.load().freed_bytes == 10
    store.mark_seen()
    assert store.load().seen is True


def test_schedule_maintenance_task() -> None:
    runner = FakeRunner()
    assert (
        schedule_maintenance(runner, ["C:\\Program Files\\SafeBoost\\SafeBoost.exe"], "PC\\Ana")
        is True
    )
    script = runner.scripts[-1]
    for part in (
        "-Weekly -WeeksInterval 4",
        "-LogonType Interactive",
        "-RunLevel Highest",
        "'--maintenance'",
        "-StartWhenAvailable",
        "'PC\\Ana'",
    ):
        assert part in script


def test_cleanup_without_restore_point_only_for_actions(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    engine = make_engine()
    with pytest.raises(PreflightError, match="solo se pueden ejecutar limpiezas"):
        engine.apply(["power.hibernate_off"], restore_point=False)  # riesgo medio
    session = engine.apply(
        ["cleanup.thumbnails"], confirmed={"cleanup.thumbnails"}, restore_point=False
    )
    assert "Omitido" in session.restore_point
    assert not any("Checkpoint-Computer" in s for s in runner.scripts)


def test_maintenance_command_writes_report(
    make_engine: EngineFactory, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import core.monitor
    import main

    engine = make_engine()
    monkeypatch.setattr(watch, "WATCH_DIR", tmp_path)
    monkeypatch.setattr(
        core.monitor, "refresh", lambda _app: SimpleNamespace(new_startup=[StartupItem("k", "X")])
    )
    monkeypatch.setattr(main, "maintenance", main.maintenance)  # se importa de main, no del módulo
    stores: list[MaintenanceStore] = []

    class Store(MaintenanceStore):
        def __init__(self) -> None:
            super().__init__(tmp_path)
            stores.append(self)

    monkeypatch.setattr(watch, "MaintenanceStore", Store)
    monkeypatch.setattr(watch, "EventLog", lambda: EventLog(tmp_path))
    code = main.maintenance(build=lambda **_kw: SimpleNamespace(engine=engine))
    report = MaintenanceStore(tmp_path).load()
    assert code == 0 and report is not None
    assert report.new_startup == ["X"]
    assert report.error == ""


# --------------------------------------------------------------------------- privacidad


def test_filetime_conversion() -> None:
    assert filetime_to_datetime(0) is None
    assert filetime_to_datetime("x") is None
    assert filetime_to_datetime(134396730000000000) == datetime(2026, 11, 20, 18, 30, tzinfo=UTC)


def test_read_privacy(backend: MemoryRegistryBackend) -> None:
    base = f"{USER_SID}\\{CONSENT_STORE}"
    for app, start, stop in (
        ("NonPackaged\\C:#Apps#Zoom.exe", 134396730000000000, 134396736000000000),
        ("Microsoft.WindowsCamera_8wekyb3d8bbwe", 134396740000000000, 0),
        ("Nunca.Usada_x", 0, 0),
    ):
        key = f"{base}\\webcam\\{app}"
        backend.seed("HKU", key, "LastUsedTimeStart", RegValue("REG_QWORD", start))
        backend.seed("HKU", key, "LastUsedTimeStop", RegValue("REG_QWORD", stop))
    backend.seed("HKU", f"{base}\\webcam", "Value", RegValue("REG_SZ", "Deny"))
    webcam = read_privacy(Registry(backend, USER_SID))[0]
    assert webcam.label == "Cámara" and webcam.globally_allowed is False
    assert [a.app.lower() for a in webcam.apps] == ["windowscamera", "zoom.exe"]
    assert webcam.apps[0].in_use is True and webcam.apps[1].in_use is False
    assert webcam.settings_uri == "ms-settings:privacy-webcam"


# --------------------------------------------------------------------------- programas instalados


def test_list_programs(backend: MemoryRegistryBackend) -> None:
    hklm, wow = UNINSTALL_KEYS[0][1], UNINSTALL_KEYS[1][1]
    for root, sub, values in (
        (hklm, "VLC", {"DisplayName": "VLC", "EstimatedSize": 40000, "InstallDate": "20250102"}),
        (wow, "VLC32", {"DisplayName": "VLC"}),  # duplicado en WOW6432Node
        (hklm, "KB1", {"DisplayName": "Parche", "ParentKeyName": "Office"}),
        (hklm, "Sys", {"DisplayName": "Runtime", "SystemComponent": 1}),
        (hklm, "SinNombre", {"Publisher": "X"}),
    ):
        for name, value in values.items():
            kind = "REG_DWORD" if isinstance(value, int) else "REG_SZ"
            backend.seed("HKLM", f"{root}\\{sub}", name, RegValue(kind, value))
    programs = list_programs(Registry(backend, USER_SID))
    assert [p.name for p in programs] == ["VLC"]
    assert programs[0].size_kb == 40000
    assert programs[0].installed_on == date(2025, 1, 2)
    assert len(list_programs(Registry(backend, USER_SID), include_system=True)) == 3


def test_evolution_chart_points() -> None:
    from ui.pages.evolution_page import chart_points, describe_diff

    points = chart_points([record(1, 30000), record(2, None), record(3, 60000)], 400, 200)
    assert len(points) == 2
    assert points[0][0] < points[1][0] and points[0][1] > points[1][1]  # más alto = más lento
    assert describe_diff(diff_snapshots({}, {})) == "No ha cambiado nada desde la foto."
