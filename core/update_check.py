"""Aviso de versión nueva: consulta la última Release publicada en GitHub.

Una petición HTTPS de solo lectura al arrancar (desactivable en Ajustes). Si hay versión nueva,
el usuario puede pulsar "Actualizar ahora": se descarga el instalador, se comprueba su SHA-256
contra SHA256SUMS.txt del mismo Release y solo entonces se ejecuta. Si no hay red, GitHub no
responde o el repositorio es privado (404 sin credenciales), no dice nada.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.constants import APP_NAME, APP_VERSION, SYSTEM_ROOT, UPDATE_API_URL, UPDATE_CHECK_TIMEOUT
from core.logger import get_logger

log = get_logger("update_check")

Opener = Callable[..., Any]


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    url: str
    setup_url: str = ""  # SafeBoost-Setup-X.Y.Z.exe
    sums_url: str = ""  # SHA256SUMS.txt


def parse_version(text: str) -> tuple[int, ...] | None:
    """'v0.4.0' o '0.4.0' → (0, 4, 0). None si no es una versión X.Y.Z numérica."""
    parts = text.strip().lstrip("vV").split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def check_latest(
    current: str = APP_VERSION,
    opener: Opener = urllib.request.urlopen,
    url: str = UPDATE_API_URL,
    timeout: float = UPDATE_CHECK_TIMEOUT,
) -> ReleaseInfo | None:
    """Devuelve la Release publicada si es más nueva que `current`; None en cualquier otro caso."""
    if not url.startswith("https://"):
        return None
    request = urllib.request.Request(  # noqa: S310 - esquema https comprobado arriba
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}/{current}",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 404: repositorio privado o sin Releases. No es un error para el usuario.
        log.info("update_check_http", extra={"status": exc.code})
        return None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.info("update_check_failed", extra={"err": str(exc)})
        return None
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    latest = parse_version(str(data.get("tag_name") or ""))
    mine = parse_version(current)
    page = str(data.get("html_url") or "")
    if latest is None or mine is None or latest <= mine or not page.startswith("https://"):
        return None
    version = ".".join(map(str, latest))
    assets = {
        str(a.get("name")): str(a.get("browser_download_url") or "")
        for a in data.get("assets") or []
        if isinstance(a, dict)
    }
    # Hasta 0.10.x el instalador se llamaba SafeTrim-Setup; se acepta por si acaso.
    setup = assets.get(f"SafeBoost-Setup-{version}.exe") or assets.get(
        f"SafeTrim-Setup-{version}.exe", ""
    )
    sums = assets.get("SHA256SUMS.txt", "")
    if not (setup.startswith("https://") and sums.startswith("https://")):
        setup = sums = ""
    return ReleaseInfo(version, page, setup, sums)


def _download(url: str, target: Path, opener: Opener, timeout: float = 120) -> None:
    if not url.startswith("https://"):
        raise ValueError(f"URL no segura: {url}")
    request = urllib.request.Request(  # noqa: S310 - esquema https comprobado arriba
        url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}
    )
    with opener(request, timeout=timeout) as response, target.open("wb") as fh:
        while chunk := response.read(1024 * 1024):
            fh.write(chunk)


def expected_hash(sums_text: str, file_name: str) -> str | None:
    """Busca "<sha256>  <archivo>" en SHA256SUMS.txt."""
    for line in sums_text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1] == file_name and len(parts[0]) == 64:
            return parts[0].lower()
    return None


def download_installer(
    info: ReleaseInfo, directory: Path, opener: Opener = urllib.request.urlopen
) -> Path:
    """Descarga el instalador y comprueba su SHA-256 con SHA256SUMS.txt del mismo Release.
    Lanza ValueError si no coincide (el archivo se borra)."""
    if not info.setup_url or not info.sums_url:
        raise ValueError("Esta versión no publica instalador con huella SHA-256")
    directory.mkdir(parents=True, exist_ok=True)
    name = info.setup_url.rsplit("/", 1)[-1]
    sums = directory / "SHA256SUMS.txt"
    target = directory / name
    _download(info.sums_url, sums, opener, timeout=30)
    expected = expected_hash(sums.read_text(encoding="utf-8", errors="replace"), name)
    if expected is None:
        raise ValueError(f"{name} no aparece en SHA256SUMS.txt")
    _download(info.setup_url, target, opener)
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    if actual != expected:
        target.unlink(missing_ok=True)
        raise ValueError("La huella SHA-256 del instalador no coincide: descarga descartada")
    return target


def update_dir() -> Path:
    """Carpeta nueva para la descarga. En Windows, dentro de C:\\Windows\\Temp: SafeBoost se
    ejecuta como administrador y lo que crea ahí no lo puede modificar un programa sin permisos
    (en el %TEMP% del usuario sí podría cambiar el instalador antes de que se ejecute)."""
    system_temp = SYSTEM_ROOT / "Temp"
    if sys.platform == "win32" and system_temp.is_dir():
        try:
            return Path(tempfile.mkdtemp(prefix="SafeBoost-update-", dir=system_temp))
        except OSError:
            pass
    return Path(tempfile.mkdtemp(prefix="SafeBoost-update-"))


def still_verified(installer: Path) -> bool:
    """Repite la comprobación de la huella justo antes de ejecutar el instalador."""
    try:
        sums = (installer.parent / "SHA256SUMS.txt").read_text(encoding="utf-8", errors="replace")
        expected = expected_hash(sums, installer.name)
        return (
            expected is not None and hashlib.sha256(installer.read_bytes()).hexdigest() == expected
        )
    except OSError:
        return False


def installer_command(installer: Path) -> list[str]:
    """Instalación silenciosa de Inno Setup: cierra SafeBoost, actualiza y lo vuelve a abrir."""
    return [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS", "/NORESTART"]
