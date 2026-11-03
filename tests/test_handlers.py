"""Handlers de tweaks/ con runner y registro simulados."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from core.constants import POWER_SCHEMES, TCPIP_INTERFACES_KEY
from core.context import DetectState
from core.engine import Engine
from core.process import CommandResult
from core.registry import MemoryRegistryBackend, RegValue
from tests.conftest import FakeRunner
from tweaks.gaming import parse_dxdiag

EngineFactory = Callable[..., Engine]
BALANCED = POWER_SCHEMES["balanced"]
HIGH = POWER_SCHEMES["high_performance"]


class PowerRunner(FakeRunner):
    def __init__(self, schemes: set[str]) -> None:
        super().__init__()
        self.active = BALANCED
        self.schemes = schemes

    def run(self, args: list[str], timeout: int = 60, encoding: str | None = None) -> CommandResult:
        self.calls.append(list(args))
        if "/getactivescheme" in args:
            return CommandResult(tuple(args), 0, f"GUID del plan de energía: {self.active}", "")
        if "/list" in args:
            return CommandResult(tuple(args), 0, "\n".join(self.schemes), "")
        if "/duplicatescheme" in args:
            self.schemes.add(args[-1])
        if "/setactive" in args:
            self.active = args[-1]
        return CommandResult(tuple(args), 0, "", "")


@pytest.fixture
def power_runner() -> PowerRunner:
    return PowerRunner({BALANCED})


def test_power_scheme_created_on_canonical_guid_and_restored(
    make_engine: EngineFactory, power_runner: PowerRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine()
    engine.runner = power_runner
    session = engine.apply(["power.high_performance"])
    assert session.results["power.high_performance"].status == "applied"
    assert power_runner.active == HIGH
    assert any(c[1:] == ["/duplicatescheme", HIGH, HIGH] for c in power_runner.calls)
    assert session.handler_state["power.high_performance"] == {
        "previous": BALANCED,
        "created": HIGH,
    }
    assert engine.detect(engine.catalog.get("power.high_performance")).state == (
        DetectState.APPLIED
    )
    engine.revert(session.id)
    assert power_runner.active == BALANCED
    assert any(c[1:] == ["/delete", HIGH] for c in power_runner.calls)


def test_power_scheme_already_active_is_noop(
    make_engine: EngineFactory, power_runner: PowerRunner
) -> None:
    power_runner.active = HIGH
    engine = make_engine()
    engine.runner = power_runner
    assert engine.apply(["power.high_performance"]).results["power.high_performance"].status == (
        "skipped"
    )


def test_nagle_writes_only_active_interfaces_and_reverts(
    make_engine: EngineFactory, backend: MemoryRegistryBackend
) -> None:
    active = f"{TCPIP_INTERFACES_KEY}\\{{AAAA}}"
    idle = f"{TCPIP_INTERFACES_KEY}\\{{BBBB}}"
    backend.write("HKLM", active, "DhcpIPAddress", RegValue("REG_SZ", "192.168.1.5"))
    backend.write("HKLM", idle, "DhcpIPAddress", RegValue("REG_SZ", "0.0.0.0"))  # noqa: S104
    engine = make_engine()
    tweak = engine.catalog.get("network.nagle_off")
    assert engine.detect(tweak).state == DetectState.NOT_APPLIED
    session = engine.apply([tweak.id])
    assert backend.read("HKLM", active, "TCPNoDelay") == RegValue("REG_DWORD", 1)
    assert backend.read("HKLM", idle, "TCPNoDelay") is None
    assert engine.detect(tweak).state == DetectState.APPLIED
    engine.revert(session.id)
    assert backend.read("HKLM", active, "TCPNoDelay") is None


def test_dns_requires_provider(make_engine: EngineFactory) -> None:
    result = make_engine().apply(["network.dns"]).results["network.dns"]
    assert result.status == "failed"
    assert "proveedor" in result.message


def test_dns_set_and_restore_dhcp(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.respond_json(
        "Get-NetAdapter",
        [{"index": 7, "name": "Ethernet", "static": "", "servers": ["192.168.1.1"]}],
    )
    engine = make_engine()
    session = engine.apply(["network.dns"], params={"network.dns": {"provider": "quad9"}})
    assert session.results["network.dns"].status == "applied"
    assert any("-ServerAddresses @('9.9.9.9','149.112.112.112')" in s for s in runner.scripts)
    engine.revert(session.id)
    assert any("-InterfaceIndex 7 -ResetServerAddresses" in s for s in runner.scripts)


def test_dns_blocked_on_domain(make_engine: EngineFactory) -> None:
    session = make_engine(domain_joined=True).apply(
        ["network.dns"], params={"network.dns": {"provider": "google"}}
    )
    assert session.results["network.dns"].status == "skipped"


def test_autotuning_restores_previous_level(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.respond_json("Get-NetTCPSetting", [{"level": "Disabled"}])
    engine = make_engine()
    session = engine.apply(["network.autotuning_normal"])
    assert any(c[-1] == "autotuninglevel=normal" for c in runner.calls)
    engine.revert(session.id)
    assert runner.calls[-1][-1] == "autotuninglevel=disabled"


def test_pagefile_system_managed(make_engine: EngineFactory, runner: FakeRunner) -> None:
    previous = {
        "auto": False,
        "settings": [{"name": "C:\\pagefile.sys", "initial": 2048, "maximum": 2048}],
    }
    runner.respond_json("Win32_PageFileSetting", previous)
    engine = make_engine()
    session = engine.apply(["memory.pagefile_system_managed"])
    assert any("AutomaticManagedPagefile=$true" in s for s in runner.scripts)
    engine.revert(session.id)
    assert any("InitialSize=[uint32]2048" in s for s in runner.scripts)


def test_pagefile_fixed_rejects_tiny_size(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.respond_json("Win32_PageFileSetting", {"auto": True, "settings": []})
    session = make_engine().apply(
        ["memory.pagefile_fixed"], params={"memory.pagefile_fixed": {"size_mb": 512}}
    )
    assert "mínimo" in session.results["memory.pagefile_fixed"].message


def test_indexing_only_non_system_drives(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.respond_json(
        "Win32_Volume", [{"letter": "C:", "indexing": True}, {"letter": "D:", "indexing": True}]
    )
    engine = make_engine()
    session = engine.apply(["search.indexing_drives"])
    changed = [s for s in runner.scripts if "IndexingEnabled=$false" in s]
    assert len(changed) == 1
    assert "'D:'" in changed[0]
    assert session.handler_state["search.indexing_drives"] == {"previous": {"D:": True}}


def test_cleanup_respects_age_and_dry_run(
    make_engine: EngineFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp = tmp_path / "Temp"
    (temp / "sub").mkdir(parents=True)
    old, new = temp / "sub" / "old.log", temp / "new.log"
    old.write_bytes(b"x" * 2048)
    new.write_bytes(b"y")
    os.utime(old, (0, 0))
    monkeypatch.setattr("tweaks.cleanup.SYSTEM_ROOT", tmp_path)
    engine = make_engine()
    item = engine.plan(["cleanup.temp_windows"])[0]
    assert "1 archivos" in item.lines[0]
    assert old.exists()
    detected = engine.detect(engine.catalog.get("cleanup.temp_windows"))
    assert detected.data["files"] == 1
    engine.apply(["cleanup.temp_windows"], confirmed={"cleanup.temp_windows"})
    assert not old.exists()
    assert new.exists()
    assert not (temp / "sub").exists()


def test_cleanup_nothing_to_do_is_skipped(
    make_engine: EngineFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tweaks.cleanup.SYSTEM_ROOT", tmp_path)
    item = make_engine().plan(["cleanup.wu_cache"])[0]
    assert "nada que limpiar" in item.lines[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hardware Scheduling: Supported:True Enabled:False", True),
        ("Hardware Scheduling: Supported:False Enabled:False", False),
        ("Driver Model: WDDM 3.1", True),
        ("Driver Model: WDDM 2.6", False),
        ("", False),
    ],
)
def test_parse_dxdiag(text: str, expected: bool) -> None:
    assert parse_dxdiag(text) is expected


def test_hags_not_applicable_without_support(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    runner.fail_on.append("dxdiag")
    engine = make_engine()
    assert not engine.evaluate(engine.catalog.get("gaming.hags")).applicable


def test_indexing_explicit_drive_selection(make_engine: EngineFactory, runner: FakeRunner) -> None:
    runner.respond_json(
        "Win32_Volume",
        [
            {"letter": "C:", "indexing": True},
            {"letter": "D:", "indexing": True},
            {"letter": "E:", "indexing": True},
        ],
    )
    engine = make_engine()
    session = engine.apply(
        ["search.indexing_drives"], params={"search.indexing_drives": {"drives": ["E:"]}}
    )
    changed = [s for s in runner.scripts if "IndexingEnabled=$false" in s]
    assert len(changed) == 1 and "'E:'" in changed[0]
    assert session.handler_state["search.indexing_drives"] == {"previous": {"E:": True}}


def test_indexing_empty_selection_is_skipped(
    make_engine: EngineFactory, runner: FakeRunner
) -> None:
    runner.respond_json("Win32_Volume", [{"letter": "D:", "indexing": True}])
    session = make_engine().apply(
        ["search.indexing_drives"], params={"search.indexing_drives": {"drives": []}}
    )
    assert session.results["search.indexing_drives"].status == "skipped"
