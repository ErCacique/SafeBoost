"""Acciones de limpieza (irreversibles). Cada clean_* tiene su estimate_* para el detector."""

from __future__ import annotations

import ctypes
import os
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import psutil

from core.constants import (
    CLEAN_NEGLIGIBLE_BYTES,
    CLEAN_PREFETCH_MIN_AGE_DAYS,
    CLEAN_TEMP_MIN_AGE_HOURS,
    CLEAN_WU_MIN_AGE_DAYS,
    CLEANMGR_PREVIOUS_INSTALLS_KEY,
    CLEANMGR_PROFILE,
    SYSTEM_ROOT,
    TIMEOUT_CLEANMGR,
    WINDOWS_OLD_ROLLBACK_DAYS,
)
from core.context import DetectResult, DetectState, HandlerContext, SkipOperation
from core.logger import get_logger
from core.metrics import human_bytes
from core.registry import RegValue
from tweaks._common import run_tool, user_local_appdata

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


def _is_link(entry: os.DirEntry[str] | Path) -> bool:
    """Enlace simbólico o junction (punto de montaje NTFS). Cualquier usuario puede crear una
    junction en su %TEMP% o en C:\\Windows\\Temp apuntando a otra carpeta: si la limpieza (que
    se ejecuta como administrador) entrara, borraría archivos del sistema o de otros programas."""
    try:
        return entry.is_symlink() or entry.is_junction()
    except OSError:
        return True


def _walk(root: Path, recursive: bool) -> Iterator[tuple[Path, list[os.DirEntry[str]]]]:
    """Recorre `root` sin seguir enlaces ni junctions. Devuelve (carpeta, entradas)."""
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            continue
        yield folder, entries
        if recursive:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False) and not _is_link(entry):
                        stack.append(Path(entry.path))
                except OSError:
                    continue


def _iter_candidates(target: Target, now: float) -> Iterator[Path]:
    root = target.root
    if not root.is_dir() or _is_link(root):
        return
    for _folder, entries in _walk(root, target.recursive):
        for entry in entries:
            try:
                if not entry.is_file(follow_symlinks=False) or _is_link(entry):
                    continue
                if entry.name.lower() in target.keep or not fnmatch(entry.name, target.pattern):
                    continue
                if now - entry.stat(follow_symlinks=False).st_mtime < target.min_age_seconds:
                    continue
            except OSError:
                continue
            yield Path(entry.path)


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
    if not root.is_dir() or _is_link(root):
        return
    # Sin seguir junctions: rmdir sobre una junction solo quitaría el enlace, pero entrar en ella
    # vaciaría carpetas ajenas. Las más profundas primero.
    folders = [folder for folder, _entries in _walk(root, True) if folder != root]
    for directory in sorted(folders, key=lambda p: len(p.parts), reverse=True):
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
    hr = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
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


# --------------------------------------------------------------------------- Windows.old


def windows_old_path() -> Path:
    return Path(SYSTEM_ROOT.anchor or "C:\\") / "Windows.old"


