"""Genera los manifiestos de winget (esquema 1.6) para una versión publicada.

Uso (lo ejecuta release.yml): python scripts/make_winget.py VERSION SHA256_SETUP SALIDA
Para publicar en winget: abrir un PR con la carpeta generada en microsoft/winget-pkgs
(manifests/e/ErCacique/SafeBoost/VERSION) o usar `wingetcreate submit`. Requiere que las Releases
sean públicas: winget descarga el instalador desde la URL del manifiesto.
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE = "ErCacique.SafeBoost"
REPO = "https://github.com/ErCacique/SafeBoost"
SCHEMA = "1.6.0"


def manifests(version: str, sha256: str) -> dict[str, str]:
    url = f"{REPO}/releases/download/v{version}/SafeBoost-Setup-{version}.exe"
    head = f"PackageIdentifier: {PACKAGE}\nPackageVersion: {version}\n"
    return {
        f"{PACKAGE}.yaml": f"{head}DefaultLocale: es-ES\nManifestType: version\n"
        f"ManifestVersion: {SCHEMA}\n",
        f"{PACKAGE}.installer.yaml": f"{head}InstallerType: inno\nScope: machine\n"
        "ElevationRequirement: elevatesSelf\nMinimumOSVersion: 10.0.19045.0\nInstallers:\n"
        f"  - Architecture: x64\n    InstallerUrl: {url}\n    InstallerSha256: {sha256.upper()}\n"
        f"ManifestType: installer\nManifestVersion: {SCHEMA}\n",
        f"{PACKAGE}.locale.es-ES.yaml": f"{head}PackageLocale: es-ES\nPublisher: ErCacique\n"
        f"PackageName: SafeBoost\nPackageUrl: {REPO}\nLicense: Propietaria\n"
        "ShortDescription: Optimización reversible de Windows 10 y 11, con diagnóstico de "
        "hardware y deshacer verificado.\nTags:\n  - optimizacion\n  - privacidad\n  - windows\n"
        f"ReleaseNotesUrl: {REPO}/blob/v{version}/CHANGELOG.md\n"
        f"ManifestType: defaultLocale\nManifestVersion: {SCHEMA}\n",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3 or len(argv[1]) != 64:
        print("Uso: make_winget.py VERSION SHA256_SETUP SALIDA")
        return 2
    version, sha256, out = argv
    target = Path(out)
    target.mkdir(parents=True, exist_ok=True)
    for name, text in manifests(version, sha256).items():
        (target / name).write_text(text, encoding="utf-8")
        print(target / name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
