"""Ajustes de usuario persistidos en %LOCALAPPDATA%\\SafeTrim\\settings.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from core.constants import SETTINGS_FILE
from core.logger import get_logger

log = get_logger("settings")


@dataclass
class Settings:
    dry_run: bool = True
    allow_without_restore_point: bool = False
    export_reg_backups: bool = True
    measure_boot_after_reboot: bool = True
    # Sin opción en la interfaz: solo para VMs de prueba y CI (Windows Server en el job e2e).
    allow_unsupported_os: bool = False
    appearance: str = "dark"
    log_level: str = "INFO"
    first_run: bool = True
    # Una petición a la API de Releases de GitHub al arrancar; nada más sale del equipo.
    check_updates: bool = True
    # Tarea \SafeTrim\Maintenance cada 4 semanas (Ajustes → General).
    maintenance: bool = False

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> Settings:
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("settings_unreadable", extra={"err": str(exc)})
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path = SETTINGS_FILE) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)