def _dir_size(root: Path) -> tuple[int, int]:
    """Bytes y archivos bajo root sin seguir enlaces ni uniones (Windows.old contiene uniones
    como "Application Data" que apuntan a sí mismas)."""
    total = files = 0
    pending = [root]
    while pending:
        try:
            entries = list(os.scandir(pending.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                else:
                    total += entry.stat(follow_symlinks=False).st_size
                    files += 1
            except OSError:
                continue
    return total, files


def _age_days(path: Path) -> int:
    # En Windows st_ctime es la fecha de creación de la carpeta.
    return max(int((time.time() - path.stat().st_ctime) / DAY), 0)


def windows_old_exists(_ctx: HandlerContext) -> bool:
    return windows_old_path().is_dir()


def estimate_windows_old(_ctx: HandlerContext) -> DetectResult:
    path = windows_old_path()
    if not path.is_dir():
        return DetectResult(DetectState.APPLIED, "No hay copia de una versión anterior")
    size, files = _dir_size(path)
    age = _age_days(path)
    message = f"{human_bytes(size)} · creada hace {age} días"
    if age < WINDOWS_OLD_ROLLBACK_DAYS:
        message += " (aún puedes volver a la versión anterior de Windows)"
    state = DetectState.NOT_APPLIED if size > CLEAN_NEGLIGIBLE_BYTES else DetectState.APPLIED
    return DetectResult(state, message, {"bytes": size, "files": files, "age_days": age})


def clean_windows_old(ctx: HandlerContext) -> bool:
    """Borra Windows.old con el Liberador de espacio de Windows (cleanmgr /sagerun): es la vía
    soportada; borrarla a mano choca con permisos de TrustedInstaller y uniones."""
    path = windows_old_path()
    if not path.is_dir():
        raise SkipOperation("No hay Windows.old")
    size, _files = _dir_size(path)
    if ctx.dry_run:
        ctx.plan(
            f"Borrar Windows.old ({human_bytes(size)}) con el Liberador de espacio de Windows. "
            "Después ya no se podrá volver a la versión anterior de Windows."
        )
        return True
    flag = f"StateFlags{CLEANMGR_PROFILE:04d}"
    # Marca "Instalaciones anteriores de Windows" para el perfil /sagerun; inocuo si se queda.
    ctx.set_registry("HKLM", CLEANMGR_PREVIOUS_INSTALLS_KEY, flag, RegValue("REG_DWORD", 2))
    run_tool(
        ctx,
        "cleanmgr",
        [f"/sagerun:{CLEANMGR_PROFILE}"],
        "Liberador de espacio (instalaciones anteriores de Windows)",
        timeout=TIMEOUT_CLEANMGR,
    )
    remaining = _dir_size(path)[0] if path.is_dir() else 0
    freed = max(size - remaining, 0)
    ctx.state["freed_bytes"] = ctx.state.get("freed_bytes", 0) + freed
    ctx.note(f"Windows.old: {human_bytes(freed)} liberados")
    if remaining > CLEAN_NEGLIGIBLE_BYTES:
        ctx.note(
            f"Quedan {human_bytes(remaining)} en Windows.old (archivos en uso): reinicia y "
            "vuelve a ejecutar la limpieza."
        )
    ctx.record("handler", {"action": "Windows.old"}, None, {"bytes": freed})
    return freed > 0


# --------------------------------------------------------------------------- navegadores

# Carpeta de datos (bajo %LOCALAPPDATA%) y proceso de cada navegador basado en Chromium.
CHROMIUM_BROWSERS: dict[str, tuple[str, str]] = {
    "Chrome": (r"Google\Chrome\User Data", "chrome.exe"),
    "Edge": (r"Microsoft\Edge\User Data", "msedge.exe"),
    "Brave": (r"BraveSoftware\Brave-Browser\User Data", "brave.exe"),
    "Opera": (r"Opera Software\Opera Stable", "opera.exe"),
}
# Solo cachés que el navegador regenera: nunca cookies, historial, contraseñas ni sesiones.
CHROMIUM_CACHE_DIRS = (r"Cache\Cache_Data", "Code Cache", "GPUCache")


def _join(base: Path, rel: str) -> Path:
    """Las rutas relativas se escriben con "\\" como en Windows; se unen por partes."""
    return base.joinpath(*rel.split("\\"))


def _chromium_profiles(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    # Opera guarda la caché directamente en la raíz; Chrome/Edge/Brave en Default y Profile N.
    # Solo se usan las carpetas de caché conocidas que existan dentro (browser_caches).
    return [root, *(p for p in root.iterdir() if p.is_dir())]


def browser_caches(local_appdata: Path) -> dict[str, list[Path]]:
    """Carpetas de caché por navegador instalado (Chromium y Firefox)."""
    out: dict[str, list[Path]] = {}
    for name, (rel, _exe) in CHROMIUM_BROWSERS.items():
        dirs = [
            _join(profile, cache)
            for profile in _chromium_profiles(_join(local_appdata, rel))
            for cache in CHROMIUM_CACHE_DIRS
            if _join(profile, cache).is_dir()
        ]
        if dirs:
            out[name] = dirs
    firefox = local_appdata / "Mozilla" / "Firefox" / "Profiles"
    if firefox.is_dir():
        dirs = [p / "cache2" for p in firefox.iterdir() if (p / "cache2").is_dir()]
        if dirs:
            out["Firefox"] = dirs
    return out


def folder_bytes(dirs: list[Path]) -> int:
    """Tamaño de unas carpetas (solo lectura), para mostrarlo antes de limpiar."""
    return _measure([Target(d) for d in dirs]).bytes


def _running_browsers() -> set[str]:
    exes = {exe: name for name, (_rel, exe) in CHROMIUM_BROWSERS.items()} | {
        "firefox.exe": "Firefox"
    }
    running = set()
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in exes:
            running.add(exes[name])
    return running


def _browser_targets(ctx: HandlerContext) -> tuple[list[Target], list[str]]:
    running = _running_browsers()
    targets: list[Target] = []
    skipped: list[str] = []
    for name, dirs in browser_caches(user_local_appdata(ctx)).items():
        if name in running:
            skipped.append(name)  # con el navegador abierto los archivos están en uso
            continue
        targets.extend(Target(d) for d in dirs)
    return targets, skipped


def clean_browser_cache(ctx: HandlerContext) -> bool:
    targets, skipped = _browser_targets(ctx)
    if skipped:
        ctx.note(f"Cierra {', '.join(skipped)} para limpiar su caché (ahora está abierto)")
    if not targets:
        raise SkipOperation(
            "Caché de navegadores: cierra el navegador y vuelve a intentarlo"
            if skipped
            else "Caché de navegadores: nada que limpiar"
        )
    return _run_clean(ctx, "caché de navegadores", targets)


def estimate_browser_cache(ctx: HandlerContext) -> DetectResult:
    targets = [Target(d) for dirs in browser_caches(user_local_appdata(ctx)).values() for d in dirs]
    return _estimate(targets)
