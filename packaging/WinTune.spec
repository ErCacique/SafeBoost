# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 6.22.3 · Python 3.12 · Ejecutar desde la raíz del repo:
#   pyinstaller --clean --noconfirm packaging/WinTune.spec
#
# Equivalente en línea de comandos (por referencia):
#   pyinstaller --onefile --noconsole --uac-admin --name WinTune --clean ^
#     --add-data "data/tweaks.json;data" --add-data "data/tweaks.schema.json;data" ^
#     --collect-data customtkinter --paths . --hidden-import tweaks.cleanup (uno por módulo) ^
#     --version-file packaging/version_info.txt --noupx main.py

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH lo inyecta PyInstaller

datas = [
    (str(ROOT / "data" / "tweaks.json"), "data"),
    (str(ROOT / "data" / "tweaks.schema.json"), "data"),
]
# Temas JSON y fuentes de CustomTkinter: sin esto el .exe arranca sin estilos.
datas += collect_data_files("customtkinter")

# Los handlers se cargan con importlib a partir de tweaks.json: PyInstaller no los ve solo.
# Se listan desde los ficheros: collect_submodules("tweaks") corre en un subproceso sin la
# raíz del repo en sys.path y devuelve una lista vacía sin avisar.
hiddenimports = ["tweaks"] + sorted(
    f"tweaks.{p.stem}" for p in (ROOT / "tweaks").glob("*.py") if p.stem != "__init__"
)

a = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "jsonschema", "ruff"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WinTune",
    console=False,
    # Manifest con requestedExecutionLevel=requireAdministrator: Windows pide UAC al abrir.
    uac_admin=True,
    # UPX desactivado: los binarios comprimidos con UPX disparan más falsos positivos de AV.
    upx=False,
    version=str(ROOT / "packaging" / "version_info.txt"),
    disable_windowed_traceback=False,
)
