"""Métricas, comparación y recomendación de perfil."""

from __future__ import annotations

from core.environment import EnvironmentInfo
from core.metrics import (
    GIB,
    BootInfo,
    MetricsStore,
    Snapshot,
    compare,
    human_bytes,
    last_boot,
    recommend_profile,
)
from tests.conftest import FakeRunner


def snap(
    ram_avail: int = 4 * GIB,
    procs: int = 120,
    free: int = 50 * GIB,
    ram_total: int = 16 * GIB,
    boot: BootInfo | None = None,
) -> Snapshot:
    return Snapshot(
        "2026-01-01T00:00:00", ram_total, ram_avail, 50.0, 10.0, 100 * GIB, free, procs, boot
    )


def test_compare() -> None:
    before = snap(boot=BootInfo(30000, "a"))
    after = snap(ram_avail=5 * GIB, procs=100, free=52 * GIB, boot=BootInfo(25000, "b"))
    result = compare(before, after)
    assert result.ram_freed == GIB
    assert result.process_delta == -20
    assert result.disk_freed == 2 * GIB
    assert result.boot_delta_ms == -5000


def test_compare_same_boot_has_no_delta() -> None:
    boot = BootInfo(30000, "same")
    assert compare(snap(boot=boot), snap(boot=boot)).boot_delta_ms is None


def test_recommendation(env: EnvironmentInfo) -> None:
    assert recommend_profile(env, snap())[0] == 2
    assert recommend_profile(env, snap(ram_total=4 * GIB))[0] == 3
    env.chassis = "laptop"
    assert recommend_profile(env, snap(ram_total=4 * GIB))[0] == 2
    env.domain_joined = True
    assert recommend_profile(env, snap())[0] == 1


def test_human_bytes() -> None:
    assert human_bytes(512) == "512 B"
    assert human_bytes(1536) == "1.5 KB"
    assert human_bytes(-3 * GIB) == "-3.0 GB"


def test_last_boot(runner: FakeRunner) -> None:
    runner.respond_json("EventID=100", {"boot_ms": 21000, "timestamp": "2026-11-02T08:00:00"})
    assert last_boot(runner) == BootInfo(21000, "2026-11-02T08:00:00")


def test_metrics_store_post_reboot(tmp_path, runner: FakeRunner) -> None:
    store = MetricsStore(tmp_path)
    store.save("s1", "before", snap(boot=BootInfo(30000, "boot-1")))
    store.save("s1", "after", snap())
    assert store.pending_reboot_sessions() == ["s1"]
    runner.respond_json("EventID=100", {"boot_ms": 30000, "timestamp": "boot-1"})
    assert store.capture_post_reboot(runner, "C:") == []
    runner.json_responses.clear()
    runner.respond_json("EventID=100", {"boot_ms": 20000, "timestamp": "boot-2"})
    assert store.capture_post_reboot(runner, "C:") == ["s1"]
    assert store.get("s1", "after_reboot").boot.boot_ms == 20000
