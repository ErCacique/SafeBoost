"""Gestor de inicio: formato StartupApproved, inventario, cambio y deshacer."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from core.engine import Engine
from core.registry import MemoryRegistryBackend, Registry, RegValue
from core.session import Session
from core.tasks import TaskManager
from tests.conftest import USER_SID, FakeRunner
from tweaks.startup import (
    StartupManager,
    approved_value,
    executable_from_command,
    is_approved_enabled,
)

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def test_approved_value_format() -> None:
    assert approved_value(True) == b"\x02" + b"\x00" * 11
    disabled = approved_value(False)
    assert len(disabled) == 12
    assert disabled[0] == 3
    assert is_approved_enabled(RegValue("REG_BINARY", approved_value(True)))
    assert not is_approved_enabled(RegValue("REG_BINARY", disabled))
    assert is_approved_enabled(None)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (r'"C:\Program Files\App\app.exe" /min', r"C:\Program Files\App\app.exe"),
        (r"C:\Tools\tool.exe --quiet", r"C:\Tools\tool.exe"),
        ("rundll32", None),
    ],
)
def test_executable_from_command(command: str, expected: str | None) -> None:
    result = executable_from_command(command)
    assert (str(result).replace("/", "\\") if result else None) == expected


def test_toggle_records_change_and_engine_reverts_it(
    make_engine: Callable[..., Engine],
    backend: MemoryRegistryBackend,
    runner: FakeRunner,
    env,
) -> None:
    backend.write("HKU", rf"{USER_SID}\{RUN}", "Spotify", RegValue("REG_SZ", r'"C:\s.exe"'))
    runner.respond_json("MSFT_TaskLogonTrigger", [])
    engine = make_engine()
    manager = StartupManager(Registry(backend, USER_SID), runner, TaskManager(runner), env)
    entries = [e for e in manager.list() if e.name == "Spotify"]
    assert entries and entries[0].enabled and entries[0].scope == "HKCU"

    session = Session.new("apply")
    manager.set_enabled(entries[0], False, session)
    engine.store.save(session)
    value = backend.read("HKU", rf"{USER_SID}\{APPROVED}", "Spotify")
    assert value is not None and value.data[0] == 3
    assert not next(e for e in manager.list() if e.name == "Spotify").enabled

    revert = engine.revert(session.id)
    assert {r.status for r in revert.results.values()} == {"reverted"}
    assert backend.read("HKU", rf"{USER_SID}\{APPROVED}", "Spotify") is None
