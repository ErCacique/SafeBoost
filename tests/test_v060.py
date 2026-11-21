"""v0.6.0: hardware. Qué RAM comprar, salud del disco y la batería, procesador frenado, drivers
con problemas y análisis rápido con Windows Defender."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from core.defender import TIMEOUT_DEFENDER_SCAN, quick_scan
from core.diagnostics import HardwareInfo, read_hardware
from core.hardware import (
    HARDWARE_SCRIPT,
    BatteryHealth,
    CpuPerf,
    DeviceProblem,
    DiskHealth,
    GpuDriver,
    HardwareDetails,
    MemoryModule,
    hardware_findings,
    parse_details,
    ram_purchase_advice,
)
from core.metrics import GIB
from core.process import CommandError
from tests.conftest import FakeRunner
from tests.test_v040 import analyze, report, snapshot

DDR4_SODIMM = MemoryModule(4 * GIB, mem_type=26, form=12, speed=2400, maker="Samsung")


# --------------------------------------------------------------------------- parseo


def test_parse_full_hardware_payload() -> None:
    details = parse_details(
        {
            "modules": [{"cap": 4 * GIB, "type": 26, "form": 12, "speed": 2666, "part": " X1 "}],
            "disks": {
                "name": "SSD",
                "media": "SSD",
                "size": 256e9,
                "health": "Healthy",
                "wear": 12,
                "temp": 40,
                "read_errors": 0,
                "hours": 900,
            },
            "battery": {"design": 40000, "full": 30000, "cycles": 300},
            "cpu_perf": {"performance": 95, "utility": 20},
            "devices": [{"name": "Wi-Fi", "code": 28}],
            "gpus": [{"name": "Intel UHD", "version": "1.2", "date": "2019-01-01"}],
        }
    )
    mod = details.memory[0]
    assert (mod.type_name, mod.form_name, mod.speed, mod.part) == ("DDR4", "SO-DIMM", 2666, "X1")
    assert details.disks[0].wear == 12  # un solo disco llega como objeto, no como lista
    assert details.battery is not None and details.battery.percent == 75
    assert details.cpu_perf == CpuPerf(95, 20)
    assert details.devices[0].meaning == "no tiene driver instalado"
    assert details.gpus[0].age_days(date(2026, 1, 1)) == 2557


def test_parse_tolerates_old_and_partial_payloads() -> None:
    details = parse_details({"modules": 8 * GIB, "battery": {"design": 0}, "devices": ["x"]})
    assert [m.capacity for m in details.memory] == [8 * GIB]
    assert details.battery is None and details.devices == [] and details.disks == []


def test_read_hardware_keeps_details(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    runner.respond_json(
        "Win32_PhysicalMemoryArray",
        {"cpu": "Celeron", "threads": 2, "slots": 2, "modules": [{"cap": 4 * GIB, "type": 26}]},
    )
    hw = read_hardware(runner)
    assert hw is not None and hw.modules == [4 * GIB]
    assert hw.details.memory[0].type_name == "DDR4"


def test_hardware_script_isolates_sections_and_avoids_localized_counters() -> None:
    for part in (
        "Get-StorageReliabilityCounter",
        "BatteryStaticData",
        "Win32_PnPEntity",
        "Win32_VideoController",
        "Win32_PerfFormattedData_Counters_ProcessorInformation",
    ):
        assert part in HARDWARE_SCRIPT
    assert "Get-Counter" not in HARDWARE_SCRIPT  # sus rutas están traducidas al idioma de Windows
    assert HARDWARE_SCRIPT.count("try {") >= 9


# --------------------------------------------------------------------------- qué RAM comprar


def test_advice_with_free_slot_names_exact_module() -> None:
    advice = ram_purchase_advice([DDR4_SODIMM], slots=2, max_capacity=16 * GIB, installed=4 * GIB)
    assert "DDR4 SO-DIMM de 4 GB" in advice
    assert "2400 MHz" in advice
    assert "ranura libre" in advice


def test_advice_suggests_same_size_for_dual_channel() -> None:
    small = MemoryModule(4 * GIB, mem_type=26, form=12, speed=2400)
    advice = ram_purchase_advice([small], slots=2, max_capacity=32 * GIB, installed=int(3.4 * GIB))
    assert "de 8 GB" in advice and "doble canal" in advice


def test_advice_for_soldered_memory() -> None:
    lp = MemoryModule(4 * GIB, mem_type=30)
    assert "no se puede ampliar" in ram_purchase_advice([lp], 0, 0, 4 * GIB)


def test_advice_when_all_slots_are_full() -> None:
    advice = ram_purchase_advice([DDR4_SODIMM], slots=1, max_capacity=8 * GIB, installed=4 * GIB)
    assert "ocupadas" in advice and "8.0 GB" in advice


def test_advice_without_module_details_is_empty() -> None:
    assert ram_purchase_advice([], 2, 0, 4 * GIB) == ""


def test_low_ram_finding_includes_purchase_advice() -> None:
    hw = HardwareInfo(
        threads=4, slots=2, modules=[4 * GIB], details=HardwareDetails(memory=[DDR4_SODIMM])
    )
    finding = analyze(report(snap=snapshot(ram_total=3.8 * GIB), hardware=hw))[0]
    assert finding.title == "Poca memoria RAM"
    assert "Compra un módulo DDR4 SO-DIMM" in finding.detail


# --------------------------------------------------------------------------- salud del hardware


def titles(details: HardwareDetails, **kw: Any) -> dict[str, str]:
    return {title: level for level, title, _d in hardware_findings(details, **kw)}


def test_failing_disk_is_critical() -> None:
    found = titles(HardwareDetails(disks=[DiskHealth("WD", health="Unhealthy")]))
    assert found == {"El disco puede estar fallando": "critical"}
    assert "El disco puede estar fallando" in titles(
        HardwareDetails(disks=[DiskHealth("WD", health="Healthy", read_errors=3)])
    )


def test_worn_and_hot_ssd() -> None:
    found = titles(HardwareDetails(disks=[DiskHealth("SSD", health="Healthy", wear=85, temp=66)]))
    assert found == {"SSD desgastado": "warning", "Disco muy caliente": "warning"}
    assert titles(HardwareDetails(disks=[DiskHealth("SSD", health="Healthy", wear=10)])) == {}


@pytest.mark.parametrize(
    "full, expected",
    [
        (22000, {"Batería muy gastada": "warning"}),
        (30000, {"Batería algo gastada": "info"}),
        (38000, {}),
    ],
)
def test_battery_health(full: int, expected: dict[str, str]) -> None:
    assert titles(HardwareDetails(battery=BatteryHealth(40000, full, 500))) == expected


def test_throttled_cpu_cause_depends_on_power_source() -> None:
    details = HardwareDetails(cpu_perf=CpuPerf(performance=40, utility=90))
    plugged = hardware_findings(details, plugged=True)
    assert plugged[0][1] == "Procesador frenado" and "ventilador" in plugged[0][2]
    on_battery = hardware_findings(details, plugged=False)
    assert "batería" in on_battery[0][2]
    assert hardware_findings(HardwareDetails(cpu_perf=CpuPerf(40, 10))) == []  # en reposo es normal


def test_device_problem_and_old_gpu_driver() -> None:
    details = HardwareDetails(
        devices=[DeviceProblem("Bluetooth", 43)],
        gpus=[GpuDriver("Intel HD", "9.1", "2018-05-01"), GpuDriver("Nueva", "31", "2026-01-01")],
    )
    found = hardware_findings(details, today=date(2026, 11, 21))
    assert [f[1] for f in found] == ["Dispositivo con problemas", "Driver de gráfica antiguo"]
    assert "Windows lo detuvo" in found[0][2]
    assert "Intel HD" in found[1][2]


def test_hardware_findings_reach_the_verdict() -> None:
    hw = HardwareInfo(
        threads=8,
        slots=2,
        modules=[16 * GIB],
        details=HardwareDetails(disks=[DiskHealth("WD", health="Warning")]),
    )
    findings = analyze(report(hardware=hw))
    assert findings[0].title == "El disco puede estar fallando"


# --------------------------------------------------------------------------- Defender


class DefenderRunner(FakeRunner):
    def __init__(self, payload: Any) -> None:
        super().__init__()
        self.payload = payload
        self.timeouts: list[int] = []

    def powershell_json(self, script: str, timeout: int = 120) -> Any:
        self.timeouts.append(timeout)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_defender_clean_scan() -> None:
    runner = DefenderRunner({"enabled": True, "threats": [], "signature_age": 1})
    result = quick_scan(runner)
    assert result.ran and result.threats == []
    assert "ninguna amenaza" in result.message
    assert runner.timeouts == [TIMEOUT_DEFENDER_SCAN]


def test_defender_reports_threats_and_old_signatures() -> None:
    result = quick_scan(
        DefenderRunner({"enabled": True, "threats": "Trojan:X", "signature_age": 20})
    )
    assert result.threats == ["Trojan:X"]
    assert "1 amenaza" in result.message and "20 días" in result.message


def test_defender_passive_when_other_antivirus() -> None:
    result = quick_scan(DefenderRunner({"enabled": False, "mode": "Passive Mode"}))
    assert not result.ran and "Passive Mode" in result.message


def test_defender_failure_is_reported() -> None:
    result = quick_scan(DefenderRunner(CommandError("cmdlet no encontrado")))
    assert not result.ran and "No se pudo" in result.message
