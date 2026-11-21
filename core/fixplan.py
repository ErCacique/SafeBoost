""" "Arreglar mi PC lento": del diagnóstico a un plan concreto y revisable.

No aplica nada por su cuenta: prepara una selección (perfil recomendado + limpieza segura) y
señala los programas de inicio y los consejos de hardware. El usuario simula y confirma como
siempre. Sustituye al "perfil para equipos antiguos": con poca RAM el perfil recomendado ya
incluye los navegadores en segundo plano y aquí se suma la limpieza.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.diagnostics import DiagnosticReport

FIX_CLEANUPS = ("cleanup.temp_user", "cleanup.temp_windows", "cleanup.thumbnails")
HARDWARE_TITLES = {
    "Poca memoria RAM",
    "El disco puede estar fallando",
    "SSD desgastado",
    "Disco muy caliente",
    "Disco mecánico (HDD)",
    "Procesador frenado",
    "Batería muy gastada",
    "Poco espacio en disco",
}


@dataclass
class StartupCandidate:
    name: str
    reason: str


@dataclass
class FixPlan:
    level: int | None  # None: no se recomienda aplicar perfiles (Windows no soportado, reinicio…)
    why: str
    cleanups: list[str] = field(default_factory=list)
    startup: list[StartupCandidate] = field(default_factory=list)
    hardware: list[str] = field(default_factory=list)
    first: list[str] = field(default_factory=list)  # lo que conviene hacer antes de nada

    @property
    def has_actions(self) -> bool:
        return self.level is not None or bool(self.cleanups)


def build_plan(
    report: DiagnosticReport,
    recommendation: tuple[int | None, str],
    startup: list[tuple[str, str, str]],
    available_cleanups: list[str],
) -> FixPlan:
    """`startup`: (nombre, archivo, impacto) de los programas de inicio activos."""
    level, why = recommendation
    plan = FixPlan(level, why, cleanups=[c for c in FIX_CLEANUPS if c in available_cleanups])
    if report.updates.reboot_pending:
        plan.first.append("Reinicia el equipo: Windows Update tiene un reinicio pendiente.")
    elif report.updates.stale:
        plan.first.append("Ejecuta Windows Update hasta que diga “Estás al día”.")
    culprits = {c.file.lower(): c for c in report.boot.culprits if c.kind == "programa" and c.file}
    for name, file, impact in startup:
        culprit = culprits.get(file.lower())
        if culprit:
            plan.startup.append(
                StartupCandidate(name, f"retrasa el arranque unos {culprit.avg_ms / 1000:.0f} s")
            )
        elif impact == "alto":
            plan.startup.append(StartupCandidate(name, "impacto alto en el arranque"))
    plan.hardware = [
        f"{f.title}: {f.detail}" for f in report.findings if f.title in HARDWARE_TITLES
    ]
    return plan
