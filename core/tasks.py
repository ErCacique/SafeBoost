"""Tareas programadas: consulta y activación/desactivación.

Se usa PowerShell (ScheduledTasks) en lugar de schtasks.exe porque la salida de schtasks está
localizada ("Deshabilitado", "Listo"...) y el enum State de PowerShell no.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote

log = get_logger("tasks")

TaskStatus = Literal["Ready", "Running", "Disabled", "Queued", "Unknown", "Missing"]


class TaskError(RuntimeError):
    pass


@dataclass(frozen=True)
class TaskInfo:
    path: str
    status: TaskStatus

    @property
    def exists(self) -> bool:
        return self.status != "Missing"

    @property
    def enabled(self) -> bool:
        return self.status not in ("Disabled", "Missing")


def split_task_path(full_path: str) -> tuple[str, str]:
    r"""'\Microsoft\Windows\X\Tarea' -> ('\Microsoft\Windows\X\', 'Tarea')."""
    full_path = "\\" + full_path.strip("\\")
    folder, _, name = full_path.rpartition("\\")
    return folder + "\\", name


class TaskManager:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        # Resultados de prefetch(): evita un PowerShell por tarea al detectar en bloque.
        self._cache: dict[str, TaskInfo] = {}

    def prefetch(self, paths: list[str]) -> None:
        """Consulta muchas tareas en un solo PowerShell y deja el resultado en caché."""
        unique = sorted({"\\" + p.strip("\\") for p in paths})
        if not unique:
            return
        items = ",".join(ps_quote(p) for p in unique)
        script = (
            f"$out = @{{}}; foreach ($p in @({items})) {{"
            " $i = $p.LastIndexOf('\\'); $folder = $p.Substring(0, $i + 1);"
            " $name = $p.Substring($i + 1);"
            " $t = Get-ScheduledTask -TaskPath $folder -TaskName $name"
            " -ErrorAction SilentlyContinue;"
            " $out[$p] = if ($t) { $t.State.ToString() } else { 'Missing' } };"
            " $out | ConvertTo-Json -Compress"
        )
        try:
            data = self.runner.powershell_json(script) or {}
        except CommandError as exc:
            # Sin prefetch se cae a consultas individuales: más lento, pero correcto.
            log.warning("tasks_prefetch_failed", extra={"err": str(exc)})
            return
        if not isinstance(data, dict):
            log.warning("tasks_prefetch_unexpected", extra={"type": type(data).__name__})
            return
        for path in unique:
            if path not in data:
                continue  # sin dato: query() hará la consulta individual
            status = data[path]
            if status not in ("Ready", "Running", "Disabled", "Queued", "Missing"):
                status = "Unknown"
            self._cache[path.lower()] = TaskInfo(path, status)

    def clear_cache(self) -> None:
        self._cache.clear()

    def query(self, full_path: str) -> TaskInfo:
        cached = self._cache.get(("\\" + full_path.strip("\\")).lower())
        if cached is not None:
            return TaskInfo(full_path, cached.status)
        folder, name = split_task_path(full_path)
        script = (
            f"$t = Get-ScheduledTask -TaskPath {ps_quote(folder)} -TaskName {ps_quote(name)} "
            "-ErrorAction SilentlyContinue;"
            "if ($t) { @{state=$t.State.ToString()} | ConvertTo-Json -Compress } "
            "else { @{state='Missing'} | ConvertTo-Json -Compress }"
        )
        try:
            data = self.runner.powershell_json(script) or {}
        except CommandError as exc:
            raise TaskError(str(exc)) from exc
        status = data.get("state", "Unknown")
        if status not in ("Ready", "Running", "Disabled", "Queued", "Missing"):
            status = "Unknown"
        return TaskInfo(full_path, status)

    def set_enabled(self, full_path: str, enabled: bool) -> None:
        self._cache.pop(("\\" + full_path.strip("\\")).lower(), None)
        folder, name = split_task_path(full_path)
        verb = "Enable-ScheduledTask" if enabled else "Disable-ScheduledTask"
        result = self.runner.powershell(
            f"{verb} -TaskPath {ps_quote(folder)} -TaskName {ps_quote(name)} | Out-Null"
        )
        if not result.ok:
            raise TaskError(f"{verb} {full_path}: {result.error_text()}")
        log.info("task_state_set", extra={"task": full_path, "enabled": enabled})

    def logon_tasks(self) -> list[dict[str, str]]:
        """Tareas no-Microsoft con disparador de inicio de sesión o arranque (gestor de inicio)."""
        script = (
            "Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' -and "
            "($_.Triggers | Where-Object { $_.CimClass.CimClassName -in "
            "@('MSFT_TaskLogonTrigger','MSFT_TaskBootTrigger') }) } | "
            "ForEach-Object { @{path=($_.TaskPath + $_.TaskName); state=$_.State.ToString(); "
            "action=(($_.Actions | ForEach-Object { $_.Execute }) -join ';')} } | "
            "ConvertTo-Json -Depth 3 -Compress"
        )
        try:
            return [dict(x) for x in as_list(self.runner.powershell_json(script))]
        except CommandError as exc:
            raise TaskError(str(exc)) from exc
