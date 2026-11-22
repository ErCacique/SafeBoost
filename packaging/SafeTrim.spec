# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.22.3 · Python 3.12 · Ejecutar desde la raíz del repo:
#   pyinstaller --clean --noconfirm packaging/SafeTrim.spec
#
# Genera una carpeta (onedir) en dist/SafeTrim: SafeTrim.exe + _internal/. A partir de ella el
# release crea el instalador (packaging/SafeTrim.iss) y la versión portable (.zip).
#
# Por qué onedir y no onefile: un .exe de un solo archivo se descomprime entero en %TEMP% cada
# vez que se abre (varios segundos en un equipo lento) y los antivirus desconfían más de ese
# patrón de "autoextracción".

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH lo inyecta PyInstaller

datas = [
    (str(ROOT / "data" / "tweaks.json"), "data"),
    (str(ROOT / "data" / "tweaks.schema.json"), "data"),
    (str(ROOT / "assets" / "safetrim.ico"), "assets"),
    (str(ROOT / "data" / "i18n"), "data/i18n"),
]
# Temas JSON y fuentes de CustomTkinter: sin esto el .exe arranca sin estilos.
datas += collect_data_files("customtkinter")

# Los handlers se cargan con importlib a partir de tweaks.json: PyInstaller no los ve solo.
# Se listan desde los ficheros: collect_submodules("tweaks") corre en un subproceso sin la
# raíz del repo en sys.path y devuelve una lista vacía sin avisar.
hiddenimports = ["tweaks", "pystray._win32", "core.tray"] + sorted(
    f"tweaks.{p.stem}" for p in (ROOT / "tweaks").glob("*.py") if p.stem != "__init__"
)

a = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "jsonschema", "ruff", "mypy", "coverage"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SafeTrim",
    console=False,
    # Manifest con requestedExecutionLevel=requireAdministrator: Windows pide UAC al abrir.
    uac_admin=True,
    # UPX desactivado: los binarios comprimidos con UPX disparan más falsos positivos de AV.
    upx=False,
    version=str(ROOT / "packaging" / "version_info.txt"),
    icon=str(ROOT / "assets" / "safetrim.ico"),
    disable_windowed_traceback=False,
    contents_directory="_internal",
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SafeTrim",
)
