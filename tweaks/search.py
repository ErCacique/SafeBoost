"""Indexado de búsqueda por unidad.

Se usa Win32_Volume.IndexingEnabled, que es la casilla "Permitir que los archivos de esta
unidad tengan el contenido indizado". No se toca el servicio WSearch.
"""

from __future__ import annotations

from core.context import DetectResult, DetectState, HandlerContext, SkipOperation
from core.process import ps_quote
from tweaks._common import ps_json, ps_run


def _volumes(ctx: HandlerContext) -> list[dict]:
    """Volúmenes fijos con letra: [{letter: 'D:', indexing: bool}]."""
    return ps_json(
        ctx,
        "Get-CimInstance Win32_Volume | Where-Object { $_.DriveType -eq 3 -and $_.DriveLetter } "
        "| ForEach-Object { @{letter=$_.DriveLetter; indexing=[bool]$_.IndexingEnabled} } "
        "| ConvertTo-Json -Compress",
    )


def _targets(ctx: HandlerContext) -> list[dict]:
    selection = ctx.params.get("drives", "non_system")
    system = ctx.env.system_drive.upper()
    volumes = _volumes(ctx)
    if selection == "non_system":
        return [v for v in volumes if str(v["letter"]).upper() != system]
    wanted = {str(d).upper().rstrip("\\") for d in selection}
    return [v for v in volumes if str(v["letter"]).upper() in wanted]


def _set(ctx: HandlerContext, letter: str, enabled: bool) -> None:
    flag = "$true" if enabled else "$false"
    ps_run(
        ctx,
        f'Get-CimInstance Win32_Volume -Filter ("DriveLetter=\'" + {ps_quote(letter)} + "\'") | '
        f"Set-CimInstance -Property @{{IndexingEnabled={flag}}}",
        f"Indexado de {letter}: {'activado' if enabled else 'desactivado'}",
    )


def disable_indexing(ctx: HandlerContext) -> bool:
    targets = _targets(ctx)
    if not targets:
        raise SkipOperation("No hay unidades seleccionadas (solo existe la unidad del sistema)")
    previous = {}
    for volume in targets:
        if volume["indexing"]:
            _set(ctx, volume["letter"], False)
            previous[volume["letter"]] = True
    if previous and not ctx.dry_run:
        ctx.state["previous"] = previous
    return bool(previous)


def restore_indexing(ctx: HandlerContext) -> bool:
    previous: dict[str, bool] = ctx.prior_state.get("previous") or {}
    for letter, enabled in previous.items():
        _set(ctx, letter, enabled)
    return bool(previous)


def detect_indexing(ctx: HandlerContext) -> DetectResult:
    targets = _targets(ctx)
    if not targets:
        return DetectResult(DetectState.NOT_APPLICABLE, "Solo existe la unidad del sistema")
    off = [v for v in targets if not v["indexing"]]
    letters = ", ".join(v["letter"] for v in targets)
    if len(off) == len(targets):
        return DetectResult(DetectState.APPLIED, letters)
    if off:
        return DetectResult(DetectState.PARTIAL, letters)
    return DetectResult(DetectState.NOT_APPLIED, letters)
