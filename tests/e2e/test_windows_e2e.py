"""Extremo a extremo sobre Windows REAL: aplica tweaks de verdad y los revierte.

Modifica el sistema (registro, servicios, tareas, plan de energía, red). Solo se ejecuta si:
  - el sistema es Windows,
  - el proceso es administrador,
  - SAFETRIM_E2E=1 (lo define el job "e2e" de CI, que corre en una VM desechable).
Nunca lo ejecutes en tu equipo.

Quedan fuera los tweaks que no tienen sentido o no son reversibles en un runner de Windows
Server: apps AppX (no vienen en Server), limpieza (irreversible), DNS (podría cortar la red
del runner), memoria virtual e hibernación (requieren reinicio), HAGS (sin GPU) y
mitigaciones de CPU (riesgo alto).
"""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform != "win32", reason="requiere Windows"),
    pytest.mark.skipif(os.environ.get("SAFETRIM_E2E") != "1", reason="requiere SAFETRIM_E2E=1"),
]

EXCLUDED_CATEGORIES = {"bloatware", "cleanup"}
EXCLUDED_IDS = {
    "network.dns",
    "memory.pagefile_fixed",
    "memory.pagefile_system_managed",
    "power.hibernate_off",
    "power.ultimate_performance",
    "gaming.hags",
    "security.cpu_mitigations_off",
}


def _report(title: str, results: dict) -> str:
    lines = [title]
    for tid, r in sorted(results.items()):
        extra = f" | {'; '.join(r.details[:4])}" if r.details else ""
        lines.append(f"  [{r.status}] {tid}: {r.message}{extra}")
    return "\n".join(lines)


def test_apply_and_revert_on_real_windows() -> None:
    from core.app import build_context
    from core.context import DetectState
    from core.environment import is_admin
    from core.settings import Settings

    assert is_admin(), "el job e2e debe ejecutarse como administrador"
    settings = Settings(
        dry_run=False,
        # Windows Server (runner) no tiene Restaurar sistema.
        allow_without_restore_point=True,
        export_reg_backups=True,
        measure_boot_after_reboot=False,
        # El runner es Windows Server: edición no reconocida, que la app bloquearía.
        allow_unsupported_os=True,
    )
    app = build_context(settings=settings)
    engine = app.engine
    print(
        f"\nEntorno: {app.env.os_label} · edición {app.env.edition_id} · "
        f"disco {app.env.disk_type} · {app.env.chassis} · avisos: {app.env.warnings}"
    )

    ids = [
        t.id
        for t in engine.catalog.tweaks
        if t.category not in EXCLUDED_CATEGORIES
        and t.id not in EXCLUDED_IDS
        and not t.is_action
        and engine.evaluate(t).applicable
    ]
    assert len(ids) >= 20, f"demasiado pocos tweaks aplicables en el runner: {ids}"

    session = engine.apply(ids)
    print(_report("APLICAR", session.results))
    broken = {t: r for t, r in session.results.items() if r.status in ("failed", "partial")}
    assert not broken, _report("Fallos al aplicar", broken)
    applied = [t for t, r in session.results.items() if r.status == "applied"]
    assert len(applied) >= 10, "se esperaba aplicar al menos 10 tweaks en un Windows limpio"

    not_applied = {}
    for tid in applied:
        state = engine.detect(engine.catalog.get(tid)).state
        if state not in (DetectState.APPLIED, DetectState.UNKNOWN):
            not_applied[tid] = state
    assert not not_applied, f"aplicados pero la detección no lo confirma: {not_applied}"

    revert = engine.revert(session.id)
    print(_report("DESHACER", revert.results))
    bad = {
        t: r for t, r in revert.results.items() if r.status != "reverted" or r.verified is not True
    }
    assert not bad, _report("Reversión incompleta o no verificada", bad)
    assert not engine.drift(), "tras deshacer no debería quedar deriva"
