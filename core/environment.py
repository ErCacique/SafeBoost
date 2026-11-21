"""Detección del entorno: versión/edición de Windows, disco, chasis, dominio/MDM, impresoras."""

from __future__ import annotations

import ctypes
import os
import sys
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


class EnvironmentDetector:
    def __init__(self, registry: Registry, runner: Runner) -> None:
        self.registry = registry
        self.runner = runner

    def detect(self) -> EnvironmentInfo:
        env = EnvironmentInfo(is_admin=is_admin())
        # Cada paso es independiente: un fallo deja el valor en "unknown" y añade un aviso.
        for step in (
            self._windows,
            self._interactive_user,
            self._disk,
            self._chassis,
            self._domain,
            self._mdm,
            self._printers,
            self._drives,
            self._updates,
        ):
            try:
                step(env)
            except (CommandError, OSError, ValueError, KeyError, TypeError) as exc:
                msg = f"{step.__name__.strip('_')}: {exc}"
                env.warnings.append(msg)
                log.warning("env_step_failed", extra={"step": step.__name__, "err": str(exc)})
        log.info("environment", extra={"env": env.to_dict()})
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
        """El dueño de explorer.exe es el usuario con sesión; su SID permite escribir en HKU."""
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
        if not env.interactive_user:
            return
        sid = self.runner.powershell_json(
            "(New-Object System.Security.Principal.NTAccount("
            f"{ps_quote(env.interactive_user)})).Translate("
            "[System.Security.Principal.SecurityIdentifier]).Value | ConvertTo-Json"
        )
        env.interactive_sid = str(sid) if sid else None
        if owner and current and owner.lower() != current.lower():
            env.warnings.append(
                f"SafeTrim se ejecuta como {current} pero la sesión es de {owner}: "
                "los ajustes de usuario se aplicarán a la sesión de " + owner + "."
            )

    def _disk(self, env: EnvironmentInfo) -> None:
        env.system_drive = os.environ.get("SYSTEMDRIVE", "C:")
        letter = env.system_drive.rstrip(":\\")
        data = self.runner.powershell_json(
            f"$d = Get-Partition -DriveLetter {ps_quote(letter)} | Get-Disk;"
            "$p = Get-PhysicalDisk | Where-Object { $_.DeviceId -eq [string]$d.Number };"
            "@{media=[string]$p.MediaType; bus=[string]$p.BusType} | ConvertTo-Json -Compress"
        )
        media = (data or {}).get("media", "").upper()
        bus = (data or {}).get("bus", "").upper()
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
        types = as_list(
            self.runner.powershell_json(
                "(Get-CimInstance Win32_SystemEnclosure).ChassisTypes | ConvertTo-Json -Compress"
            )
        )
        is_laptop_chassis = any(int(t) in LAPTOP_CHASSIS_TYPES for t in types)
        env.chassis = "laptop" if (is_laptop_chassis or env.has_battery) else "desktop"

    def _domain(self, env: EnvironmentInfo) -> None:
        data = (
            self.runner.powershell_json(
                "$c = Get-CimInstance Win32_ComputerSystem;"
                "@{part=[bool]$c.PartOfDomain; domain=[string]$c.Domain} | ConvertTo-Json -Compress"
            )
            or {}
        )
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
        names = as_list(
            self.runner.powershell_json(
                "@(Get-Printer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)"
                " | ConvertTo-Json -Compress"
            )
        )
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
        status = read_update_status(self.registry, self.runner)
        env.reboot_pending = status.reboot_pending
        env.last_update_days = status.last_update_days
        env.warnings.extend(status.warnings())


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


def read_update_status(registry: Registry, runner: Runner) -> UpdateStatus:
    """Reinicio pendiente (claves del registro) y días desde la última actualización instalada."""
    status = UpdateStatus(
        reboot_pending=any(registry.key_exists("HKLM", key) for key in WU_REBOOT_KEYS)
    )
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
    if isinstance(days, int | float) and days >= 0:
        status.last_update_days = int(days)
    return status
