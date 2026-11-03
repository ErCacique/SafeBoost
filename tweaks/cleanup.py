"""Acciones de limpieza (irreversibles). Cada clean_* tiene su estimate_* para el detector."""

from __future__ import annotations

import ctypes
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import psutil

from core.constants import (
    CLEAN_NEGLIGIBLE_BYTES,
    CLEAN_PREFETCH_MIN_AGE_DAYS,
    CLEAN_TEMP_MIN_AGE_HOURS,
    CLEAN_WU_MIN_AGE_DAYS,
    SYSTEM_ROOT,
)
from core.context import DetectResult, DetectState, HandlerContext, SkipOperation
from core.logger import get_logger
from core.metrics import human_bytes
from tweaks._common import user_local_appdata

log = get_logger("tweaks.cleanup")

HOUR = 3600
DAY = 24 * HOUR


@dataclass
class Target:
    """Qué borrar: raíz, patrón glob, antigüedad mínima y si se recorre recursivamente."""

    root: Path
    pattern: str = "*"
    min_age_seconds: float = 0
    recursive: bool = True
    keep: tuple[str, ...] = ("desktop.ini",)


@dataclass
class Tally:
    files: int = 0
    bytes: int = 0
    skipped: int = 0


def _iter_candidates(target: Target, now: float) -> Iterator[Path]:
    if not target.root.exists():
        return
    iterator = (
        target.root.rglob(target.pattern) if target.recursive else target.root.glob(target.pattern)
    )
    for path in iterator:
        try:
            if not path.is_file() or path.is_symlink() or path.name.lower() in target.keep:
                continue
            if now - path.stat().st_mtime < target.min_age_seconds:
                continue
        except OSError:
            continue
        yield path


def _measure(targets: list[Target]) -> Tally:
    tally = Tally()
    now = time.time()
    for target in targets:
        for path in _iter_candidates(target, now):
            try:
                tally.bytes += path.stat().st_size
                tally.files += 1
            except OSError:
                tally.skipped += 1
    return tally


def _delete(targets: list[Target]) -> Tally:
    tally = Tally()
    now = time.time()
    for target in targets:
        for path in _iter_candidates(target, now):
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                # Archivo en uso o sin permisos: se omite, no es un error de la acción.
                tally.skipped += 1
                continue
            tally.files += 1
            tally.bytes += size
        if target.recursive:
            _remove_empty_dirs(target.root)
    return tally


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            continue


def _run_clean(ctx: HandlerContext, label: str, targets: list[Target]) -> bool:
    if ctx.dry_run:
        tally = _measure(targets)
        if tally.files == 0:
            raise SkipOperation(f"{label}: nada que limpiar")
        ctx.plan(f"Borrar {tally.files} archivos de {label} ({human_bytes(tally.bytes)})")
        return True
    tally = _delete(targets)
    ctx.state["freed_bytes"] = ctx.state.get("freed_bytes", 0) + tally.bytes
    ctx.note(
        f"{label}: {tally.files} archivos borrados, {human_bytes(tally.bytes)} liberados"
        + (f", {tally.skipped} en uso omitidos" if tally.skipped else "")
    )
    ctx.record("handler", {"action": label}, None, {"files": tally.files, "bytes": tally.bytes})
    return tally.files > 0


def _estimate(targets: list[Target]) -> DetectResult:
    tally = _measure(targets)
    state = DetectState.NOT_APPLIED if tally.bytes > CLEAN_NEGLIGIBLE_BYTES else DetectState.APPLIED
    return DetectResult(
        state,
        f"{human_bytes(tally.bytes)} en {tally.files} archivos",
        {"bytes": tally.bytes, "files": tally.files},
    )


# --------------------------------------------------------------------------- objetivos


def _temp_user(ctx: HandlerContext) -> list[Target]:
    return [
        Target(user_local_appdata(ctx) / "Temp", min_age_seconds=CLEAN_TEMP_MIN_AGE_HOURS * HOUR)
    ]


