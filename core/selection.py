"""Exportar e importar una selección de tweaks (y sus parámetros) a un archivo JSON.

Permite replicar la misma configuración en varios equipos, desde la interfaz o con
`SafeTrim --apply-selection archivo.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.catalog import Catalog
from core.constants import APP_VERSION, LEGACY_SELECTION_FORMATS

SELECTION_FORMAT = "safetrim-selection"
SELECTION_VERSION = 1


class SelectionError(ValueError):
    pass


@dataclass
class Selection:
    tweaks: list[str]
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    profile: int | None = None
    app_version: str = APP_VERSION
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": SELECTION_FORMAT,
            "version": SELECTION_VERSION,
            "app_version": self.app_version,
            "created": self.created,
            "profile": self.profile,
            "tweaks": self.tweaks,
            "params": self.params,
        }

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def load_selection(path: Path, catalog: Catalog) -> tuple[Selection, list[str]]:
    """Lee y valida una selección. Devuelve (selección, avisos).

    Los IDs que ya no existen en el catálogo se descartan con un aviso en vez de fallar: así un
    archivo exportado con una versión anterior sigue siendo útil.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectionError(f"No se pudo leer {path}: {exc}") from exc
    formats = (SELECTION_FORMAT, *LEGACY_SELECTION_FORMATS)
    if not isinstance(raw, dict) or raw.get("format") not in formats:
        raise SelectionError(f"{path.name} no es un archivo de selección de SafeTrim")
    if int(raw.get("version", 0)) > SELECTION_VERSION:
        raise SelectionError("El archivo es de una versión de SafeTrim más nueva")
    tweaks = raw.get("tweaks")
    params = raw.get("params") or {}
    if not isinstance(tweaks, list) or not all(isinstance(t, str) for t in tweaks):
        raise SelectionError("El campo 'tweaks' debe ser una lista de IDs")
    if not isinstance(params, dict):
        raise SelectionError("El campo 'params' debe ser un objeto")
    warnings = [
        f"{tid}: no existe en esta versión del catálogo" for tid in tweaks if tid not in catalog
    ]
    valid = [tid for tid in tweaks if tid in catalog]
    clean_params = {
        tid: dict(p) for tid, p in params.items() if tid in valid and isinstance(p, dict)
    }
    profile = raw.get("profile")
    selection = Selection(
        tweaks=valid,
        params=clean_params,
        profile=int(profile) if isinstance(profile, int) else None,
        app_version=str(raw.get("app_version", "?")),
        created=str(raw.get("created", "")),
    )
    return selection, warnings
