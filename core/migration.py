"""Migración de datos de los nombres anteriores del programa a SafeBoost.

- SafeTrim (0.3.0 a 0.10.x): se copia la carpeta entera (sesiones para deshacer, copias .reg,
  vigilancia, licencia, ajustes…) y se vuelven a crear con el nuevo nombre las tareas
  programadas que tuviera activas (mantenimiento mensual y vigilancia en segundo plano).
- WinTune (hasta 0.2.x): solo sesiones, copias, métricas, logs y ajustes, y solo si la carpeta es
  claramente nuestra, porque "WinTune" es también el nombre de otro producto real.

Las sesiones guardadas son lo que permite Deshacer: si no se trajeran, no se podría revertir
lo aplicado con la versión anterior. Siempre se COPIA: no se mueve ni se borra nada.
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
    ENV_OVERRIDDEN,
    HOME_OVERRIDDEN,
    LEGACY_HOME,
    LEGACY_LOG_FILE_NAME,
    LEGACY_MIGRATED_MARKER,
    LEGACY_TASK_FOLDER,
    POST_REBOOT_TASK_NAME,
    SAFETRIM_HOME,
    SAFETRIM_MIGRATED_MARKER,
    SAFETRIM_TASK_FOLDER_OLD,
    self_command,
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


# --------------------------------------------------------------------------- SafeTrim → SafeBoost

# Tareas que SafeTrim dejaba en \\SafeTrim\\ con la ruta de SafeTrim.exe, que ya no existe.
_OLD_TASKS = ("Maintenance", "Tray", POST_REBOOT_TASK_NAME)


def _old_task_user(runner: Runner, name: str) -> str | None:
    """Usuario de la tarea antigua, o None si no existe."""
    try:
        data = runner.powershell_json(
            f"$t = Get-ScheduledTask -TaskPath {ps_quote(SAFETRIM_TASK_FOLDER_OLD)} "
            f"-TaskName {ps_quote(name)} -ErrorAction SilentlyContinue;"
            "if ($t) { ConvertTo-Json -Compress @{ user = $t.Principal.UserId } }"
        )
    except Exception as exc:  # noqa: BLE001 - migrar tareas nunca debe impedir arrancar
        log.warning("migration_task_query_failed", extra={"task": name, "err": str(exc)})
        return None
    return str(data.get("user") or "") if isinstance(data, dict) else None


def _stop_old_tray(old_home: Path) -> None:
    import psutil

    try:
        pid = int((old_home / "tray.pid").read_text(encoding="ascii").strip())
        psutil.Process(pid).terminate()
    except (OSError, ValueError, psutil.Error):
        return


def migrate_tasks(runner: Runner, command: list[str] | None = None) -> list[str]:
    """Vuelve a crear con el nombre nuevo las tareas que el usuario tenía activas y borra las
    antiguas. Devuelve las tareas recreadas."""
    from core.tray import TRAY_TASK, schedule_tray
    from core.watch import MAINTENANCE_TASK, schedule_maintenance

    command = command or self_command()
    recreated: list[str] = []
    schedulers = {MAINTENANCE_TASK: schedule_maintenance, TRAY_TASK: schedule_tray}
    for name in _OLD_TASKS:
        user = _old_task_user(runner, name)
        if user is None:
            continue
        runner.powershell(
            f"Unregister-ScheduledTask -TaskPath {ps_quote(SAFETRIM_TASK_FOLDER_OLD)} "
            f"-TaskName {ps_quote(name)} -Confirm:$false -ErrorAction SilentlyContinue"
        )
        scheduler = schedulers.get(name)
        if scheduler is not None and user and scheduler(runner, command, user):
            recreated.append(name)
    return recreated


def migrate_from_safetrim(
    runner: Runner | None = None,
    old_home: Path = SAFETRIM_HOME,
    new_home: Path = APP_HOME,
    overridden: bool = ENV_OVERRIDDEN,
) -> MigrationResult:
    """Copia los datos de SafeTrim a SafeBoost (una sola vez) y migra sus tareas programadas."""
    if overridden:
        return MigrationResult(False, "carpeta de datos redirigida por variable de entorno")
    if not old_home.is_dir():
        return MigrationResult(False, "no hay datos de SafeTrim")
    if (old_home / SAFETRIM_MIGRATED_MARKER).exists():
        return MigrationResult(False, "ya se migró antes")
    if (new_home / "sessions").is_dir() and any((new_home / "sessions").glob("*.json")):
        return MigrationResult(False, f"{APP_NAME} ya tiene sesiones propias")

    new_home.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in sorted(old_home.iterdir()):
        if source.name in (LEGACY_MIGRATED_MARKER, "tray.pid"):
            continue
        target = new_home / source.name
        try:
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            elif not target.exists():
                shutil.copy2(source, target)
            else:
                continue
            copied.append(source.name)
        except OSError as exc:
            log.warning("migration_copy_failed", extra={"entry": source.name, "err": str(exc)})
    # El log antiguo sigue en logs/safetrim.jsonl; el nuevo se escribe en logs/safeboost.jsonl.
    stamp = datetime.now().isoformat(timespec="seconds")
    (old_home / SAFETRIM_MIGRATED_MARKER).write_text(
        f"SafeTrim ahora se llama SafeBoost. Datos copiados a {new_home} el {stamp}. "
        "Esta carpeta ya no se usa y puedes borrarla.\n",
        encoding="utf-8",
    )
    _stop_old_tray(old_home)
    tasks: list[str] = []
    if runner is not None:
        tasks = migrate_tasks(runner)
    log.info("safetrim_migrated", extra={"from": str(old_home), "copied": copied, "tasks": tasks})
    return MigrationResult(True, "datos de SafeTrim copiados", copied)
