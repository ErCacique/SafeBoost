"""Planes de energía (powercfg)."""

from __future__ import annotations

from core.constants import ALLOWED_COMMAND_EXES, POWER_SCHEMES
from core.context import DetectResult, DetectState, HandlerContext, HandlerError
from tweaks._common import GUID_RE, run_tool


def _active_scheme(ctx: HandlerContext) -> str:
    # La salida de powercfg está localizada, pero el GUID es siempre el mismo.
    result = ctx.runner.run([str(ALLOWED_COMMAND_EXES["powercfg"]), "/getactivescheme"])
    match = GUID_RE.search(result.stdout)
    if not result.ok or not match:
        raise HandlerError(f"No se pudo leer el plan activo: {result.error_text()}")
    return match.group(0).lower()


def _schemes(ctx: HandlerContext) -> set[str]:
    result = ctx.runner.run([str(ALLOWED_COMMAND_EXES["powercfg"]), "/list"])
    if not result.ok:
        raise HandlerError(f"powercfg /list: {result.error_text()}")
    return {m.lower() for m in GUID_RE.findall(result.stdout)}


def set_scheme(ctx: HandlerContext) -> bool:
    name = ctx.params["scheme"]
    target = POWER_SCHEMES[name]
    active = _active_scheme(ctx)
    if active == target:
        return False
    created = False
    if target not in _schemes(ctx):
        # Se duplica sobre el MISMO GUID canónico para que la detección sea por GUID y para
        # que no se acumulen copias si se aplica varias veces.
        run_tool(ctx, "powercfg", ["/duplicatescheme", target, target], f"Crear plan {name}")
        created = True
    run_tool(ctx, "powercfg", ["/setactive", target], f"Activar plan de energía {name}")
    if not ctx.dry_run:
        ctx.state.update(previous=active, created=target if created else None)
    return True


def restore_scheme(ctx: HandlerContext) -> bool:
    previous = ctx.prior_state.get("previous")
    created = ctx.prior_state.get("created")
    if not previous:
        return False
    run_tool(ctx, "powercfg", ["/setactive", previous], "Restaurar el plan de energía anterior")
    if created:
        run_tool(ctx, "powercfg", ["/delete", created], "Eliminar el plan creado por WinTune")
    return True


def detect_scheme(ctx: HandlerContext) -> DetectResult:
    target = POWER_SCHEMES[ctx.params["scheme"]]
    active = _active_scheme(ctx)
    if active == target:
        return DetectResult(DetectState.APPLIED)
    return DetectResult(DetectState.NOT_APPLIED, f"Plan activo: {active}")
