"""Análisis rápido con Windows Defender, por si la lentitud viene de malware.

Usa el propio Defender (Start-MpScan): no instala nada ni sustituye al antivirus. Si hay otro
antivirus activo, Defender está en modo pasivo y se informa en lugar de analizar.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.logger import get_logger
from core.process import CommandError, Runner, as_list

log = get_logger("defender")

TIMEOUT_DEFENDER_SCAN = 1800  # un análisis rápido tarda 2-15 min según el equipo

_SCAN_SCRIPT = (
    "$s = Get-MpComputerStatus;"
    "if (-not $s.AntivirusEnabled -or $s.AMRunningMode -ne 'Normal') {"
    " @{enabled=$false; mode=[string]$s.AMRunningMode} | ConvertTo-Json -Compress"
    "} else {"
    " $start = Get-Date;"
    " Start-MpScan -ScanType QuickScan;"
    " $names = @(Get-MpThreatDetection | Where-Object { $_.InitialDetectionTime -ge $start }"
    " | ForEach-Object { (Get-MpThreat -ThreatID $_.ThreatID).ThreatName } | Sort-Object -Unique);"
    " @{enabled=$true; threats=$names; signature_age=[int]$s.AntivirusSignatureAge}"
    " | ConvertTo-Json -Compress"
    "}"
)


@dataclass
class ScanResult:
    ran: bool
    threats: list[str] = field(default_factory=list)
    signature_age: int | None = None  # días desde la última actualización de firmas
    message: str = ""


def quick_scan(runner: Runner) -> ScanResult:
    try:
        data = runner.powershell_json(_SCAN_SCRIPT, timeout=TIMEOUT_DEFENDER_SCAN)
    except CommandError as exc:
        log.warning("defender_scan_failed", extra={"err": str(exc)})
        return ScanResult(False, message=f"No se pudo ejecutar el análisis: {exc}")
    if not isinstance(data, dict):
        return ScanResult(False, message="Windows Defender no devolvió resultados.")
    if not data.get("enabled"):
        mode = str(data.get("mode") or "desconocido")
        return ScanResult(
            False,
            message="Windows Defender no es el antivirus activo (modo "
            f"“{mode}”): usa el análisis de tu antivirus.",
        )
    threats = [str(t) for t in as_list(data.get("threats")) if t]
    age = data.get("signature_age")
    result = ScanResult(True, threats, int(age) if isinstance(age, int | float) else None)
    if threats:
        result.message = (
            f"Windows Defender ha encontrado {len(threats)} amenaza(s): {', '.join(threats)}. "
            "Revisa “Seguridad de Windows → Protección contra virus” para ver qué hizo "
            "con ellas."
        )
    else:
        result.message = "Análisis rápido terminado: no se ha encontrado ninguna amenaza."
    if result.signature_age and result.signature_age > 7:
        result.message += (
            f" Ojo: las definiciones de virus tienen {result.signature_age} días; ejecuta "
            "Windows Update."
        )
    return result
