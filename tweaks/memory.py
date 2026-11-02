"""Memoria virtual (archivo de paginación) vía CIM."""

from __future__ import annotations

import psutil

from core.context import DetectResult, DetectState, HandlerContext, HandlerError
from core.process import ps_quote
from tweaks._common import ps_json, ps_run

MIB = 1024 * 1024


def _read(ctx: HandlerContext) -> dict:
    rows = ps_json(
        ctx,
        "$cs = Get-CimInstance Win32_ComputerSystem;"
        "$s = @(Get-CimInstance Win32_PageFileSetting | ForEach-Object "
        "{ @{name=$_.Name; initial=[int]$_.InitialSize; maximum=[int]$_.MaximumSize} });"
        "@{auto=[bool]$cs.AutomaticManagedPagefile; settings=$s} "
        "| ConvertTo-Json -Depth 3 -Compress",
    )
    if not rows:
        raise HandlerError("No se pudo leer la configuración del archivo de paginación")
    data = rows[0]
    settings = data.get("settings") or []
    data["settings"] = settings if isinstance(settings, list) else [settings]
    return data


def _set_auto(ctx: HandlerContext, enabled: bool) -> None:
    flag = "$true" if enabled else "$false"
    ps_run(
        ctx,
        "$cs = Get-CimInstance Win32_ComputerSystem;"
        f"Set-CimInstance -InputObject $cs -Property @{{AutomaticManagedPagefile={flag}}}",
        "Archivo de paginación: " + ("gestionado por el sistema" if enabled else "manual"),
    )


def _replace_settings(ctx: HandlerContext, settings: list[dict]) -> None:
    """Sustituye todas las entradas Win32_PageFileSetting por las indicadas."""
    script = "Get-CimInstance Win32_PageFileSetting | Remove-CimInstance;"
    for s in settings:
        script += (
            "New-CimInstance -ClassName Win32_PageFileSetting -Property "
            f"@{{Name={ps_quote(s['name'])}; InitialSize=[uint32]{int(s['initial'])}; "
            f"MaximumSize=[uint32]{int(s['maximum'])}}} | Out-Null;"
        )
    desc = ", ".join(f"{s['name']} {s['initial']}-{s['maximum']} MB" for s in settings) or "ninguno"
    ps_run(ctx, script, f"Configurar archivos de paginación: {desc}")


def set_system_managed(ctx: HandlerContext) -> bool:
    current = _read(ctx)
    if current.get("auto"):
        return False
    _set_auto(ctx, True)
    if not ctx.dry_run:
        ctx.state["previous"] = current
    return True


def detect_system_managed(ctx: HandlerContext) -> DetectResult:
    current = _read(ctx)
    if current.get("auto"):
        return DetectResult(DetectState.APPLIED)
    return DetectResult(
        DetectState.NOT_APPLIED, f"{len(current['settings'])} archivo(s) manual(es)"
    )


def _target_size(ctx: HandlerContext) -> int:
    raw = ctx.params.get("size_mb", "ram_x1_5")
    minimum = int(ctx.tweak.params.get("size_mb", {}).get("min", 4096))
    # "ram_x1_5": 1,5 veces la RAM física, el tamaño inicial que usa Windows por defecto.
    size = int(psutil.virtual_memory().total * 1.5 // MIB) if raw == "ram_x1_5" else int(raw)
    if size < minimum:
        raise HandlerError(f"Tamaño {size} MB por debajo del mínimo seguro ({minimum} MB)")
    return size


def set_fixed(ctx: HandlerContext) -> bool:
    size = _target_size(ctx)
    current = _read(ctx)
    letter = ctx.env.system_drive.rstrip(":\\")
    name = f"{letter}:\\pagefile.sys"
    target = [{"name": name, "initial": size, "maximum": size}]
    if not current.get("auto") and current["settings"] == target:
        return False
    _set_auto(ctx, False)
    _replace_settings(ctx, target)
    if not ctx.dry_run:
        ctx.state["previous"] = current
    return True


def detect_fixed(ctx: HandlerContext) -> DetectResult:
    current = _read(ctx)
    fixed = [s for s in current["settings"] if s["initial"] and s["initial"] == s["maximum"]]
    if not current.get("auto") and fixed:
        return DetectResult(DetectState.APPLIED, f"{fixed[0]['initial']} MB")
    return DetectResult(DetectState.NOT_APPLIED)


def restore_pagefile(ctx: HandlerContext) -> bool:
    previous = ctx.prior_state.get("previous")
    if not previous:
        return False
    if previous.get("auto"):
        _set_auto(ctx, True)
    else:
        _set_auto(ctx, False)
        _replace_settings(ctx, previous.get("settings") or [])
    return True
