"""Planes de energía (powercfg)."""

from __future__ import annotations

import re

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
        run_tool(ctx, "powercfg", ["/delete", created], "Eliminar el plan creado por SafeTrim")
    return True


def detect_scheme(ctx: HandlerContext) -> DetectResult:
    target = POWER_SCHEMES[ctx.params["scheme"]]
    active = _active_scheme(ctx)
    if active == target:
        return DetectResult(DetectState.APPLIED)
    return DetectResult(DetectState.NOT_APPLIED, f"Plan activo: {active}")


# --------------------------------------------------------------------------- con batería
# Valores "DC" (con batería) del plan activo. Con el cargador (AC) no cambia nada.

_HEX_RE = re.compile(r"0x([0-9a-fA-F]{8})")


def has_battery(ctx: HandlerContext) -> bool:
    return ctx.env.has_battery


def _dc_value(ctx: HandlerContext, sub: str, setting: str) -> int:
    """Valor DC actual. Los textos de `powercfg /q` están traducidos, pero los dos últimos
    números hexadecimales son siempre el índice AC y el DC, en ese orden."""
    result = ctx.runner.run(
        [str(ALLOWED_COMMAND_EXES["powercfg"]), "/q", "SCHEME_CURRENT", sub, setting]
    )
    values = _HEX_RE.findall(result.stdout)
    if not result.ok or len(values) < 2:
        raise HandlerError(f"No se pudo leer {sub}/{setting}: {result.error_text()}")
    return int(values[-1], 16)


def _set_dc(ctx: HandlerContext, scheme: str, sub: str, setting: str, value: int) -> None:
    label = ctx.params.get("label", f"{sub}/{setting}")
    run_tool(
        ctx,
        "powercfg",
        ["/setdcvalueindex", scheme, sub, setting, str(value)],
        f"Con batería: {label} = {value}",
    )
    # Sin volver a activar el plan, el cambio no se aplica hasta el siguiente cambio de plan.
    run_tool(ctx, "powercfg", ["/setactive", scheme], "Aplicar el plan de energía")


def set_dc_value(ctx: HandlerContext) -> bool:
    sub, setting, value = ctx.params["sub"], ctx.params["setting"], int(ctx.params["value"])
    current = _dc_value(ctx, sub, setting)
    if current == value:
        return False
    scheme = _active_scheme(ctx)
    _set_dc(ctx, scheme, sub, setting, value)
    if not ctx.dry_run:
        ctx.state.update(scheme=scheme, sub=sub, setting=setting, previous=current)
    return True


def restore_dc_value(ctx: HandlerContext) -> bool:
    prior = ctx.prior_state
    if "previous" not in prior:
        return False
    _set_dc(ctx, prior["scheme"], prior["sub"], prior["setting"], int(prior["previous"]))
    return True


def detect_dc_value(ctx: HandlerContext) -> DetectResult:
    current = _dc_value(ctx, ctx.params["sub"], ctx.params["setting"])
    if current == int(ctx.params["value"]):
        return DetectResult(DetectState.APPLIED)
    return DetectResult(DetectState.NOT_APPLIED, f"Con batería: {current}")
