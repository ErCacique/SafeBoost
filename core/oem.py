"""Programas basura del fabricante y de prueba que traen los portátiles nuevos.

Lista curada por nombre (no por fabricante entero: las utilidades de teclas, audio o
controladores sí hacen falta). Se desinstalan con el desinstalador del propio programa, que el
usuario ve y confirma; no es reversible (se puede reinstalar desde la web del fabricante).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.programs import Program

# (patrón del nombre, motivo). Se comparan en minúsculas con búsqueda de subcadena/regex.
OEM_BLOAT: tuple[tuple[str, str], ...] = (
    (
        r"mcafee (livesafe|total protection|webadvisor|security scan)",
        "prueba de antivirus de McAfee",
    ),
    (r"norton (security|360|antivirus|safe web)", "prueba de antivirus de Norton"),
    (r"wildtangent", "juegos de prueba preinstalados"),
    (r"hp jumpstart", "asistente de bienvenida de HP"),
    (r"hp documentation", "manuales de HP (están en su web)"),
    (r"hp support assistant", "asistente de HP: mejor la web de drivers de tu modelo"),
    (r"hp insights|hp touchpoint analytics", "telemetría de HP"),
    (r"dell supportassist remediation", "recuperación de Dell que consume recursos"),
    (r"dell digital delivery", "descarga de software comprado con el equipo"),
    (r"lenovo vantage service|lenovo welcome", "asistentes de Lenovo"),
    (r"acer jumpstart|acer collection", "accesos y promociones de Acer"),
    (r"asus giftbox", "promociones de ASUS"),
    (r"expressvpn", "VPN de prueba preinstalada"),
    (r"booking\.com", "acceso promocional"),
    (r"dropbox (promotion|25 gb)", "promoción de Dropbox"),
    (r"cyberlink (power2go|powerdvd|youcam)", "software multimedia de prueba"),
)
_COMPILED = [(re.compile(p), why) for p, why in OEM_BLOAT]


@dataclass
class OemCandidate:
    program: Program
    reason: str


def find_oem_bloat(programs: list[Program]) -> list[OemCandidate]:
    out = []
    for program in programs:
        name = program.name.lower()
        for pattern, why in _COMPILED:
            if pattern.search(name) and program.uninstall_string:
                out.append(OemCandidate(program, why))
                break
    return out


def uninstall_command(program: Program) -> str:
    """Orden del desinstalador tal como la registra el programa (se ejecuta con cmd /c para
    respetar comillas y argumentos). MsiExec /I (reparar) se cambia por /X (desinstalar)."""
    command = program.uninstall_string.strip()
    if re.match(r"(?i)^msiexec(\.exe)?\s+/i", command):
        command = re.sub(r"(?i)/i", "/X", command, count=1)
    return command
