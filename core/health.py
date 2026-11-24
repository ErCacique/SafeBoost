"""Nota de salud del equipo (0-100) y la frase que la explica, para el Inicio del modo Fácil.

Es una función pura sobre las medidas que ya toma el diagnóstico: no mide nada nuevo. Parte de 100
y resta por cada problema según cuánto se nota al usar el equipo. No compara con otros equipos:
un portátil modesto bien cuidado puede sacar un 90.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from core.i18n import _

if TYPE_CHECKING:
    from core.diagnostics import DiagnosticReport

Tone = Literal["ok", "warning", "critical"]

# Umbrales (segundos de arranque, GiB de RAM, % de uso, % de disco libre).
BOOT_SLOW_S = 90
BOOT_MEH_S = 60
BOOT_OK_S = 40
RAM_LOW_GIB = 5
RAM_PRESSURE_PCT = 85
RAM_BUSY_PCT = 75
DISK_LOW_PCT = 10
DISK_MEH_PCT = 20


@dataclass
class HealthInputs:
    boot_s: float | None = None
    ram_gib: float = 0.0
    ram_percent: float = 0.0
    disk_free_pct: float = 100.0
    hdd: bool = False
    security_problems: list[str] = field(default_factory=list)  # solo los críticos
    reboot_pending: bool = False
    updates_stale: bool = False


@dataclass
class Health:
    score: int
    tone: Tone
    label: str  # BIEN / MEJORABLE / NECESITA AYUDA
    headline: str
    detail: str
    issues: list[str]


def assess(data: HealthInputs) -> Health:
    score = 100
    issues: list[tuple[int, str]] = []  # (peso, frase corta para el titular)

    def hit(points: int, phrase: str) -> None:
        nonlocal score
        score -= points
        issues.append((points, phrase))

    for name in data.security_problems:
        hit(15, _("tiene un problema de seguridad ({name})", name=name.lower()))
    if data.boot_s is not None:
        secs = round(data.boot_s)
        if data.boot_s > BOOT_SLOW_S:
            minutes = round(data.boot_s / 60)
            hit(
                25,
                _("tarda {m} minutos en arrancar", m=minutes)
                if minutes >= 2
                else _("tarda {s} s en arrancar", s=secs),
            )
        elif data.boot_s > BOOT_MEH_S:
            hit(15, _("tarda {s} s en arrancar", s=secs))
        elif data.boot_s > BOOT_OK_S:
            hit(7, _("tarda {s} s en arrancar", s=secs))
    if 0 < data.ram_gib < RAM_LOW_GIB:
        hit(15, _("se queda sin memoria"))
    elif data.ram_percent >= RAM_PRESSURE_PCT:
        hit(10, _("tiene la memoria casi llena"))
    elif data.ram_percent >= RAM_BUSY_PCT:
        hit(5, _("tiene la memoria muy ocupada"))
    if data.disk_free_pct < DISK_LOW_PCT:
        hit(15, _("se está quedando sin espacio"))
    elif data.disk_free_pct < DISK_MEH_PCT:
        hit(7, _("tiene poco espacio libre"))
    if data.hdd:
        hit(5, _("usa un disco mecánico lento"))
    if data.reboot_pending:
        hit(5, _("tiene un reinicio pendiente"))
    elif data.updates_stale:
        hit(8, _("lleva tiempo sin actualizarse"))

    score = max(0, min(100, score))
    issues.sort(key=lambda item: -item[0])
    phrases = [phrase for _w, phrase in issues]
    if score >= 80:
        tone: Tone = "ok"
        label = _("BIEN")
    elif score >= 55:
        tone, label = "warning", _("MEJORABLE")
    else:
        tone, label = "critical", _("NECESITA AYUDA")
    if not phrases:
        headline = _("Tu PC está en buena forma")
        detail = _(
            "No hay nada importante que arreglar. "
            "Puedes revisarlo de nuevo cuando notes que va lento."
        )
    elif tone == "ok":
        # Nota alta con algún detalle: el titular no debe sonar a problema.
        headline = _("Tu PC está en buena forma")
        detail = _("Solo un detalle: {what}.", what=phrases[0])
    else:
        main = phrases[0] if len(phrases) == 1 else _("{a} y {b}", a=phrases[0], b=phrases[1])
        headline = _("Tu PC {what}", what=main)
        detail = _(
            "Arreglarlo es seguro: SafeBoost te enseña el plan antes y todo se puede deshacer."
        )
    return Health(score, tone, label, headline, detail, phrases)


def from_report(report: DiagnosticReport, boot_ms: int | None) -> Health:
    """Construye la nota a partir de un informe del diagnóstico y del último arranque medido."""
    snap = report.snapshot
    disk_total = snap.disk_total or 0
    return assess(
        HealthInputs(
            boot_s=boot_ms / 1000 if boot_ms else None,
            ram_gib=report.ram_installed / 1024**3,
            ram_percent=snap.ram_percent,
            disk_free_pct=snap.disk_free / disk_total * 100 if disk_total else 100.0,
            hdd=report.env.disk_type == "hdd",
            security_problems=[c.name for c in report.security.problems if c.critical],
            reboot_pending=report.updates.reboot_pending,
            updates_stale=report.updates.stale,
        )
    )
