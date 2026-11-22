"""Estado de seguridad del equipo y datos del modelo, en una consulta de PowerShell. Solo lee.

Defender (antivirus, protección en tiempo real, definiciones), firewall por perfil, activación de
Windows, UAC (registro), BitLocker de la unidad del sistema y, para la página de soporte,
fabricante, modelo y número de serie.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.environment import EnvironmentInfo
from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote
from core.registry import Registry

log = get_logger("security")

UAC_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"
WINDOWS_APP_ID = "55c92734-d682-4d71-983e-d6ec3f16059f"
SIGNATURE_STALE_DAYS = 7


def _script(drive: str) -> str:
    letter = ps_quote(drive.rstrip("\\"))
    return (
        "$r = @{};"
        "try { $m = Get-MpComputerStatus -ErrorAction Stop; $r.defender = @{"
        "av=[bool]$m.AntivirusEnabled; rt=[bool]$m.RealTimeProtectionEnabled;"
        " age=[int]$m.AntivirusSignatureAge; mode=[string]$m.AMRunningMode} } catch {};"
        "try { $r.firewall = @(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object {"
        " @{name=[string]$_.Name; on=[bool]$_.Enabled} }) } catch {};"
        "try { $l = Get-CimInstance SoftwareLicensingProduct -Filter"
        f" \"ApplicationID='{WINDOWS_APP_ID}' AND PartialProductKey IS NOT NULL\""
        " -ErrorAction Stop | Select-Object -First 1;"
        " $r.license = [int]$l.LicenseStatus } catch {};"
        f"try {{ $b = Get-BitLockerVolume -MountPoint {letter} -ErrorAction Stop;"
        " $r.bitlocker = [string]$b.ProtectionStatus } catch {};"
        "try { $c = Get-CimInstance Win32_ComputerSystem; $s = Get-CimInstance Win32_BIOS;"
        " $r.system = @{maker=[string]$c.Manufacturer; model=[string]$c.Model;"
        " serial=[string]$s.SerialNumber} } catch {};"
        "$r | ConvertTo-Json -Compress -Depth 4"
    )


@dataclass
class SecurityCheck:
    name: str
    ok: bool | None  # None = no se pudo comprobar o no aplica
    detail: str
    critical: bool = False  # si falla, aparece como hallazgo grave


@dataclass
class SystemModel:
    manufacturer: str = ""
    model: str = ""
    serial: str = ""


@dataclass
class SecurityReport:
    checks: list[SecurityCheck] = field(default_factory=list)
    system: SystemModel = field(default_factory=SystemModel)

    @property
    def problems(self) -> list[SecurityCheck]:
        return [c for c in self.checks if c.ok is False]


def evaluate(
    data: dict, uac: tuple[int | None, int | None], env: EnvironmentInfo
) -> SecurityReport:
    """Convierte los datos en comprobaciones legibles. Función pura."""
    report = SecurityReport()
    checks = report.checks
    defender = data.get("defender")
    if isinstance(defender, dict):
        passive = str(defender.get("mode", "")).lower() not in ("", "normal")
        if passive:
            checks.append(
                SecurityCheck(
                    "Antivirus",
                    None,
                    "Defender está en modo pasivo: otro antivirus "
                    "protege el equipo (compruébalo en Seguridad de Windows).",
                )
            )
        else:
            on = bool(defender.get("av")) and bool(defender.get("rt"))
            age = defender.get("age")
            checks.append(
                SecurityCheck(
                    "Antivirus (Windows Defender)",
                    on,
                    "activo, protección en tiempo real" if on else "DESACTIVADO o sin tiempo real",
                    critical=True,
                )
            )
            if isinstance(age, int):
                checks.append(
                    SecurityCheck(
                        "Definiciones de virus",
                        age <= SIGNATURE_STALE_DAYS,
                        f"actualizadas hace {age} días",
                    )
                )
    else:
        checks.append(SecurityCheck("Antivirus", None, "no se pudo consultar"))
    profiles = [p for p in as_list(data.get("firewall")) if isinstance(p, dict)]
    if profiles:
        off = [str(p.get("name")) for p in profiles if not p.get("on")]
        checks.append(
            SecurityCheck(
                "Firewall",
                not off,
                "activo en todos los perfiles" if not off else f"desactivado en: {', '.join(off)}",
                critical=True,
            )
        )
    license_status = data.get("license")
    if isinstance(license_status, int):
        checks.append(
            SecurityCheck(
                "Windows activado",
                license_status == 1,
                "sí" if license_status == 1 else "no: algunas funciones y avisos dependen de ello",
            )
        )
    enable_lua, consent = uac
    if enable_lua is not None:
        if enable_lua == 0:
            checks.append(
                SecurityCheck("Control de cuentas (UAC)", False, "desactivado", critical=True)
            )
        else:
            silent = consent == 0
            checks.append(
                SecurityCheck(
                    "Control de cuentas (UAC)",
                    not silent,
                    "eleva sin preguntar" if silent else "activado",
                )
            )
    bitlocker = data.get("bitlocker")
    if bitlocker is not None:
        on = str(bitlocker).lower() in ("on", "1")
        checks.append(
            SecurityCheck(
                "Cifrado del disco (BitLocker)",
                True if on else None,
                "activado" if on else "no activado (recomendable en portátiles que salen de casa)",
            )
        )
    if env.reboot_pending:
        checks.append(SecurityCheck("Actualizaciones", False, "reinicio pendiente"))
    elif env.last_update_days is not None:
        recent = env.last_update_days <= 60
        checks.append(
            SecurityCheck(
                "Actualizaciones", recent, f"última instalada hace {env.last_update_days} días"
            )
        )
    system = data.get("system")
    if isinstance(system, dict):
        report.system = SystemModel(
            str(system.get("maker") or "").strip(),
            str(system.get("model") or "").strip(),
            str(system.get("serial") or "").strip(),
        )
    return report


def read_security(registry: Registry, runner: Runner, env: EnvironmentInfo) -> SecurityReport:
    try:
        data = runner.powershell_json(_script(env.system_drive))
    except CommandError as exc:
        log.warning("security_query_failed", extra={"err": str(exc)})
        data = None
    lua = registry.read("HKLM", UAC_KEY, "EnableLUA")
    consent = registry.read("HKLM", UAC_KEY, "ConsentPromptBehaviorAdmin")
    uac = (
        int(str(lua.data)) if lua and lua.data is not None else None,
        int(str(consent.data)) if consent and consent.data is not None else None,
    )
    return evaluate(data if isinstance(data, dict) else {}, uac, env)
