"""Qué ocupa el disco: carpetas y archivos más grandes y duplicados en Descargas. Solo lee.

SafeTrim no borra nada desde aquí: enseña dónde está el espacio y el usuario decide (botón para
abrir la carpeta). El recorrido no sigue enlaces ni uniones y se salta lo que no puede leer.
"""

from __future__ import annotations

import hashlib
import heapq
import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

TOP_FOLDERS = 12
TOP_FILES = 15
BIG_FILE_BYTES = 200 * 1024 * 1024
DUPLICATE_MIN_BYTES = 1024 * 1024  # los duplicados pequeños no merecen la pena
HASH_CHUNK = 1024 * 1024


@dataclass
class FolderSize:
    path: Path
    size: int
    files: int


@dataclass
class BigFile:
    path: Path
    size: int


@dataclass
class DuplicateGroup:
    size: int  # tamaño de cada copia
    paths: list[Path]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.paths) - 1)


@dataclass
class DiskUsageReport:
    root: Path
    folders: list[FolderSize] = field(default_factory=list)
    big_files: list[BigFile] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)


def _entries(path: Path) -> list[os.DirEntry[str]]:
    try:
        return list(os.scandir(path))
    except OSError:
        return []


def _is_link(entry: os.DirEntry[str]) -> bool:
    try:
        return entry.is_symlink() or bool(getattr(entry, "is_junction", lambda: False)())
    except OSError:
        return True


def walk_sizes(
    root: Path,
    on_file: Callable[[Path, int], None] | None = None,
    cancel: Callable[[], bool] = lambda: False,
) -> tuple[int, int]:
    """Bytes y archivos bajo root sin seguir enlaces; llama on_file por cada archivo."""
    total = files = 0
    pending = [root]
    while pending and not cancel():
        for entry in _entries(pending.pop()):
            if _is_link(entry):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            total += size
            files += 1
            if on_file is not None:
                on_file(Path(entry.path), size)
    return total, files


def scan(root: Path, cancel: Callable[[], bool] = lambda: False) -> DiskUsageReport:
    """Tamaño de cada subcarpeta de primer nivel de root y los archivos más grandes."""
    report = DiskUsageReport(root)
    biggest: list[tuple[int, str]] = []

    def on_file(path: Path, size: int) -> None:
        if size >= BIG_FILE_BYTES:
            heapq.heappush(biggest, (size, str(path)))
            if len(biggest) > TOP_FILES:
                heapq.heappop(biggest)

    for entry in _entries(root):
        if cancel() or _is_link(entry):
            continue
        path = Path(entry.path)
        try:
            if entry.is_dir(follow_symlinks=False):
                size, count = walk_sizes(path, on_file, cancel)
            else:
                size, count = entry.stat(follow_symlinks=False).st_size, 1
                on_file(path, size)
        except OSError:
            continue
        report.folders.append(FolderSize(path, size, count))
    report.folders.sort(key=lambda f: f.size, reverse=True)
    report.folders = report.folders[:TOP_FOLDERS]
    report.big_files = [BigFile(Path(p), s) for s, p in sorted(biggest, reverse=True)]
    return report


def _digest(path: Path) -> str | None:
    sha = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            while chunk := fh.read(HASH_CHUNK):
                sha.update(chunk)
    except OSError:
        return None
    return sha.hexdigest()


def find_duplicates(folder: Path, min_bytes: int = DUPLICATE_MIN_BYTES) -> list[DuplicateGroup]:
    """Archivos idénticos (mismo tamaño y mismo SHA-256). Solo se calcula el hash de los que
    comparten tamaño, así que es rápido aunque Descargas tenga muchos archivos."""
    by_size: dict[int, list[Path]] = defaultdict(list)
    walk_sizes(folder, lambda p, s: by_size[s].append(p) if s >= min_bytes else None)
    groups = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for path in paths:
            digest = _digest(path)
            if digest:
                by_hash[digest].append(path)
        groups += [DuplicateGroup(size, sorted(p)) for p in by_hash.values() if len(p) > 1]
    groups.sort(key=lambda g: g.wasted, reverse=True)
    return groups


def last_used_by_exe(prefetch: Path) -> dict[str, float]:
    """Último uso de cada ejecutable según Prefetch (NOMBRE.EXE-HASH.pf → fecha de modificación).

    Windows actualiza el .pf cada vez que se ejecuta el programa. Requiere permisos de
    administrador; si no se puede leer, devuelve un diccionario vacío.
    """
    out: dict[str, float] = {}
    for entry in _entries(prefetch):
        name = entry.name
        if not name.lower().endswith(".pf") or "-" not in name:
            continue
        exe = name.rsplit("-", 1)[0].lower()
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        out[exe] = max(out.get(exe, 0.0), mtime)
    return out
