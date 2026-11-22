"""Gestor de programas de inicio (herramienta interactiva del nivel 2, fuera del catálogo).

Desactiva igual que el Administrador de tareas: con los valores StartupApproved, sin borrar
entradas ni mover archivos. Cada cambio se registra en una sesión, así que Deshacer funciona
igual que con los tweaks del catálogo.
"""

from __future__ import annotations

import os
import re
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.constants import (
    BOOT_DEGRADATION_EVENT_ID,
    DIAG_PERF_LOG,
    RUN_KEYS,
    STARTUP_APPROVED_KEYS,
)
from core.environment import EnvironmentInfo
from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote
from core.registry import Registry, RegValue
from core.session import Change, Session, TweakResult
from core.tasks import TaskManager

log = get_logger("tweaks.startup")

# Tareas de los programas de inicio retrasados (se crean al pulsar "Retrasar").
DELAYED_TASK_FOLDER = "\\SafeTrim\\Delayed\\"

Source = Literal["run", "run32", "folder", "task"]
Impact = Literal["alto", "medio", "bajo", "desconocido"]

PROFILE_LIST_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"
USER_STARTUP = Path("AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup")
COMMON_STARTUP = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / (
    "Microsoft/Windows/Start Menu/Programs/StartUp"
)

IMPACT_HIGH_MS = 1000
IMPACT_MEDIUM_MS = 300
IMPACT_MEDIUM_BYTES = 30 * 1024 * 1024
UPDATER_HINTS = ("update", "updater", "helper", "launcher", "tray", "agent")

# Diferencia en intervalos de 100 ns entre 1601-01-01 (FILETIME) y 1970-01-01 (epoch Unix).
_FILETIME_EPOCH_OFFSET = 116444736000000000

_EXE_RE = re.compile(r'^\s*"([^"]+)"|^\s*(\S+?\.(?:exe|bat|cmd|com|lnk))', re.IGNORECASE)


@dataclass
class StartupEntry:
    key: str
    name: str
    command: str
    source: Source
    scope: Literal["HKLM", "HKCU"]
    location: str
    enabled: bool
    impact: Impact = "desconocido"
    impact_detail: str = ""
    approved_path: str | None = None
    task_path: str | None = None

    @property
    def change_id(self) -> str:
        return f"startup.{re.sub(r'[^a-z0-9_]+', '_', self.key.lower()).strip('_')}"


def approved_value(enabled: bool) -> bytes:
    """Formato de 12 bytes de StartupApproved: marca (02 activo / 03 inactivo) + FILETIME."""
    if enabled:
        return b"\x02" + b"\x00" * 11
    filetime = int(time.time() * 10_000_000) + _FILETIME_EPOCH_OFFSET
    return b"\x03\x00\x00\x00" + struct.pack("<Q", filetime)


def is_approved_enabled(value: RegValue | None) -> bool:
    if value is None or not isinstance(value.data, bytes) or not value.data:
        return True
    # Bit 0 activado = desactivado por el usuario (03, 07...).
    return not value.data[0] & 1


def executable_from_command(command: str) -> Path | None:
    match = _EXE_RE.match(os.path.expandvars(command))
    if not match:
        return None
    return Path(match.group(1) or match.group(2))