def _temp_windows(_ctx: HandlerContext) -> list[Target]:
    return [Target(SYSTEM_ROOT / "Temp", min_age_seconds=CLEAN_TEMP_MIN_AGE_HOURS * HOUR)]


def _wu_cache(_ctx: HandlerContext) -> list[Target]:
    # No se detiene wuauserv (lista de protección): solo descargas antiguas no bloqueadas.
    return [
        Target(
            SYSTEM_ROOT / "SoftwareDistribution" / "Download",
            min_age_seconds=CLEAN_WU_MIN_AGE_DAYS * DAY,
        )
    ]


def _prefetch(_ctx: HandlerContext) -> list[Target]:
    # La fecha de modificación de un .pf se actualiza en cada ejecución del programa.
    return [
        Target(
            SYSTEM_ROOT / "Prefetch",
            pattern="*.pf",
            min_age_seconds=CLEAN_PREFETCH_MIN_AGE_DAYS * DAY,
            recursive=False,
        )
    ]


def _thumbnails(ctx: HandlerContext) -> list[Target]:
    explorer = user_local_appdata(ctx) / "Microsoft" / "Windows" / "Explorer"
    return [Target(explorer, pattern="thumbcache_*.db", recursive=False)]


def _recycle_bins(ctx: HandlerContext) -> list[Target]:
    """Papelera del usuario interactivo en cada unidad fija ($Recycle.Bin\\<SID>)."""
    sid = ctx.env.interactive_sid
    if not sid:
        return []
    targets = []
    for part in psutil.disk_partitions(all=False):
        if "fixed" in part.opts.split(","):
            root = Path(part.mountpoint) / "$Recycle.Bin" / sid
            targets.append(Target(root))
    return targets


# --------------------------------------------------------------------------- handlers públicos

TargetFn = Callable[[HandlerContext], list[Target]]


def _pair(
    label: str, fn: TargetFn
) -> tuple[Callable[[HandlerContext], bool], Callable[[HandlerContext], DetectResult]]:
    def clean(ctx: HandlerContext) -> bool:
        return _run_clean(ctx, label, fn(ctx))

    def estimate(ctx: HandlerContext) -> DetectResult:
        return _estimate(fn(ctx))

    return clean, estimate


clean_temp_user, estimate_temp_user = _pair("temporales del usuario", _temp_user)
clean_temp_windows, estimate_temp_windows = _pair("temporales de Windows", _temp_windows)
clean_wu_cache, estimate_wu_cache = _pair("caché de Windows Update", _wu_cache)
clean_prefetch_orphans, estimate_prefetch_orphans = _pair("Prefetch obsoleto", _prefetch)
clean_thumbnails, estimate_thumbnails = _pair("caché de miniaturas", _thumbnails)


def clean_recycle_bin(ctx: HandlerContext) -> bool:
    targets = _recycle_bins(ctx)
    if targets:
        return _run_clean(ctx, "papelera de reciclaje", targets)
    # Sin SID del usuario interactivo: API de shell para la papelera del usuario del proceso.
    if ctx.dry_run:
        ctx.plan("Vaciar la papelera de reciclaje (SHEmptyRecycleBinW)")
        return True
    if sys.platform != "win32":
        raise SkipOperation("Solo disponible en Windows")
    flags = 0x1 | 0x2 | 0x4  # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)  # type: ignore[attr-defined]
    # S_OK o E_UNEXPECTED (papelera ya vacía) se consideran correctos.
    if hr not in (0, -2147418113):
        raise OSError(f"SHEmptyRecycleBinW devolvió 0x{hr & 0xFFFFFFFF:08X}")
    ctx.note("Papelera vaciada")
    return True


def estimate_recycle_bin(ctx: HandlerContext) -> DetectResult:
    targets = _recycle_bins(ctx)
    if not targets:
        return DetectResult(DetectState.UNKNOWN, "No se pudo localizar la papelera del usuario")
    return _estimate(targets)
