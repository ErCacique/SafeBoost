"""Diagnóstico de "¿por qué va lento?": procesos, hardware, actualizaciones y Windows 11.

Solo lee. El veredicto (`analyze`) es una función pura sobre el informe para poder probarlo sin
Windows; la recogida de datos (`collect`) usa psutil y una única consulta de PowerShell.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import psutil

from core.boot import BootReport, read_boot_culprits
from core.constants import (
    DIAG_BOOT_CULPRIT_WARN_MS,
    DIAG_CPU_BUSY_PERCENT,
    DIAG_LOW_DISK_FREE_PERCENT,
    DIAG_PROCESS_HOG_PERCENT,
    DIAG_RAM_PRESSURE_PERCENT,
    DIAG_SAMPLE_SECONDS,
    DIAG_TOP_PROCESSES,
    DIAG_WEAK_CPU_THREADS,
    KNOWN_PROCESSES,
    LOW_RAM_GIB,
    MIN_BUILD_WIN11,
    WIN10_END_OF_SUPPORT,
    WIN11_MIN_RAM_GIB,
    WIN11_MIN_STORAGE_GIB,
)
from core.environment import EnvironmentInfo, UpdateStatus, read_update_status
from core.hardware import (
    HardwareDetails,
    hardware_findings,
    parse_details,
    query_hardware,
    ram_purchase_advice,
)
from core.i18n import _
from core.logger import get_logger
from core.metrics import GIB, Snapshot, human_bytes, take_snapshot
from core.process import Runner
from core.registry import Registry
from core.security import SecurityReport, read_security

log = get_logger("diagnostics")

Level = Literal["critical", "warning", "info", "ok"]
_LEVEL_ORDER: dict[str, int] = {"critical": 0, "warning": 1, "info": 2, "ok": 3}


@dataclass
class HardwareInfo:
    cpu_name: str = ""
    cores: int = 0
    threads: int = 0
    mhz: int = 0
    slots: int = 0
    modules: list[int] = field(default_factory=list)  # bytes por módulo instalado
    max_capacity: int = 0  # bytes; 0 = desconocido
    tpm_version: str = ""
    secure_boot: bool | None = None
    firmware: str = ""  # "UEFI" / "Legacy" / ""
    details: HardwareDetails = field(default_factory=HardwareDetails)

    @property
    def installed_ram(self) -> int:
        return sum(self.modules)

    @property
    def free_slots(self) -> int | None:
        if not self.slots or not self.modules:
            return None
        return max(self.slots - len(self.modules), 0)

    @property
    def tpm2(self) -> bool | None:
        if not self.tpm_version:
            return None
        return self.tpm_version.strip().startswith("2.")


@dataclass
class ProcessUsage:
    name: str
    cpu_percent: float  # porcentaje del total del equipo (todas las CPU = 100 %)
    memory: int
    count: int = 1

    @property
    def hint(self) -> str:
        return KNOWN_PROCESSES.get(self.name.lower(), "")


@dataclass
class Requirement:
    name: str
    ok: bool | None  # None = no se pudo comprobar
    detail: str


@dataclass
class Finding:
    level: Level
    title: str
    detail: str


@dataclass
class DiagnosticReport:
    env: EnvironmentInfo
    snapshot: Snapshot
    disk_total: int
    top_cpu: list[ProcessUsage]
    top_memory: list[ProcessUsage]
    hardware: HardwareInfo | None
    updates: UpdateStatus
    win11: list[Requirement] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    boot: BootReport = field(default_factory=BootReport)
    security: SecurityReport = field(default_factory=SecurityReport)

    @property
    def ram_installed(self) -> int:
        """RAM física instalada si se conoce; si no, la que ve Windows (algo menor)."""
        if self.hardware and self.hardware.installed_ram:
            return self.hardware.installed_ram
        return self.snapshot.ram_total


# --------------------------------------------------------------------------- recogida


def sample_processes(
    interval: float = DIAG_SAMPLE_SECONDS, sleep: Callable[[float], None] = time.sleep
) -> list[ProcessUsage]:
    """Uso de CPU medido durante `interval` y memoria, agrupados por nombre de ejecutable
    (un navegador con 15 procesos cuenta como uno)."""
    procs = []
    for proc in psutil.process_iter(["name"]):
        if proc.pid == 0:  # "System Idle Process"
            continue
        try:
            proc.cpu_percent(None)
            procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    sleep(interval)
    cpus = psutil.cpu_count() or 1
    grouped: dict[str, ProcessUsage] = {}
    for proc in procs:
        try:
            name = proc.info.get("name") or f"pid {proc.pid}"
            cpu = proc.cpu_percent(None) / cpus
            mem = proc.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        usage = grouped.get(name.lower())
        if usage is None:
            grouped[name.lower()] = ProcessUsage(name, cpu, mem)
        else:
            usage.cpu_percent += cpu
            usage.memory += mem
            usage.count += 1
    return list(grouped.values())


def read_hardware(runner: Runner) -> HardwareInfo | None:
    data = query_hardware(runner)
    if data is None:
        return None
    secure_boot = data.get("secure_boot")
    details = parse_details(data)
    return HardwareInfo(
        cpu_name=str(data.get("cpu") or "").strip(),
        cores=int(data.get("cores") or 0),
        threads=int(data.get("threads") or 0),
        mhz=int(data.get("mhz") or 0),
        slots=int(data.get("slots") or 0),
        modules=[m.capacity for m in details.memory],
        max_capacity=int(data.get("max_kb") or 0) * 1024,
        tpm_version=str(data.get("tpm") or ""),
        secure_boot=secure_boot if isinstance(secure_boot, bool) else None,
        firmware=str(data.get("firmware") or ""),
        details=details,
    )


def collect(
    env: EnvironmentInfo,
    registry: Registry,
    runner: Runner,
    sampler: Callable[[], list[ProcessUsage]] = sample_processes,
) -> DiagnosticReport:
    """Recoge todo el informe (~2-5 s). Llamar desde un hilo de trabajo."""
    processes = sampler()
    snapshot = take_snapshot(env.system_drive, cpu_interval=0)
    # La CPU del equipo durante el muestreo: la suma por proceso es más fiable que una
    # lectura instantánea, que justo después de muestrear tiende a dar 0.
    snapshot.cpu_percent = min(100.0, sum(p.cpu_percent for p in processes))
    hardware = read_hardware(runner)
    report = DiagnosticReport(
        env=env,
        snapshot=snapshot,
        disk_total=snapshot.disk_total,
        top_cpu=sorted(processes, key=lambda p: p.cpu_percent, reverse=True)[:DIAG_TOP_PROCESSES],
        top_memory=sorted(processes, key=lambda p: p.memory, reverse=True)[:DIAG_TOP_PROCESSES],
        hardware=hardware,
        updates=read_update_status(registry, runner),
        boot=read_boot_culprits(runner),
        security=read_security(registry, runner, env),
    )
    report.win11 = win11_requirements(report)
    report.findings = analyze(report)
    return report


# --------------------------------------------------------------------------- Windows 11


def win11_requirements(report: DiagnosticReport) -> list[Requirement]:
    """Requisitos mínimos de Windows 11 que se pueden comprobar sin herramientas de Microsoft."""
    hw = report.hardware
    ram_gib = report.ram_installed / GIB
    # Con los módulos leídos la cifra es exacta. Sin ellos solo se sabe lo que ve Windows, que
    # descuenta la memoria reservada (un equipo de 4 GB muestra ~3.8 GiB): margen de 0.5 GiB.
    margin = 0.01 if hw and hw.installed_ram else 0.5
    reqs = [
        Requirement(
            "Memoria RAM",
            ram_gib >= WIN11_MIN_RAM_GIB - margin,
            f"{human_bytes(report.ram_installed)} (mínimo {WIN11_MIN_RAM_GIB} GB)",
        ),
        Requirement(
            "Disco del sistema",
            report.disk_total / GIB >= WIN11_MIN_STORAGE_GIB * 0.93,  # 64 GB ≈ 59.6 GiB
            f"{human_bytes(report.disk_total)} (mínimo {WIN11_MIN_STORAGE_GIB} GB)",
        ),
    ]
    if hw is None:
        reqs.append(Requirement("TPM 2.0 y arranque seguro", None, "No se pudo consultar"))
    else:
        reqs.append(
            Requirement(
                "TPM 2.0",
                hw.tpm2,
                f"Versión {hw.tpm_version.split(',')[0]}" if hw.tpm_version else "No detectado",
            )
        )
        uefi = hw.firmware.upper() == "UEFI" if hw.firmware else None
        reqs.append(
            Requirement(
                "Arranque UEFI con arranque seguro",
                uefi,  # Windows 11 exige UEFI con arranque seguro "disponible", no activado
                "BIOS antigua (Legacy)"
                if uefi is False
                else "UEFI, arranque seguro "
                + {True: "activado", False: "desactivado (se puede activar en la BIOS)", None: "?"}[
                    hw.secure_boot
                ],
            )
        )
    reqs.append(
        Requirement(
            "Procesador compatible",
            None,
            "Microsoft mantiene una lista de modelos: compruébalo con la app "
            "“Comprobación de estado del PC”.",
        )
    )
    return reqs


# --------------------------------------------------------------------------- veredicto


def analyze(report: DiagnosticReport) -> list[Finding]:
    """Convierte las medidas en hallazgos ordenados por gravedad, en lenguaje claro."""
    findings: list[Finding] = []
    snap = report.snapshot
    hw = report.hardware
    ram = report.ram_installed

    if ram < LOW_RAM_GIB * GIB:
        findings.append(Finding("critical", _("Poca memoria RAM"), _ram_advice(ram, hw)))
    elif snap.ram_percent >= DIAG_RAM_PRESSURE_PERCENT:
        hog = report.top_memory[0] if report.top_memory else None
        detail = _(
            "La RAM está al {pct} %. Windows usa el disco como memoria y va a tirones.",
            pct=f"{snap.ram_percent:.0f}",
        )
        if hog:
            detail += " " + _("Lo que más ocupa: {what}.", what=_describe(hog, memory=True))
        findings.append(Finding("warning", _("Memoria casi llena"), detail))

    for check in report.security.problems:
        if check.critical:
            findings.append(
                Finding(
                    "critical",
                    _("Seguridad: {name}", name=_(check.name)),
                    _(
                        "{detail}. Actívalo en Seguridad de Windows: un equipo sin esta "
                        "protección también puede ir lento por malware.",
                        detail=_(check.detail),
                    ),
                )
            )

    if report.updates.reboot_pending:
        findings.append(
            Finding(
                "warning",
                _("Reinicio pendiente de Windows Update"),
                _(
                    "Windows tiene actualizaciones a medio instalar. Reinicia antes de optimizar "
                    "o de medir el rendimiento."
                ),
            )
        )
    elif report.updates.stale:
        findings.append(
            Finding(
                "warning",
                _("Windows sin actualizar"),
                _(
                    "La última actualización se instaló hace {days} días. Ejecuta Windows Update "
                    "hasta que diga “Estás al día”.",
                    days=report.updates.last_update_days,
                ),
            )
        )

    busy = snap.cpu_percent >= DIAG_CPU_BUSY_PERCENT
    top = report.top_cpu[0] if report.top_cpu else None
    if top and top.cpu_percent >= DIAG_PROCESS_HOG_PERCENT:
        detail = _(
            "{what} está usando el {pct} % del procesador.",
            what=_describe(top),
            pct=f"{top.cpu_percent:.0f}",
        )
        if top.hint:
            detail += f" {_(top.hint)}"
        title = _("Proceso acaparando la CPU")
        findings.append(Finding("warning" if busy else "info", title, detail))
    elif busy:
        findings.append(
            Finding(
                "warning",
                _("Procesador saturado"),
                _(
                    "La CPU está al {pct} % repartida entre muchos procesos.",
                    pct=f"{snap.cpu_percent:.0f}",
                ),
            )
        )

    worst = report.boot.culprits[0] if report.boot.culprits else None
    if worst and worst.avg_ms >= DIAG_BOOT_CULPRIT_WARN_MS:
        times = (
            _(" en {n} de {total} arranques", n=worst.count, total=report.boot.boots)
            if report.boot.boots >= worst.count
            else ""
        )
        findings.append(
            Finding(
                "warning",
                _("Algo retrasa el arranque"),
                _(
                    "{name} ({kind}) retrasa el arranque unos {secs} s{times}. {advice} Mira la "
                    "lista completa más abajo.",
                    name=worst.name,
                    kind=_(worst.kind),
                    secs=f"{worst.avg_ms / 1000:.0f}",
                    times=times,
                    advice=_(worst.advice),
                ),
            )
        )

    if hw and 0 < hw.threads <= DIAG_WEAK_CPU_THREADS:
        findings.append(
            Finding(
                "info",
                _("Procesador modesto"),
                _(
                    "{cpu} tiene {threads} hilos: con varias cosas abiertas a la vez se queda "
                    "corto. No se puede mejorar con ajustes.",
                    cpu=hw.cpu_name or _("El procesador"),
                    threads=hw.threads,
                ),
            )
        )

    if hw is not None:
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        plugged = None if battery is None else bool(battery.power_plugged)
        for level, title, detail in hardware_findings(hw.details, plugged):
            findings.append(Finding(level, _(title), detail))  # type: ignore[arg-type]

    if report.env.disk_type == "hdd":
        findings.append(
            Finding(
                "warning",
                _("Disco mecánico (HDD)"),
                _(
                    "Cambiar el disco del sistema por un SSD es la mejora más notable en un "
                    "equipo con disco duro: arranque y apertura de programas varias veces más "
                    "rápidos."
                ),
            )
        )
    free_pct = snap.disk_free / snap.disk_total * 100 if snap.disk_total else 100
    if free_pct < DIAG_LOW_DISK_FREE_PERCENT:
        findings.append(
            Finding(
                "warning",
                _("Poco espacio en disco"),
                _(
                    "Quedan {free} libres ({pct} %). Windows necesita espacio para actualizarse y "
                    "para la memoria virtual: usa Limpieza.",
                    free=human_bytes(snap.disk_free),
                    pct=f"{free_pct:.0f}",
                ),
            )
        )

    if MIN_BUILD_WIN11 > report.env.build >= 1:
        ready = [r.ok for r in report.win11]
        verdict = (
            _("No cumple los requisitos de Windows 11")
            if False in ready
            else _("Puede que admita Windows 11 (revisa la lista de requisitos)")
        )
        findings.append(
            Finding(
                "info",
                _("Windows 10 sin soporte"),
                _(
                    "Windows 10 dejó de recibir parches gratuitos el {date}. {verdict}.",
                    date=WIN10_END_OF_SUPPORT,
                    verdict=verdict,
                ),
            )
        )

    if not any(f.level in ("critical", "warning") for f in findings):
        findings.insert(
            0,
            Finding(
                "ok",
                _("No hay un cuello de botella claro"),
                _(
                    "Memoria, procesador y disco tienen margen. Si notas lentitud en un momento "
                    "concreto, vuelve a analizar justo entonces."
                ),
            ),
        )
    findings.sort(key=lambda f: _LEVEL_ORDER[f.level])
    return findings


def _ram_advice(ram: int, hw: HardwareInfo | None) -> str:
    text = _(
        "El equipo tiene {ram}. Windows y un navegador ya la llenan, y entonces usa el disco como "
        "memoria. Ningún perfil de SafeBoost sustituye a ampliar memoria.",
        ram=human_bytes(ram),
    )
    if hw is None or hw.free_slots is None:
        return text + " " + _("Ampliar a 8 GB es la mejora que más se notaría.")
    if hw.free_slots > 0:
        text += " " + _(
            "Tiene {n} ranura(s) libre(s): añadir un módulo de 4 u 8 GB es la mejora que más se "
            "notaría.",
            n=hw.free_slots,
        )
    else:
        text += " " + _(
            "Las {n} ranura(s) están ocupadas: habría que sustituir un módulo por otro mayor.",
            n=hw.slots,
        )
    if hw.max_capacity:
        text += " " + _(
            "La placa admite hasta {cap}.",
            cap=human_bytes(hw.max_capacity),
        )
    advice = ram_purchase_advice(hw.details.memory, hw.slots, hw.max_capacity, ram)
    return f"{text} {advice}" if advice else text


def _describe(proc: ProcessUsage, memory: bool = False) -> str:
    many = f" ({proc.count} procesos)" if proc.count > 1 else ""
    if memory:
        return f"{proc.name}{many}, {human_bytes(proc.memory)}"
    return f"{proc.name}{many}"