class StartupManager:
    def __init__(
        self, registry: Registry, runner: Runner, tasks: TaskManager, env: EnvironmentInfo
    ) -> None:
        self.registry = registry
        self.runner = runner
        self.tasks = tasks
        self.env = env

    # ------------------------------------------------------------------ inventario

    def list(self) -> list[StartupEntry]:
        entries: list[StartupEntry] = []
        entries += self._run_entries()
        entries += self._folder_entries()
        entries += self._task_entries()
        degradation = self._degradation_by_file()
        for entry in entries:
            self._estimate_impact(entry, degradation)
        return sorted(entries, key=lambda e: (not e.enabled, e.name.lower()))

    def _run_entries(self) -> list[StartupEntry]:
        out = []
        for hive, path in RUN_KEYS:
            source: Source = "run32" if "WOW6432Node" in path else "run"
            approved = STARTUP_APPROVED_KEYS[source]
            for name, value in self.registry.values(hive, path).items():
                if not isinstance(value.data, str) or not value.data.strip():
                    continue
                state = self.registry.read(hive, approved, name)
                out.append(
                    StartupEntry(
                        key=f"{source}:{hive}:{name}",
                        name=name,
                        command=value.data,
                        source=source,
                        scope=hive,  # type: ignore[arg-type]
                        location=f"{hive}\\{path}",
                        enabled=is_approved_enabled(state),
                        approved_path=approved,
                    )
                )
        return out

    def _user_profile(self) -> Path:
        sid = self.env.interactive_sid
        if sid:
            value = self.registry.read("HKLM", f"{PROFILE_LIST_KEY}\\{sid}", "ProfileImagePath")
            if value is not None and isinstance(value.data, str):
                return Path(os.path.expandvars(value.data))
        return Path.home()

    def _folder_entries(self) -> list[StartupEntry]:
        out = []
        folders: list[tuple[Literal["HKLM", "HKCU"], Path]] = [
            ("HKCU", self._user_profile() / USER_STARTUP),
            ("HKLM", COMMON_STARTUP),
        ]
        approved = STARTUP_APPROVED_KEYS["folder"]
        for scope, folder in folders:
            if not folder.exists():
                continue
            for item in folder.iterdir():
                if item.name.lower() == "desktop.ini" or not item.is_file():
                    continue
                state = self.registry.read(scope, approved, item.name)
                out.append(
                    StartupEntry(
                        key=f"folder:{scope}:{item.name}",
                        name=item.stem,
                        command=str(item),
                        source="folder",
                        scope=scope,
                        location=str(folder),
                        enabled=is_approved_enabled(state),
                        approved_path=approved,
                    )
                )
        return out

    def _task_entries(self) -> list[StartupEntry]:
        try:
            rows = self.tasks.logon_tasks()
        except Exception as exc:  # noqa: BLE001 - el inventario parcial es mejor que ninguno
            log.warning("startup_tasks_failed", extra={"err": str(exc)})
            return []
        return [
            StartupEntry(
                key=f"task:{row['path']}",
                name=row["path"].rsplit("\\", 1)[-1],
                command=row.get("action", ""),
                source="task",
                scope="HKLM",
                location="Tareas programadas",
                enabled=row.get("state") != "Disabled",
                task_path=row["path"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------------ impacto

    def _degradation_by_file(self) -> dict[str, int]:
        """Eventos 101: apps que retrasaron el arranque. Nombre de archivo → peor retraso (ms)."""
        # try/catch: sin el registro o sin eventos, Get-WinEvent aborta el script (ver core.boot).
        script = (
            f"$ev = try {{ @(Get-WinEvent -LogName {ps_quote(DIAG_PERF_LOG)} "
            f"-FilterXPath '*[System[EventID={BOOT_DEGRADATION_EVENT_ID}]]' -MaxEvents 200 "
            "-ErrorAction Stop) } catch { @() };"
            "@($ev | ForEach-Object { $x = [xml]$_.ToXml();"
            "$d = @{}; $x.Event.EventData.Data | ForEach-Object { $d[$_.Name] = $_.'#text' };"
            "@{file=$(if ($d['FileName']) { $d['FileName'] } else { $d['Name'] });"
            " ms=[int]$d['DegradationTime']} }) | ConvertTo-Json -Compress"
        )
        try:
            rows = as_list(self.runner.powershell_json(script))
        except CommandError:
            return {}
        out: dict[str, int] = {}
        for row in rows:
            name = Path(str(row.get("file") or "")).name.lower()
            if name:
                out[name] = max(out.get(name, 0), int(row.get("ms") or 0))
        return out

    @staticmethod
    def _estimate_impact(entry: StartupEntry, degradation: dict[str, int]) -> None:
        exe = executable_from_command(entry.command)
        if exe is None:
            entry.impact, entry.impact_detail = (
                "desconocido",
                "No se pudo identificar el ejecutable",
            )
            return
        delay = degradation.get(exe.name.lower())
        if delay:
            entry.impact = (
                "alto"
                if delay >= IMPACT_HIGH_MS
                else "medio"
                if delay >= IMPACT_MEDIUM_MS
                else "bajo"
            )
            entry.impact_detail = f"Windows registró un retraso de {delay} ms en el arranque"
            return
        try:
            size = exe.stat().st_size
        except OSError:
            entry.impact, entry.impact_detail = "desconocido", "Ejecutable no accesible"
            return
        if any(h in exe.name.lower() for h in UPDATER_HINTS):
            entry.impact, entry.impact_detail = "bajo", "Estimado: actualizador o proceso auxiliar"
        elif size >= IMPACT_MEDIUM_BYTES:
            entry.impact, entry.impact_detail = "medio", "Estimado por el tamaño del ejecutable"
        else:
            entry.impact, entry.impact_detail = "bajo", "Estimado por el tamaño del ejecutable"

    # ------------------------------------------------------------------ cambios

    def set_enabled(self, entry: StartupEntry, enabled: bool, session: Session) -> None:
        """Activa/desactiva una entrada y lo registra en `session` para poder deshacerlo."""
        if entry.enabled == enabled:
            return
        tid = entry.change_id
        if entry.source == "task" and entry.task_path:
            self.tasks.set_enabled(entry.task_path, enabled)
            session.changes.append(
                Change(tid, "task", {"path": entry.task_path}, entry.enabled, enabled)
            )
        elif entry.approved_path:
            value_name = entry.name if entry.source != "folder" else Path(entry.command).name
            before = self.registry.read(entry.scope, entry.approved_path, value_name)
            key_existed = self.registry.key_exists(entry.scope, entry.approved_path)
            new_value = RegValue("REG_BINARY", approved_value(enabled))
            self.registry.write(entry.scope, entry.approved_path, value_name, new_value)
            session.changes.append(
                Change(
                    tid,
                    "registry",
                    {
                        "hive": entry.scope,
                        "path": entry.approved_path,
                        "name": value_name,
                        "key_existed": key_existed,
                    },
                    before.to_json() if before else None,
                    new_value.to_json(),
                )
            )
        else:
            raise ValueError(f"Entrada de inicio sin mecanismo de activación: {entry.key}")
        entry.enabled = enabled
        verb = "activado" if enabled else "desactivado"
        session.results[tid] = TweakResult(tid, "applied", f"Inicio de {entry.name} {verb}")
        session.selected.append(tid)
        log.info("startup_toggled", extra={"entry": entry.key, "enabled": enabled})

    # ------------------------------------------------------------------ retrasar

    def delay(self, entry: StartupEntry, session: Session, user: str, seconds: int = 90) -> None:
        """Arranca el programa `seconds` después de iniciar sesión en vez de quitarlo: se
        desactiva la entrada original (StartupApproved) y se crea una tarea programada al
        iniciar sesión con retraso. Deshacer borra la tarea y reactiva la entrada."""
        if entry.source not in ("run", "run32", "folder") or not entry.enabled:
            raise ValueError(
                "Solo se pueden retrasar programas de inicio activos del registro o de la "
                "carpeta Inicio"
            )
        if not user:
            raise ValueError("No se conoce el usuario con sesión")
        exe = executable_from_command(entry.command)
        if exe is None:
            raise ValueError(f"No se reconoce el programa de: {entry.command}")
        if entry.source == "folder":
            program, args = "explorer.exe", f'"{entry.command}"'
        else:
            program = str(exe)
            args = entry.command.strip()
            args = args[len(f'"{exe}"') :] if args.startswith('"') else args[len(str(exe)) :]
            args = args.strip()
        task_name = re.sub(r'[\\/:*?"<>|]', "_", entry.name)[:100]
        self.set_enabled(entry, False, session)
        script = (
            f"$a = New-ScheduledTaskAction -Execute {ps_quote(program)}"
            + (f" -Argument {ps_quote(args)}" if args else "")
            + f"; $t = New-ScheduledTaskTrigger -AtLogOn -User {ps_quote(user)};"
            f" $t.Delay = {ps_quote(f'PT{seconds}S')};"
            f" $p = New-ScheduledTaskPrincipal -UserId {ps_quote(user)} -LogonType Interactive"
            " -RunLevel Limited;"
            " $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries"
            " -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0);"
            f" Register-ScheduledTask -TaskPath {ps_quote(DELAYED_TASK_FOLDER)}"
            f" -TaskName {ps_quote(task_name)} -Action $a -Trigger $t -Principal $p"
            " -Settings $s -Force | Out-Null"
        )
        result = self.runner.powershell(script)
        if not result.ok:
            raise ValueError(f"No se pudo crear la tarea retrasada: {result.error_text()}")
        session.changes.append(
            Change(
                entry.change_id,
                "task_created",
                {"folder": DELAYED_TASK_FOLDER, "name": task_name},
                None,
                True,
            )
        )
        session.results[entry.change_id] = TweakResult(
            entry.change_id, "applied", f"Inicio de {entry.name} retrasado {seconds} s"
        )
        log.info("startup_delayed", extra={"entry": entry.key, "seconds": seconds})
