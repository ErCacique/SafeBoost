"""Motor: detección, simulación, aplicación, aislamiento de errores, protección y reversión."""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest

from core.catalog import Catalog
from core.constants import SERVICES_KEY
from core.context import DetectState
from core.engine import Engine, PreflightError
from core.registry import MemoryRegistryBackend, RegValue
from core.settings import Settings
from tests.conftest import USER_SID, FakeRunner, make_tweak

EngineFactory = Callable[..., Engine]

SIUF = r"Software\Microsoft\Siuf\Rules"
USER_SIUF = rf"{USER_SID}\{SIUF}"


def reg_op(hive: str, path: str, name: str, value: int) -> dict:
    return {
        "op": "registry_set",
        "hive": hive,
        "path": path,
        "name": name,
        "kind": "REG_DWORD",
        "value": value,
    }


# --------------------------------------------------------------------------- detección


def test_detect_not_applied_then_applied(make_engine: EngineFactory) -> None:
    engine = make_engine()
    tweak = engine.catalog.get("privacy.feedback_frequency")
    assert engine.detect(tweak).state == DetectState.NOT_APPLIED
    engine.apply([tweak.id])
    assert engine.detect(tweak).state == DetectState.APPLIED


def test_detect_partial(make_engine: EngineFactory, backend: MemoryRegistryBackend) -> None:
    engine = make_engine()
    tweak = engine.catalog.get("privacy.suggestions_lockscreen")
    first = tweak.apply[0]
    backend.write("HKU", rf"{USER_SID}\{first['path']}", first["name"], RegValue("REG_DWORD", 0))
    result = engine.detect(tweak)
    assert result.state == DetectState.PARTIAL
    assert "1/2" in result.detail


def test_detect_not_applicable_reports_reason(make_engine: EngineFactory) -> None:
    engine = make_engine(disk_type="hdd")
    result = engine.detect(engine.catalog.get("services.sysmain"))
    assert result.state == DetectState.NOT_APPLICABLE
    assert "SSD" in result.detail


def test_detect_appx_never_installed_is_applied(make_engine: EngineFactory) -> None:
    engine = make_engine()
    result = engine.detect(engine.catalog.get("bloatware.solitaire"))
    assert result.state == DetectState.APPLIED
    assert result.detail == "No instalado"


