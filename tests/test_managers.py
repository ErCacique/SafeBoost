"""Servicios, tareas programadas y AppX con runner simulado."""

from __future__ import annotations

import pytest

from core.appx import AppxError, AppxManager, is_protected_package
from core.constants import SERVICES_KEY
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.services import ServiceError, ServiceManager
from core.tasks import TaskManager, split_task_path
from tests.conftest import FakeRunner


def test_service_state_reads_registry(backend: MemoryRegistryBackend, runner: FakeRunner) -> None:
    key = f"{SERVICES_KEY}\\MapsBroker"
    backend.write("HKLM", key, "DelayedAutostart", RegValue("REG_DWORD", 1))
    services = ServiceManager(Registry(backend), runner)
    assert services.state("MapsBroker").start == "automatic_delayed"
    assert services.state("Fax").start == "manual"
    missing = services.state("NoExiste")
    assert not missing.exists
    assert missing.start is None


def test_service_set_start_arguments(backend: MemoryRegistryBackend, runner: FakeRunner) -> None:
    ServiceManager(Registry(backend), runner).set_start("Fax", "manual")
    assert runner.calls[-1][1:] == ["config", "Fax", "start=", "demand"]


def test_service_set_start_rejects_invalid(
    backend: MemoryRegistryBackend, runner: FakeRunner
) -> None:
    with pytest.raises(ServiceError):
        ServiceManager(Registry(backend), runner).set_start("Fax", "boot")


def test_service_set_start_failure(backend: MemoryRegistryBackend, runner: FakeRunner) -> None:
    runner.fail_on.append("Fax")
    with pytest.raises(ServiceError, match="Acceso denegado"):
        ServiceManager(Registry(backend), runner).set_start("Fax", "manual")


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"\Microsoft\Windows\Autochk\Proxy", ("\\Microsoft\\Windows\\Autochk\\", "Proxy")),
        ("Tarea", ("\\", "Tarea")),
    ],
)
def test_split_task_path(path: str, expected: tuple[str, str]) -> None:
    assert split_task_path(path) == expected


def test_task_query_and_toggle(runner: FakeRunner) -> None:
    tasks = TaskManager(runner)
    path = r"\Microsoft\Windows\Autochk\Proxy"
    assert tasks.query(path).enabled
    tasks.set_enabled(path, False)
    info = tasks.query(path)
    assert info.status == "Disabled"
    assert not info.enabled


def test_task_missing(runner: FakeRunner) -> None:
    runner.respond_json("Get-ScheduledTask -TaskPath", {"state": "Missing"})
    assert not TaskManager(runner).query(r"\X\Y").exists


@pytest.mark.parametrize(
    ("name", "protected"),
    [
        ("Microsoft.WindowsStore", True),
        ("Microsoft.VCLibs.140.00", True),
        ("MSTeams", True),
        ("Microsoft.XboxIdentityProvider", True),
        ("Microsoft.BingNews", False),
        ("MicrosoftTeams", False),
    ],
)
def test_protected_packages(name: str, protected: bool) -> None:
    assert is_protected_package(name) is protected


def test_appx_remove_refuses_protected(runner: FakeRunner) -> None:
    with pytest.raises(AppxError):
        AppxManager(runner).remove("Microsoft.DesktopAppInstaller", provisioned=True)


def test_appx_remove_includes_provisioned(runner: FakeRunner) -> None:
    runner.respond_json(
        "Get-AppxPackage",
        {
            "installed": {"Name": "Clipchamp.Clipchamp", "PackageFullName": "Clipchamp_1_x64"},
            "provisioned": {"DisplayName": "Clipchamp.Clipchamp", "PackageName": "Clip_prov"},
        },
    )
    removed = AppxManager(runner).remove("Clipchamp.Clipchamp", provisioned=True)
    assert removed == ["Clipchamp_1_x64", "Clip_prov"]
    assert any("Remove-AppxProvisionedPackage" in s for s in runner.scripts)


def test_appx_reinstall_without_winget(runner: FakeRunner) -> None:
    manager = AppxManager(runner)
    manager.__dict__["winget_path"] = None
    with pytest.raises(AppxError, match="winget"):
        manager.reinstall("Microsoft.BingNews", "9WZDNCRFHVFW", "Microsoft News")


