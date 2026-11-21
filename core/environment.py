"""Detección del entorno: versión/edición de Windows, disco, chasis, dominio/MDM, impresoras."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import psutil

from core.constants import (
    EDITION_MAP,
    LAPTOP_CHASSIS_TYPES,
    MIN_BUILD_WIN10,
    MIN_BUILD_WIN11,
    UPDATE_STALE_DAYS,
    VIRTUAL_PRINTER_MARKERS,
    WIN10_END_OF_SUPPORT,
    WU_REBOOT_KEYS,
)
from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote, resolve_exe
from core.registry import Registry

log = get_logger("environment")

DiskType = Literal["ssd", "hdd", "unknown"]
Chassis = Literal["desktop", "laptop", "unknown"]

_CURRENT_VERSION = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"


@dataclass
class EnvironmentInfo:
    build: int = 0
    ubr: int = 0
    display_version: str = ""
    product_name: str = ""
    edition_id: str = ""
    edition: str = "unknown"
    system_drive: str = "C:"
    disk_type: DiskType = "unknown"
    chassis: Chassis = "unknown"
    has_battery: bool = False
    domain_joined: bool = False
    domain_name: str = ""
    entra_joined: bool = False
    mdm_enrolled: bool = False
    printers: list[str] = field(default_factory=list)
    fixed_drives: list[str] = field(default_factory=list)
    interactive_user: str = ""
    interactive_sid: str | None = None
    elevated_user: str = ""
    is_admin: bool = False
    reboot_pending: bool = False
    last_update_days: int | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def os_major(self) -> str:
        return "11" if self.build >= MIN_BUILD_WIN11 else "10"

    @property
    def os_label(self) -> str:
        # ProductName sigue diciendo "Windows 10" en Windows 11; se deriva de la build.
        return f"Windows {self.os_major} {self.display_version} (build {self.build}.{self.ubr})"

    @property
    def managed(self) -> bool:
        """Equipo de dominio, unido a Entra ID o inscrito en MDM: las directivas no se tocan."""
        return self.domain_joined or self.entra_joined or self.mdm_enrolled

    @property
    def has_printers(self) -> bool:
        return bool(self.printers)

    @property
    def supported(self) -> bool:
        return self.build >= MIN_BUILD_WIN10 and self.edition != "unknown"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(os_label=self.os_label, managed=self.managed, supported=self.supported)
        return data


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except OSError:
        return False


StepProgress = Callable[[str], None]


def _no_progress(_message: str) -> None:
    return None


class EnvironmentDetector:
    """Detecta el entorno con UNA sola llamada a PowerShell (más dsregcmd y psutil).

    Arrancar PowerShell cuesta 2-4 s en un equipo flojo; antes se lanzaba siete veces seguidas.
    Cada consulta va en su propio try/catch dentro del script, así que un fallo solo deja ese
    dato como "desconocido" con su aviso, igual que cuando eran llamadas separadas.
    """

    def __init__(self, registry: Registry, runner: Runner) -> None:
        self.registry = registry
        self.runner = runner
        self.facts: dict[str, Any] = {}
        self.timings: dict[str, int] = {}  # ms por paso, también en el log

    def detect(self, progress: StepProgress = _no_progress) -> EnvironmentInfo:
        env = EnvironmentInfo(is_admin=is_admin())
        # Cada paso es independiente: un fallo deja el valor en "unknown" y añade un aviso.
        for label, step in (
            ("Versión de Windows", self._windows),
            ("Usuario con sesión", self._interactive_user),
            ("Disco, equipo, impresoras y actualizaciones", self._query_facts),
            ("Disco del sistema", self._disk),
            ("Tipo de equipo", self._chassis),
            ("Dominio", self._domain),
            ("Gestión empresarial (Entra ID / MDM)", self._mdm),
            ("Impresoras", self._printers),
            ("Unidades", self._drives),
            ("Windows Update", self._updates),
        ):
            progress(label)
            started = time.perf_counter()
            try:
                step(env)
            except (CommandError, OSError, ValueError, KeyError, TypeError) as exc:
                msg = f"{step.__name__.strip('_')}: {exc}"
                env.warnings.append(msg)
                log.warning("env_step_failed", extra={"step": step.__name__, "err": str(exc)})
            elapsed = int((time.perf_counter() - started) * 1000)
            self.timings[step.__name__.strip("_")] = elapsed
            log.info("env_step", extra={"step": step.__name__.strip("_"), "ms": elapsed})
        log.info("environment", extra={"env": env.to_dict(), "timings_ms": self.timings})
        return env

    # ------------------------------------------------------------------ pasos

    def _windows(self, env: EnvironmentInfo) -> None:
        def val(name: str) -> Any:
            v = self.registry.read("HKLM", _CURRENT_VERSION, name)
            return v.data if v else None

        env.build = int(val("CurrentBuildNumber") or val("CurrentBuild") or 0)
        env.ubr = int(val("UBR") or 0)
        env.display_version = str(val("DisplayVersion") or val("ReleaseId") or "")
        env.product_name = str(val("ProductName") or "")
        env.edition_id = str(val("EditionID") or "")
        env.edition = EDITION_MAP.get(env.edition_id, "unknown")
        if env.build and env.build < MIN_BUILD_WIN10:
            env.warnings.append(
                f"Build {env.build} no soportada (mínimo {MIN_BUILD_WIN10}, Windows 10 22H2). "
                "Actualiza Windows: hasta entonces SafeTrim solo puede simular."
            )
        if MIN_BUILD_WIN10 <= env.build < MIN_BUILD_WIN11:
            env.warnings.append(
                f"Windows 10 dejó de recibir parches de seguridad gratuitos el "
                f"{WIN10_END_OF_SUPPORT}. Mira en Diagnóstico si este equipo puede pasar a "
                "Windows 11."
            )
        if env.edition == "unknown":
            env.warnings.append(
                f"Edición no reconocida: {env.edition_id!r}. SafeTrim solo puede simular."
            )

    def _interactive_user(self, env: EnvironmentInfo) -> None:
        """El dueño de explorer.exe es el usuario con sesión; su SID se resuelve en _query_facts."""
        current = psutil.Process().username()
        env.elevated_user = current or ""
        owner = ""
        for proc in psutil.process_iter(["name", "username"]):
            if (proc.info.get("name") or "").lower() == "explorer.exe" and proc.info.get(
                "username"
            ):
                owner = proc.info["username"]
                break
        env.interactive_user = owner or current
        if owner and current and owner.lower() != current.lower():
            env.warnings.append(
                f"SafeTrim se ejecuta como {current} pero la sesión es de {owner}: "
                "los ajustes de usuario se aplicarán a la sesión de " + owner + "."
            )

    def _query_facts(self, env: EnvironmentInfo) -> None:
        env.system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        self.facts = {}
        data = self.runner.powershell_json(facts_script(env.interactive_user, env.system_drive))
        if not isinstance(data, dict):
            raise ValueError("respuesta vacía de PowerShell")
        self.facts = data
        sid = data.get("sid")
        env.interactive_sid = str(sid) if sid else None
        for key in ("sid", "disk", "chassis", "domain", "printers", "hotfix"):
            err = data.get(f"{key}_err")
            if err:
                log.warning("env_fact_failed", extra={"fact": key, "err": str(err)})

    def _fact(self, key: str) -> Any:
        err = self.facts.get(f"{key}_err")
        if err:
            raise ValueError(str(err))
        return self.facts.get(key)

    def _disk(self, env: EnvironmentInfo) -> None:
        data = self.facts.get("disk") if not self.facts.get("disk_err") else None
        media = str((data or {}).get("media", "")).upper()
        bus = str((data or {}).get("bus", "")).upper()
        if media == "SSD" or bus == "NVME":
            env.disk_type = "ssd"
        elif media == "HDD":
            env.disk_type = "hdd"
        else:
            env.disk_type = "unknown"
            env.warnings.append("No se pudo determinar si el disco del sistema es SSD o HDD.")

    def _chassis(self, env: EnvironmentInfo) -> None:
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        env.has_battery = battery is not None
        types = as_list(self.facts.get("chassis")) if not self.facts.get("chassis_err") else []
        is_laptop_chassis = any(int(t) in LAPTOP_CHASSIS_TYPES for t in types)
        env.chassis = "laptop" if (is_laptop_chassis or env.has_battery) else "desktop"
        self._fact("chassis")  # tras fijar el valor por batería: el error solo añade el aviso

    def _domain(self, env: EnvironmentInfo) -> None:
        data = self._fact("domain") or {}
        env.domain_joined = bool(data.get("part"))
        env.domain_name = str(data.get("domain", "")) if env.domain_joined else ""

    def _mdm(self, env: EnvironmentInfo) -> None:
        result = self.runner.run([resolve_exe("dsregcmd.exe"), "/status"])
        if not result.ok:
            return
        fields: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip().lower()] = value.strip().upper()
        env.entra_joined = fields.get("azureadjoined") == "YES"
        # MdmUrl solo aparece con valor si el equipo está inscrito en MDM (Intune u otro).
        env.mdm_enrolled = bool(fields.get("mdmurl"))

    def _printers(self, env: EnvironmentInfo) -> None:
        names = as_list(self._fact("printers"))
        env.printers = [
            str(n)
            for n in names
            if not any(m.lower() in str(n).lower() for m in VIRTUAL_PRINTER_MARKERS)
        ]

    def _drives(self, env: EnvironmentInfo) -> None:
        """Unidades fijas con letra (C:, D:...). psutil es instantáneo: sin PowerShell."""
        drives = []
        for part in psutil.disk_partitions(all=False):
            letter = part.mountpoint.rstrip("\\").upper()
            if "fixed" in part.opts.split(",") and len(letter) == 2 and letter.endswith(":"):
                drives.append(letter)
        env.fixed_drives = sorted(set(drives))

    def _updates(self, env: EnvironmentInfo) -> None:
        days = None if self.facts.get("hotfix_err") else self.facts.get("hotfix")
        status = update_status(self.registry, days)
        env.reboot_pending = status.reboot_pending
        env.last_update_days = status.last_update_days
        env.warnings.extend(status.warnings())


def facts_script(user: str, system_drive: str) -> str:
    """Un único script con todas las consultas lentas del arranque, cada una aislada.

    Las impresoras se leen por CIM con tiempo límite: Get-Printer puede quedarse colgado con una
    impresora de red apagada y arrastraría a todo el script.
    """
    letter = system_drive.rstrip(":\\") or "C"
    sid_part = (
        "$r.sid = (New-Object System.Security.Principal.NTAccount("
        f"{ps_quote(user)})).Translate([System.Security.Principal.SecurityIdentifier]).Value"
        if user
        else "$r.sid = $null"
    )
    parts = {
        "sid": sid_part,
        "disk": (
            f"$d = Get-Partition -DriveLetter {ps_quote(letter)} | Get-Disk;"
            "$p = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq [string]$d.Number };"
            "$r.disk = @{media=[string]$p.MediaType; bus=[string]$p.BusType}"
        ),
        "chassis": "$r.chassis = @((Get-CimInstance Win32_SystemEnclosure).ChassisTypes)",
        "domain": (
            "$c = Get-CimInstance Win32_ComputerSystem;"
            "$r.domain = @{part=[bool]$c.PartOfDomain; domain=[string]$c.Domain}"
        ),
        "printers": (
            "$r.printers = @(Get-CimInstance -ClassName Win32_Printer -OperationTimeoutSec 15"
            " | ForEach-Object { [string]$_.Name })"
        ),
        "hotfix": (
            "$h = Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending"
            " | Select-Object -First 1;"
            "$r.hotfix = if ($h) { [int]((Get-Date) - $h.InstalledOn).TotalDays } else { $null }"
        ),
    }
    body = "".join(
        f"try {{ {code} }} catch {{ $r.{key}_err = $_.Exception.Message }};"
        for key, code in parts.items()
    )
    return "$r = @{};" + body + "$r | ConvertTo-Json -Compress -Depth 4"


@dataclass
class UpdateStatus:
    reboot_pending: bool = False
    last_update_days: int | None = None

    @property
    def stale(self) -> bool:
        return self.last_update_days is not None and self.last_update_days > UPDATE_STALE_DAYS

    def warnings(self) -> list[str]:
        out = []
        if self.reboot_pending:
            out.append("Windows Update tiene un reinicio pendiente: reinicia antes de optimizar.")
        if self.stale:
            out.append(
                f"La última actualización de Windows se instaló hace {self.last_update_days} "
                "días: ejecuta Windows Update antes de optimizar."
            )
        return out


def update_status(registry: Registry, days: Any) -> UpdateStatus:
    status = UpdateStatus(
        reboot_pending=any(registry.key_exists("HKLM", key) for key in WU_REBOOT_KEYS)
    )
    if isinstance(days, int | float) and not isinstance(days, bool) and days >= 0:
        status.last_update_days = int(days)
    return status


def read_update_status(registry: Registry, runner: Runner) -> UpdateStatus:
    """Reinicio pendiente (claves del registro) y días desde la última actualización instalada.
    Para el Diagnóstico, que lo vuelve a consultar en el momento; el arranque usa facts_script."""
    try:
        days = runner.powershell_json(
            "$h = Get-HotFix | Where-Object InstalledOn | Sort-Object InstalledOn -Descending"
            " | Select-Object -First 1;"
            "$d = if ($h) { [int]((Get-Date) - $h.InstalledOn).TotalDays } else { $null };"
            "$d | ConvertTo-Json -Compress"
        )
    except CommandError as exc:
        log.warning("hotfix_query_failed", extra={"err": str(exc)})
        days = None
    return update_status(registry, days)
