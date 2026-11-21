"""Aviso de versión nueva: consulta la última Release publicada en GitHub.

Una sola petición HTTPS de solo lectura al arrancar (desactivable en Ajustes). No descarga ni
instala nada: solo informa y abre la página de la Release si el usuario quiere. Si no hay red,
GitHub no responde o el repositorio es privado (404 sin credenciales), no dice nada.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.constants import APP_NAME, APP_VERSION, UPDATE_API_URL, UPDATE_CHECK_TIMEOUT
from core.logger import get_logger

log = get_logger("update_check")

Opener = Callable[..., Any]


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    url: str


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
    return ReleaseInfo(".".join(map(str, latest)), page)