def test_appx_reinstall_by_name_when_no_store_id(runner: FakeRunner) -> None:
    manager = AppxManager(runner)
    manager.__dict__["winget_path"] = "winget.exe"
    manager.reinstall("Microsoft.Getstarted", None, "Microsoft Tips")
    assert runner.calls[-1][2:5] == ["--name", "Microsoft Tips", "--exact"]


# --------------------------------------------------------------------------- correcciones 0.1.1


def test_appx_remove_falls_back_to_interactive_user(runner: FakeRunner) -> None:
    runner.respond_json(
        "Get-AppxPackage",
        {
            "installed": {"Name": "Microsoft.BingNews", "PackageFullName": "BingNews_1_x64"},
            "provisioned": [],
        },
    )
    runner.fail_on.append("Remove-AppxPackage -AllUsers")
    manager = AppxManager(runner, user_sid="S-1-5-21-9")
    assert manager.remove("Microsoft.BingNews", provisioned=False) == ["BingNews_1_x64"]
    assert runner.scripts[-1] == "Remove-AppxPackage -Package 'BingNews_1_x64' -User 'S-1-5-21-9'"
    notes = manager.pop_notes()
    assert len(notes) == 1
    assert "solo para el usuario actual" in notes[0]
    assert manager.pop_notes() == []


def test_appx_remove_reports_both_errors(runner: FakeRunner) -> None:
    runner.respond_json(
        "Get-AppxPackage",
        {
            "installed": {"Name": "Microsoft.BingNews", "PackageFullName": "BingNews_1_x64"},
            "provisioned": [],
        },
    )
    runner.fail_on.append("Remove-AppxPackage")
    with pytest.raises(AppxError, match="reintento por usuario"):
        AppxManager(runner, user_sid="S-1-5-21-9").remove("Microsoft.BingNews", False)


def test_reinstall_runs_in_user_session(runner: FakeRunner) -> None:
    runner.respond_json("Register-ScheduledTask", {"state": "Ready", "result": 0})
    manager = AppxManager(runner, run_as="EQUIPO\\ana")
    manager.reinstall("Microsoft.BingNews", "9WZDNCRFHVFW", "Microsoft News")
    script = runner.scripts[-1]
    assert "-UserId 'EQUIPO\\ana' -LogonType Interactive -RunLevel Limited" in script
    assert "winget install --id 9WZDNCRFHVFW --source msstore" in script
    assert "Unregister-ScheduledTask" in script
    assert not runner.calls  # no se ejecuta winget desde la cuenta elevada


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"state": "Ready", "result": 2316632107}, "código"),
        ({"state": "Running", "result": 0}, "a tiempo"),
    ],
)
def test_reinstall_in_user_session_failures(runner: FakeRunner, data: dict, match: str) -> None:
    runner.respond_json("Register-ScheduledTask", data)
    with pytest.raises(AppxError, match=match):
        AppxManager(runner, run_as="EQUIPO\\ana").reinstall("X", None, "Microsoft Tips")


def test_run_as_only_when_accounts_differ() -> None:
    from core.app import _run_as
    from core.environment import EnvironmentInfo

    same = EnvironmentInfo(interactive_user="PC\\ana", elevated_user="pc\\ANA")
    other = EnvironmentInfo(interactive_user="PC\\ana", elevated_user="PC\\admin")
    assert _run_as(same) is None
    assert _run_as(other) == "PC\\ana"
    assert _run_as(EnvironmentInfo()) is None


def test_fixed_drives_detection(monkeypatch: pytest.MonkeyPatch, backend, runner) -> None:
    from collections import namedtuple

    from core.environment import EnvironmentDetector, EnvironmentInfo

    Part = namedtuple("Part", "mountpoint opts")
    parts = [
        Part("C:\\", "rw,fixed"),
        Part("E:\\", "rw,removable"),
        Part("D:\\", "rw,fixed"),
        Part("/", "rw"),
    ]
    monkeypatch.setattr("core.environment.psutil.disk_partitions", lambda all=False: parts)
    env = EnvironmentInfo()
    EnvironmentDetector(Registry(backend), runner)._drives(env)
    assert env.fixed_drives == ["C:", "D:"]