def test_detect_appx_installed_is_not_applied(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    runner.appx_installed = ["king.com.CandyCrushSaga"]
    engine = make_engine()
    assert engine.detect(engine.catalog.get("bloatware.candy_crush")).state == (
        DetectState.NOT_APPLIED
    )


# --------------------------------------------------------------------------- simulación


def test_plan_does_not_modify_anything(
    make_engine: EngineFactory, backend: MemoryRegistryBackend, runner: FakeRunner
) -> None:
    engine = make_engine()
    ids = ["privacy.feedback_frequency", "privacy.diagtrack", "privacy.task_ceip"]
    items = engine.plan(ids)
    assert all(item.lines for item in items)
    assert "NumberOfSIUFInPeriod: (no existe) → 0" in items[0].lines[0]
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") is None
    assert not [c for c in runner.calls if "config" in c]
    assert not [s for s in runner.scripts if s.startswith("Disable-ScheduledTask")]
    assert not engine.store.list()


def test_plan_marks_already_applied(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    backend.write("HKU", USER_SIUF, "NumberOfSIUFInPeriod", RegValue("REG_DWORD", 0))
    item = make_engine().plan(["privacy.feedback_frequency"])[0]
    assert item.already_applied


# --------------------------------------------------------------------------- aplicación


def test_apply_writes_user_hive_and_records_snapshot(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency"])
    assert session.results["privacy.feedback_frequency"].status == "applied"
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") == RegValue("REG_DWORD", 0)
    change = session.changes[0]
    assert change.before is None
    assert change.target["key_existed"] is False
    assert engine.store.load(session.id).changes[0].after == {"kind": "REG_DWORD", "data": 0}


def test_apply_exports_reg_backups(make_engine: EngineFactory, runner: FakeRunner) -> None:
    session = make_engine().apply(["privacy.advertising_id"])
    exports = [c for c in runner.calls if len(c) > 1 and c[1] == "export"]
    assert len(exports) == 2
    assert len(session.backups) == 2


def test_apply_service_uses_sc_and_stops(make_engine: EngineFactory, runner: FakeRunner) -> None:
    session = make_engine().apply(["privacy.diagtrack"])
    assert ["sc.exe", "config", "DiagTrack", "start=", "disabled"] in [
        [c[0].rsplit("\\", 1)[-1], *c[1:]] for c in runner.calls
    ]
    assert any(c[-2:] == ["stop", "DiagTrack"] for c in runner.calls)
    assert session.changes[0].before == "automatic"


def test_already_applied_is_skipped(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    backend.write("HKU", USER_SIUF, "NumberOfSIUFInPeriod", RegValue("REG_DWORD", 0))
    session = make_engine().apply(["privacy.feedback_frequency"])
    result = session.results["privacy.feedback_frequency"]
    assert result.status == "skipped"
    assert result.message == "Ya estaba aplicado"
    assert not session.changes


def test_failure_in_one_tweak_does_not_abort_others(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    runner.fail_on.append("DiagTrack")
    session = make_engine().apply(["privacy.diagtrack", "privacy.feedback_frequency"])
    assert session.results["privacy.diagtrack"].status == "failed"
    assert "Acceso denegado" in session.results["privacy.diagtrack"].message
    assert session.results["privacy.feedback_frequency"].status == "applied"


def test_missing_service_is_skipped_not_failed(make_engine: EngineFactory) -> None:
    session = make_engine().apply(["services.retaildemo"])
    result = session.results["services.retaildemo"]
    assert result.status == "skipped"
    assert "no existe" in result.message


def test_not_applicable_is_skipped(make_engine: EngineFactory) -> None:
    session = make_engine(disk_type="hdd").apply(["services.sysmain"])
    assert session.results["services.sysmain"].status == "skipped"
    assert "No aplicable" in session.results["services.sysmain"].message


def test_policy_skipped_on_managed_device(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine(mdm_enrolled=True)
    session = engine.apply(["privacy.advertising_id"])
    result = session.results["privacy.advertising_id"]
    assert result.status == "applied"
    assert any("Directiva" in d for d in result.details)
    policy = r"SOFTWARE\Policies\Microsoft\Windows\AdvertisingInfo"
    assert backend.read("HKLM", policy, "DisabledByGroupPolicy") is None


def test_actions_require_explicit_confirmation(make_engine: EngineFactory) -> None:
    session = make_engine().apply(["cleanup.temp_windows"])
    assert session.results["cleanup.temp_windows"].message == "Falta confirmación explícita"


def test_high_risk_requires_confirmation(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    tid = "security.cpu_mitigations_off"
    session = engine.apply([tid])
    assert session.results[tid].status == "skipped"
    session = engine.apply([tid], confirmed={tid})
    assert session.results[tid].status == "applied"
    key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management"
    assert backend.read("HKLM", key, "FeatureSettingsOverride") == RegValue("REG_DWORD", 3)


# --------------------------------------------------------------------------- comprobaciones previas


def test_apply_requires_admin(make_engine: EngineFactory) -> None:
    with pytest.raises(PreflightError, match="administrador"):
        make_engine(is_admin=False).apply(["privacy.feedback_frequency"])


def test_apply_blocked_without_restore_point(
    make_engine: EngineFactory, runner: FakeRunner, backend: MemoryRegistryBackend
) -> None:
    runner.create_restore_points = False
    with pytest.raises(PreflightError, match="restauración"):
        make_engine().apply(["privacy.feedback_frequency"])
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") is None


def test_restore_point_override(
    make_engine: EngineFactory, runner: FakeRunner, settings: Settings
) -> None:
    runner.create_restore_points = False
    settings.allow_without_restore_point = True
    session = make_engine().apply(["privacy.feedback_frequency"])
    assert session.results["privacy.feedback_frequency"].status == "applied"


def test_restore_frequency_value_is_restored(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore"
    make_engine().apply(["privacy.feedback_frequency"])
    assert backend.read("HKLM", key, "SystemRestorePointCreationFrequency") is None


# --------------------------------------------------------------------------- protección


def test_protected_service_is_never_touched(make_engine: EngineFactory, runner: FakeRunner) -> None:
    evil = make_tweak(
        id="test.evil",
        apply=[{"op": "service_start", "name": "WinDefend", "start": "disabled", "stop": True}],
    )
    session = make_engine(Catalog([evil])).apply(["test.evil"])
    assert session.results["test.evil"].status == "failed"
    assert "protegido" in session.results["test.evil"].message
    assert not [c for c in runner.calls if "WinDefend" in c]


def test_protected_registry_path_is_blocked(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    path = r"SOFTWARE\Policies\Microsoft\Windows Defender"
    evil = make_tweak(id="test.defender", apply=[reg_op("HKLM", path, "DisableAntiSpyware", 1)])
    session = make_engine(Catalog([evil])).apply(["test.defender"])
    assert session.results["test.defender"].status == "failed"
    assert backend.read("HKLM", path, "DisableAntiSpyware") is None


def test_driver_service_is_blocked(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    backend.write("HKLM", f"{SERVICES_KEY}\\SomeDrv", "Start", RegValue("REG_DWORD", 3))
    backend.write("HKLM", f"{SERVICES_KEY}\\SomeDrv", "Type", RegValue("REG_DWORD", 1))
    tweak = make_tweak(
        id="test.drv",
        apply=[{"op": "service_start", "name": "SomeDrv", "start": "disabled", "stop": False}],
    )
    session = make_engine(Catalog([tweak])).apply(["test.drv"])
    assert "driver" in session.results["test.drv"].message


def test_spooler_protected_when_printers(make_engine: EngineFactory) -> None:
    tweak = make_tweak(
        id="test.spool",
        apply=[{"op": "service_start", "name": "Spooler", "start": "manual", "stop": False}],
    )
    session = make_engine(Catalog([tweak]), printers=["HP"]).apply(["test.spool"])
    assert session.results["test.spool"].status == "failed"


def test_protected_appx_is_blocked(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.appx_installed = ["Microsoft.WindowsStore"]
    tweak = make_tweak(
        id="test.store",
        apply=[{"op": "appx_remove", "package": "Microsoft.WindowsStore", "provisioned": True}],
    )
    session = make_engine(Catalog([tweak])).apply(["test.store"])
    assert session.results["test.store"].status == "failed"
    assert not [s for s in runner.scripts if "Remove-Appx" in s]


# --------------------------------------------------------------------------- reversión


def test_revert_restores_previous_values_and_removes_created_keys(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    lock = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"
    backend.write(
        "HKU", rf"{USER_SID}\{lock}", "RotatingLockScreenOverlayEnabled", RegValue("REG_DWORD", 1)
    )
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency", "privacy.suggestions_lockscreen"])
    revert = engine.revert(session.id)
    assert {r.status for r in revert.results.values()} == {"reverted"}
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") is None
    assert not backend.key_exists("HKU", USER_SIUF)
    assert backend.read("HKU", rf"{USER_SID}\{lock}", "RotatingLockScreenOverlayEnabled") == (
        RegValue("REG_DWORD", 1)
    )
    assert backend.read("HKU", rf"{USER_SID}\{lock}", "SubscribedContent-338387Enabled") is None
    assert engine.store.load(session.id).reverted_by == revert.id


def test_revert_order_is_reverse_of_apply(make_engine: EngineFactory) -> None:
    engine = make_engine()
    ids = ["privacy.feedback_frequency", "privacy.tailored_experiences"]
    session = engine.apply(ids)
    revert = engine.revert(session.id)
    assert revert.selected == list(reversed(ids))


def test_revert_service_restores_start_and_starts(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.diagtrack"])
    runner.calls.clear()
    engine.revert(session.id)
    tails = [c[1:] for c in runner.calls]
    assert ["config", "DiagTrack", "start=", "auto"] in tails
    assert ["start", "DiagTrack"] in tails


def test_revert_tasks(make_engine: EngineFactory, runner: FakeRunner) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.task_ceip"])
    assert set(runner.task_states.values()) == {"Disabled"}
    engine.revert(session.id)
    assert set(runner.task_states.values()) == {"Ready"}


def test_revert_dry_run_changes_nothing(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency"])
    preview = engine.revert(session.id, dry_run=True)
    assert any("Restaurar" in d for d in preview.results["privacy.feedback_frequency"].details)
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") == RegValue("REG_DWORD", 0)
    assert engine.store.load(session.id).reverted_by is None


def test_revert_irreversible_action_is_reported(
    make_engine: EngineFactory, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = tmp_path / "Temp"
    temp.mkdir()
    old = temp / "old.tmp"
    old.write_bytes(b"x" * 10)
    os.utime(old, (0, 0))
    monkeypatch.setattr("tweaks.cleanup.SYSTEM_ROOT", tmp_path)
    engine = make_engine()
    session = engine.apply(["cleanup.temp_windows"], confirmed={"cleanup.temp_windows"})
    assert session.results["cleanup.temp_windows"].status == "applied"
    assert not old.exists()
    revert = engine.revert(session.id)
    assert revert.results["cleanup.temp_windows"].status == "irreversible"


def test_revert_unknown_tweak_uses_snapshot(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    tweak = make_tweak(id="test.gone", apply=[reg_op("HKLM", r"SOFTWARE\SafeBoostTest", "X", 1)])
    engine = make_engine(Catalog([tweak]))
    session = engine.apply(["test.gone"])
    # Catálogo nuevo sin ese tweak: la reversión cae al snapshot registrado.
    other = make_tweak(id="test.other")
    engine.catalog = Catalog([other])
    revert = engine.revert(session.id)
    assert revert.results["test.gone"].status == "reverted"
    assert backend.read("HKLM", r"SOFTWARE\SafeBoostTest", "X") is None


def test_appx_remove_and_reinstall(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.appx_installed = ["Microsoft.BingNews"]
    engine = make_engine()
    session = engine.apply(["bloatware.bing_news"])
    assert session.results["bloatware.bing_news"].status == "applied"
    assert any(
        "Remove-AppxProvisionedPackage" not in s and "Remove-AppxPackage" in s
        for s in runner.scripts
    )
    engine.appx.__dict__["winget_path"] = "winget.exe"
    runner.calls.clear()
    original_run = runner.run

    def run_and_reinstall(args, timeout=60, encoding=None):  # winget simulado: reinstala
        if args[0] == "winget.exe":
            runner.appx_installed.append("Microsoft.BingNews")
        return original_run(args, timeout, encoding)

    runner.run = run_and_reinstall
    revert = engine.revert(session.id)
    assert revert.results["bloatware.bing_news"].status == "reverted"
    assert revert.results["bloatware.bing_news"].verified is True
    winget = runner.calls[-1]
    assert winget[:4] == ["winget.exe", "install", "--id", "9WZDNCRFHVFW"]
    assert "--source" in winget and "msstore" in winget


# --------------------------------------------------------------------------- correcciones 0.1.1


def test_warm_checks_caches_and_isolates_failures(
    make_engine: EngineFactory, runner: FakeRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_hags(_ctx) -> bool:
        calls.append("hags")
        return True

    monkeypatch.setattr("tweaks.gaming.hags_supported", fake_hags)
    import core.context as context

    context._cache.clear()
    engine = make_engine()
    engine.warm_checks()
    assert calls == ["hags"]
    # La UI evalúa después sin volver a ejecutar dxdiag.
    assert engine.evaluate(engine.catalog.get("gaming.hags")).applicable
    assert calls == ["hags"]

    def broken(_ctx) -> bool:
        raise RuntimeError("dxdiag roto")

    monkeypatch.setattr("tweaks.gaming.hags_supported", broken)
    context._cache.clear()
    engine = make_engine()
    engine.warm_checks()
    assert not engine.evaluate(engine.catalog.get("gaming.hags")).applicable
    context._cache.clear()


def test_appx_fallback_note_reaches_session(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.appx_installed = ["Microsoft.BingNews"]
    runner.fail_on.append("Remove-AppxPackage -AllUsers")
    session = make_engine().apply(["bloatware.bing_news"])
    result = session.results["bloatware.bing_news"]
    assert result.status == "applied"
    assert any("solo para el usuario actual" in d for d in result.details)


# --------------------------------------------------------------------------- 0.2.0


def test_revert_is_verified(make_engine: EngineFactory) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.feedback_frequency", "privacy.diagtrack", "privacy.task_ceip"])
    assert session.results["privacy.diagtrack"].detect_before == "not_applied"
    revert = engine.revert(session.id)
    for result in revert.results.values():
        assert result.status == "reverted", result
        assert result.verified is True
        assert result.message == "Revertido y verificado"


def test_revert_verification_reports_differences(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    engine = make_engine()
    session = engine.apply(["privacy.diagtrack"])
    # sc.exe "funciona" pero el servicio no cambia (p. ej. otra herramienta lo revierte).
    runner.backend = None
    revert = engine.revert(session.id)
    result = revert.results["privacy.diagtrack"]
    assert result.status == "partial"
    assert result.verified is False
    assert any("Servicio DiagTrack: disabled (esperado automatic)" in d for d in result.details)


def test_v1_session_from_0_1_x_still_reverts(
    make_engine: EngineFactory, backend: MemoryRegistryBackend, runner: FakeRunner
) -> None:
    import json
    from pathlib import Path

    from core.session import SESSION_SCHEMA_VERSION, Session

    raw = json.loads((Path(__file__).parent / "fixtures" / "session_v1.json").read_text("utf-8"))
    assert "schema_version" not in raw
    engine = make_engine()
    # Estado del sistema tal como lo dejó aquella sesión.
    backend.write("HKU", USER_SIUF, "NumberOfSIUFInPeriod", RegValue("REG_DWORD", 0))
    session = Session.from_dict(raw)
    assert session.schema_version == SESSION_SCHEMA_VERSION
    assert session.app_version == "0.1.x"
    engine.store.save(session)
    revert = engine.revert(session.id)
    assert revert.results["privacy.feedback_frequency"].status == "reverted"
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") is None


def test_newer_session_format_is_rejected() -> None:
    from core.session import SESSION_SCHEMA_VERSION, Session, SessionVersionError

    with pytest.raises(SessionVersionError, match="Actualiza SafeBoost"):
        Session.from_dict(
            {
                "id": "x",
                "kind": "apply",
                "created": "",
                "schema_version": SESSION_SCHEMA_VERSION + 1,
            }
        )


def test_apply_blocked_on_unsupported_windows(
    make_engine: EngineFactory, runner: FakeRunner, backend: MemoryRegistryBackend
) -> None:
    # Windows 10 1909: solo simular. Ni punto de restauración ni cambios en el registro.
    engine = make_engine(build=18363)
    with pytest.raises(PreflightError, match="no está soportado"):
        engine.apply(["privacy.feedback_frequency"])
    assert not any("Checkpoint-Computer" in " ".join(call) for call in runner.calls)
    assert backend.read("HKU", USER_SIUF, "NumberOfSIUFInPeriod") is None
    assert engine.store.list() == []


def test_apply_blocked_on_unknown_edition(make_engine: EngineFactory) -> None:
    with pytest.raises(PreflightError, match="no está soportado"):
        make_engine(edition="unknown", edition_id="ServerDatacenter").apply(
            ["privacy.feedback_frequency"]
        )


def test_simulation_still_works_on_unsupported_windows(make_engine: EngineFactory) -> None:
    items = make_engine(build=18363).plan(["privacy.feedback_frequency"])
    assert len(items) == 1


def test_unsupported_windows_override_for_test_vms(
    make_engine: EngineFactory, settings: Settings
) -> None:
    settings.allow_unsupported_os = True
    engine = make_engine(edition="unknown", edition_id="ServerDatacenter")
    session = engine.apply(["privacy.feedback_frequency"])
    assert "privacy.feedback_frequency" in session.results
