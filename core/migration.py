"""Migración de datos del nombre anterior del programa (WinTune, hasta 0.2.x) a SafeTrim.

Las sesiones guardadas son lo que permite Deshacer: si no se trajeran, no se podría revertir
lo aplicado con la versión anterior. Se COPIA (no se mueve ni se borra) porque "WinTune" es
también el nombre de otro producto real: solo se copia si la carpeta es claramente nuestra.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.constants import (
    APP_HOME,
    APP_NAME,
    HOME_OVERRIDDEN,
    LEGACY_HOME,
    LEGACY_LOG_FILE_NAME,
    LEGACY_MIGRATED_MARKER,
    LEGACY_TASK_FOLDER,
    POST_REBOOT_TASK_NAME,
)
from core.logger import get_logger
from core.process import Runner, ps_quote

log = get_logger("migration")

COPIED_ENTRIES = ("sessions", "backups", "metrics", "logs", "settings.json")


@dataclass
class MigrationResult:
    migrated: bool
    reason: str
    copied: list[str] = field(default_factory=list)


def looks_like_ours(folder: Path) -> bool:
    """La carpeta antigua es de este programa si tiene sesiones con nuestro formato o su log."""
    if (folder / "logs" / LEGACY_LOG_FILE_NAME).exists():
        return True
    for path in (folder / "sessions").glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and {"kind", "results", "changes"} <= data.keys():
            return True
    return False


def migrate_legacy_data(
    runner: Runner | None = None,
    legacy_home: Path = LEGACY_HOME,
    new_home: Path = APP_HOME,
    overridden: bool = HOME_OVERRIDDEN,
) -> MigrationResult:
    if overridden:
        return MigrationResult(False, "carpeta de datos redirigida por variable de entorno")
    if not legacy_home.is_dir():
        return MigrationResult(False, "no hay datos de la versión anterior")
    if (legacy_home / LEGACY_MIGRATED_MARKER).exists():
        return MigrationResult(False, "ya se migró antes")
    if (new_home / "sessions").is_dir() and any((new_home / "sessions").glob("*.json")):
        return MigrationResult(False, f"{APP_NAME} ya tiene sesiones propias")
    if not looks_like_ours(legacy_home):
        return MigrationResult(False, "la carpeta WinTune no es de este programa")

    new_home.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in COPIED_ENTRIES:
        source = legacy_home / name
        target = new_home / name
        try:
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
                copied.append(name)
            elif source.is_file() and not target.exists():
                shutil.copy2(source, target)
                copied.append(name)
        except OSError as exc:
            log.warning("migration_copy_failed", extra={"entry": name, "err": str(exc)})
    stamp = datetime.now().isoformat(timespec="seconds")
    (legacy_home / LEGACY_MIGRATED_MARKER).write_text(
        f"Datos copiados a {new_home} el {stamp}. Esta carpeta ya no se usa y puedes borrarla.\n",
        encoding="utf-8",
    )
    if runner is not None:
        # La tarea antigua lanzaría WinTune.exe, que ya no existe o no se usa.
        runner.powershell(
            f"Unregister-ScheduledTask -TaskPath {ps_quote(LEGACY_TASK_FOLDER)} "
            f"-TaskName {ps_quote(POST_REBOOT_TASK_NAME)} -Confirm:$false "
            "-ErrorAction SilentlyContinue"
        )
    log.info("legacy_migrated", extra={"from": str(legacy_home), "copied": copied})
    return MigrationResult(True, "datos de WinTune copiados", copied)
