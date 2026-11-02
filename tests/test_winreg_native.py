"""Pruebas con el registro real de Windows (solo se ejecutan en windows-latest).

Usan exclusivamente HKCU\\Software\\WinTuneTest y lo eliminan al terminar.
"""

from __future__ import annotations

import contextlib
import sys
import uuid

import pytest

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(sys.platform != "win32", reason="requiere winreg nativo"),
]

BASE = r"Software\WinTuneTest"


@pytest.fixture
def key() -> str:
    path = f"{BASE}\\{uuid.uuid4().hex}"
    yield path
    import winreg

    for sub in (path, BASE):
        with contextlib.suppress(OSError):
            winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, sub, winreg.KEY_WOW64_64KEY, 0)


def test_roundtrip_all_types(key: str) -> None:
    from core.registry import RegValue, WinRegBackend

    backend = WinRegBackend()
    values = {
        "dword": RegValue("REG_DWORD", 7),
        "qword": RegValue("REG_QWORD", 2**40),
        "sz": RegValue("REG_SZ", "ñandú"),
        "bin": RegValue("REG_BINARY", bytes.fromhex("9012038010000000")),
        "multi": RegValue("REG_MULTI_SZ", ["a", "b"]),
    }
    for name, value in values.items():
        backend.write("HKCU", key, name, value)
    for name, value in values.items():
        assert backend.read("HKCU", key, name) == value
    assert set(backend.values("HKCU", key)) == set(values)
    assert backend.delete_value("HKCU", key, "sz")
    assert backend.read("HKCU", key, "sz") is None
    assert not backend.delete_value("HKCU", key, "sz")


def test_engine_apply_and_revert_on_real_registry(key: str, tmp_path) -> None:
    from core.appx import AppxManager
    from core.catalog import Catalog
    from core.engine import Engine
    from core.environment import EnvironmentInfo
    from core.registry import Registry, RegValue, WinRegBackend
    from core.restore import RestoreManager, RestoreResult
    from core.services import ServiceManager
    from core.session import SessionStore
    from core.settings import Settings
    from core.tasks import TaskManager
    from tests.conftest import FakeRunner, make_tweak

    tweak = make_tweak(
        id="test.native",
        apply=[
            {
                "op": "registry_set",
                "hive": "HKCU",
                "path": key,
                "name": "V",
                "kind": "REG_DWORD",
                "value": 1,
            }
        ],
    )

    class NoRestorePoint(RestoreManager):
        # No se crean puntos de restauración ni se toca HKLM en el runner de CI.
        def create(self, description: str) -> RestoreResult:
            return RestoreResult(True, "omitido en test")

    backend = WinRegBackend()
    registry = Registry(backend)  # sin SID: HKCU del proceso
    runner = FakeRunner()
    engine = Engine(
        Catalog([tweak]),
        EnvironmentInfo(build=22631, edition="pro", is_admin=True),
        registry,
        runner,
        ServiceManager(registry, runner),
        AppxManager(runner),
        TaskManager(runner),
        RestoreManager(registry, runner),
        SessionStore(tmp_path),
        Settings(dry_run=False, allow_without_restore_point=True, export_reg_backups=False),
    )
    session = engine.apply(["test.native"])
    assert backend.read("HKCU", key, "V") == RegValue("REG_DWORD", 1)
    engine.revert(session.id)
    assert backend.read("HKCU", key, "V") is None
    assert not backend.key_exists("HKCU", key)
