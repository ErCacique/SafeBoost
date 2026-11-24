"""Prepara la carpeta del paquete MSIX para Microsoft Store.

    python scripts/make_msix.py VERSION CARPETA_PYINSTALLER CARPETA_SALIDA

Copia el programa compilado (dist/SafeBoost), genera los iconos que pide la Store a partir de
assets/safeboost.ico y escribe AppxManifest.xml con los datos de packaging/msix/store.json.
Después, en Windows: makeappx pack /d CARPETA_SALIDA /p SafeBoost.msix /nv
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MSIX_DIR = ROOT / "packaging" / "msix"
ICON = ROOT / "assets" / "safeboost.ico"
# Nombre del archivo → tamaño (ancho, alto) que exige el manifiesto.
ASSETS = {
    "StoreLogo.png": (50, 50),
    "Square44x44Logo.png": (44, 44),
    "Square150x150Logo.png": (150, 150),
    "Wide310x150Logo.png": (310, 150),
}


def msix_version(version: str) -> str:
    """MSIX exige cuatro números y la Store que el último sea 0."""
    parts = [int(p) for p in version.split(".")]
    if len(parts) != 3:
        raise ValueError(f"Versión no válida: {version} (formato X.Y.Z)")
    return ".".join(str(p) for p in [*parts, 0])


def make_assets(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with Image.open(ICON) as ico:
        # Un .ico trae varios tamaños; se usa el mayor como origen.
        largest = max(ico.info.get("sizes", {ico.size}))
        ico.size = largest  # type: ignore[misc]
        source = ico.convert("RGBA")
    for name, (width, height) in ASSETS.items():
        side = min(width, height)
        logo = source.resize((side, side), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(logo, ((width - side) // 2, (height - side) // 2), logo)
        canvas.save(target / name)


def render_manifest(version: str, store: dict[str, str]) -> str:
    text = (MSIX_DIR / "AppxManifest.xml").read_text(encoding="utf-8")
    values = {**store, "version": msix_version(version)}
    for key in ("identity_name", "publisher", "publisher_display_name", "version"):
        text = text.replace("{{" + key + "}}", values[key])
    if "{{" in text:
        raise ValueError("Quedan valores sin rellenar en AppxManifest.xml")
    return text


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    version, build, out = argv[0], Path(argv[1]), Path(argv[2])
    if not (build / "SafeBoost.exe").exists():
        print(f"No está SafeBoost.exe en {build}")
        return 1
    store = json.loads((MSIX_DIR / "store.json").read_text(encoding="utf-8"))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(build, out)
    make_assets(out / "Assets")
    (out / "AppxManifest.xml").write_text(render_manifest(version, store), encoding="utf-8")
    if store["publisher"].startswith("CN=00000000"):
        print("Aviso: packaging/msix/store.json tiene datos de ejemplo; la Store lo rechazará.")
    print(f"Carpeta MSIX lista en {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
