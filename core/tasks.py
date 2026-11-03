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

    def query(self, full_path: str) -> TaskInfo:
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
