"""v0.11.1: arreglos de la auditoría de seguridad (SafeBoost se ejecuta como administrador)."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import pytest

from core.catalog import Catalog
from core.constants import protected_location
from core.engine import clean_params
from core.process import ps_quote
from core.update_check import still_verified, update_dir
from tweaks.cleanup import Target, _delete, _measure


@pytest.mark.parametrize("quote", ["'", "\u2018", "\u2019", "\u201a", "\u201b"])
def test_ps_quote_escapes_every_single_quote_powershell_accepts(quote: str) -> None:
    evil = f"Spotify{quote}; Remove-Item C:\\ -Recurse; {quote}"
    quoted = ps_quote(evil)
    inner = quoted[1:-1]
    # Cada comilla del valor queda duplicada: PowerShell no puede cerrar la cadena antes.
    assert inner.count(quote * 2) == 2
    assert inner.replace(quote * 2, "") == "Spotify; Remove-Item C:\\ -Recurse; "


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="sin enlaces simbólicos")
def test_cleanup_never_follows_links_out_of_the_folder(tmp_path: Path) -> None:
    temp = tmp_path / "Temp"
    victim = tmp_path / "Windows" / "System32"
    temp.mkdir()
    victim.mkdir(parents=True)
    old = time.time() - 10 * 86400
    for path in (temp / "basura.tmp", victim / "kernel32.dll"):
        path.write_bytes(b"x" * 10)
        os.utime(path, (old, old))
    # Lo que haría un programa sin permisos: un enlace en %TEMP% hacia una carpeta del sistema.
    (temp / "trampa").symlink_to(victim, target_is_directory=True)
    target = Target(temp, min_age_seconds=3600)
    assert _measure([target]).files == 1
    tally = _delete([target])
    assert tally.files == 1 and not (temp / "basura.tmp").exists()
    assert (victim / "kernel32.dll").exists() and victim.is_dir()
    # Tampoco se limpia una carpeta raíz que sea en sí un enlace.
    assert _measure([Target(temp / "trampa")]).files == 0


def test_elevated_tasks_only_for_protected_locations() -> None:
    roots = [r"C:\Program Files", r"C:\Program Files (x86)", r"C:\Windows"]
    assert protected_location([r"C:\Program Files\SafeBoost\SafeBoost.exe"], roots)
    assert protected_location([r"c:\program files (x86)\SafeBoost\SafeBoost.exe"], roots)
    assert not protected_location([r"C:\Users\Ana\Downloads\SafeBoost.exe"], roots)
    assert not protected_location([r"E:\SafeBoost\SafeBoost.exe"], roots)  # USB
    assert not protected_location([r"C:\Program Files\..\Users\Ana\x.exe"], roots)
    assert not protected_location([r"C:\Program FilesX\x.exe"], roots)
    assert not protected_location([], roots)


def test_imported_params_are_validated() -> None:
    catalog = Catalog.load()
    drives = catalog.get("search.indexing_drives")
    assert clean_params(drives, {"drives": ["D:", "E:\\"]}) == {"drives": ["D:", "E:\\"]}
    assert clean_params(drives, {"drives": ["D:'; calc; '"]}) == {}
    assert clean_params(drives, {"drives": "non_system"}) == {"drives": "non_system"}
    dns = catalog.get("network.dns")
    assert clean_params(dns, {"provider": "quad9"}) == {"provider": "quad9"}
    assert clean_params(dns, {"provider": "evil.example"}) == {}
    assert clean_params(dns, {"unknown": 1}) == {}
    pagefile = catalog.get("memory.pagefile_fixed")
    assert clean_params(pagefile, {"size_mb": "8192"}) == {}
    assert clean_params(pagefile, {"size_mb": True}) == {}
    assert clean_params(pagefile, {"size_mb": 8192}) == {"size_mb": 8192}


def test_installer_is_rechecked_before_running() -> None:
    folder = update_dir()
    try:
        installer = folder / "SafeBoost-Setup-9.9.9.exe"
        installer.write_bytes(b"instalador bueno")
        digest = hashlib.sha256(b"instalador bueno").hexdigest()
        (folder / "SHA256SUMS.txt").write_text(f"{digest}  {installer.name}\n", encoding="utf-8")
        assert still_verified(installer)
        installer.write_bytes(b"instalador cambiado")
        assert not still_verified(installer)
    finally:
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()
