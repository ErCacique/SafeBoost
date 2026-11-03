"""Métricas del sistema, tiempo de arranque, comparación antes/después y recomendación de perfil."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from core.constants import (
    BOOT_EVENT_ID,
    DIAG_PERF_LOG,
    METRICS_DIR,
    POST_REBOOT_DELAY,
    POST_REBOOT_TASK_NAME,
    RECOMMEND_HIGH_PROC_COUNT,
    RECOMMEND_LOW_RAM_GIB,
    WINTUNE_TASK_FOLDER,
)
from core.environment import EnvironmentInfo
from core.logger import get_logger
from core.process import CommandError, Runner, ps_quote, resolve_exe

log = get_logger("metrics")

GIB = 1024**3


@dataclass
class BootInfo:
    boot_ms: int
    timestamp: str


@dataclass
class Snapshot:
    taken: str
    ram_total: int
    ram_available: int
    ram_percent: float
    cpu_percent: float
    disk_total: int
    disk_free: int
    process_count: int
    boot: BootInfo | None = None

    @property
    def ram_used(self) -> int:
        return self.ram_total - self.ram_available

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        data = dict(data)
        boot = data.pop("boot", None)
        return cls(**data, boot=BootInfo(**boot) if boot else None)


def take_snapshot(system_drive: str = "C:", cpu_interval: float = 0.5) -> Snapshot:
    mem = psutil.virtual_memory()
    root = system_drive.rstrip("\\") + "\\"
    if not Path(root).exists():
        # Modo demo fuera de Windows: no hay unidad C:, se mide la raíz del sistema actual.
        root = str(Path.cwd().anchor or "/")
    disk = psutil.disk_usage(root)
    return Snapshot(
        taken=datetime.now().isoformat(timespec="seconds"),
        ram_total=mem.total,
        ram_available=mem.available,
        ram_percent=mem.percent,
        cpu_percent=psutil.cpu_percent(interval=cpu_interval),
        disk_total=disk.total,
        disk_free=disk.free,
        process_count=len(psutil.pids()),
    )


def last_boot(runner: Runner) -> BootInfo | None:
    """Duración del último arranque (evento 100 de Diagnostics-Performance). Requiere admin."""
    script = (
        f"$e = Get-WinEvent -LogName {ps_quote(DIAG_PERF_LOG)} "
        f"-FilterXPath '*[System[EventID={BOOT_EVENT_ID}]]' -MaxEvents 1 "
        "-ErrorAction SilentlyContinue;"
        "if ($e) { $x = [xml]$e.ToXml();"
        "$b = ($x.Event.EventData.Data | Where-Object { $_.Name -eq 'BootTime' }).'#text';"
        "@{boot_ms=[int]$b; timestamp=$e.TimeCreated.ToUniversalTime()"
        ".ToString('yyyy-MM-ddTHH:mm:ssZ')} | ConvertTo-Json -Compress }"
        " else { 'null' }"
    )
    try:
        data = runner.powershell_json(script)
    except CommandError as exc:
        log.warning("boot_time_unavailable", extra={"err": str(exc)})
        return None
    if not data:
        return None
    return BootInfo(int(data["boot_ms"]), str(data["timestamp"]))


def parse_timestamp(value: str) -> datetime:
    """ISO 8601 → datetime con zona. Sin zona se interpreta como hora local."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.astimezone()


def boot_after(boot: BootInfo, taken: str) -> bool:
    """True si el arranque se registró después del instante `taken`."""
    try:
        return parse_timestamp(boot.timestamp) > parse_timestamp(taken)
    except ValueError:
        return False


def local_time(value: str) -> str:
    """Marca de tiempo para mostrar al usuario, en hora local."""
    try:
        return parse_timestamp(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value[:16]


@dataclass
class Comparison:
    ram_freed: int
    process_delta: int
    disk_freed: int
    boot_delta_ms: int | None


def compare(before: Snapshot, after: Snapshot) -> Comparison:
    boot_delta = None
    if before.boot and after.boot and before.boot.timestamp != after.boot.timestamp:
        boot_delta = after.boot.boot_ms - before.boot.boot_ms
    return Comparison(
        ram_freed=after.ram_available - before.ram_available,
        process_delta=after.process_count - before.process_count,
        disk_freed=after.disk_free - before.disk_free,
        boot_delta_ms=boot_delta,
    )


class MetricsStore:
    """metrics/<session_id>.json con before, after y after_reboot."""

    def __init__(self, directory: Path = METRICS_DIR) -> None:
        self.directory = directory

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.json"

    def save(self, session_id: str, stage: str, snapshot: Snapshot) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(session_id)
        data = self.load_raw(session_id)
        data[stage] = snapshot.to_dict()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_raw(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get(self, session_id: str, stage: str) -> Snapshot | None:
        raw = self.load_raw(session_id).get(stage)
        return Snapshot.from_dict(raw) if raw else None

    def pending_reboot_sessions(self) -> list[str]:
        if not self.directory.exists():
            return []
        out = []
        for path in self.directory.glob("*.json"):
            data = self.load_raw(path.stem)
            if "after" in data and "after_reboot" not in data:
                out.append(path.stem)
        return sorted(out)

    def capture_post_reboot(self, runner: Runner, system_drive: str) -> list[str]:
        """Si hubo un arranque nuevo tras una sesión, guarda la medición 'after_reboot'."""
        boot = last_boot(runner)
        if boot is None:
            return []
        captured = []
        for sid in self.pending_reboot_sessions():
            after = self.get(sid, "after")
            # Solo cuenta un arranque registrado DESPUÉS de aplicar la sesión. Comparar con el
            # arranque previo fallaba si no había dato previo (capturaba sin reiniciar).
            if after is None or not boot_after(boot, after.taken):
                continue
            snap = take_snapshot(system_drive)
            snap.boot = boot
            self.save(sid, "after_reboot", snap)
            captured.append(sid)
        return captured


def recommend_profile(env: EnvironmentInfo, snap: Snapshot) -> tuple[int, str]:
    if env.managed:
        return 1, "Equipo gestionado por la empresa: solo cambios conservadores."
    low_ram = snap.ram_total < RECOMMEND_LOW_RAM_GIB * GIB
    busy = snap.process_count > RECOMMEND_HIGH_PROC_COUNT
    if env.chassis == "desktop" and (low_ram or busy):
        why = "poca RAM" if low_ram else "muchos procesos en segundo plano"
        return 3, f"Sobremesa con {why}: el perfil Máximo aporta una mejora apreciable."
    if env.chassis == "laptop":
        return 2, "Portátil: Equilibrado mejora el rendimiento sin penalizar la batería."
    return 2, "Equilibrado ofrece la mejor relación beneficio/riesgo para uso general."


def human_bytes(value: float) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{sign}{value:.1f} {unit}" if unit != "B" else f"{sign}{int(value)} B"
        value /= 1024
    return f"{sign}{value:.1f} TB"


# --------------------------------------------------------------------------- tarea tras reinicio


def schedule_post_reboot_capture(runner: Runner, command: list[str], home: Path) -> bool:
    """Programa una medición automática tras el próximo reinicio.

    Tarea de un uso como SYSTEM (leer el evento de arranque requiere privilegios), disparada
    al iniciar sesión con retraso. `command` lanza WinTune con --capture-boot; WINTUNE_HOME
    apunta al perfil del usuario porque SYSTEM tiene otro %LOCALAPPDATA%. La propia ejecución
    elimina la tarea cuando ya no quedan sesiones pendientes de medir.
    """
    inner = f'set "WINTUNE_HOME={home}" && ' + subprocess.list2cmdline([*command, "--capture-boot"])
    script = (
        f"$a = New-ScheduledTaskAction -Execute {ps_quote(resolve_exe('cmd.exe'))} "
        f"-Argument {ps_quote('/c ' + inner)};"
        f"$t = New-ScheduledTaskTrigger -AtLogOn; $t.Delay = {ps_quote(POST_REBOOT_DELAY)};"
        "$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount "
        "-RunLevel Highest;"
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-ExecutionTimeLimit (New-TimeSpan -Minutes 5);"
        f"Register-ScheduledTask -TaskPath {ps_quote(WINTUNE_TASK_FOLDER)} "
        f"-TaskName {ps_quote(POST_REBOOT_TASK_NAME)} -Action $a -Trigger $t -Principal $p "
        "-Settings $s -Force | Out-Null"
    )
    result = runner.powershell(script)
    if not result.ok:
        log.warning("post_reboot_task_failed", extra={"err": result.error_text()})
        return False
    log.info("post_reboot_task_scheduled")
    return True


def remove_post_reboot_task(runner: Runner) -> None:
    runner.powershell(
        f"Unregister-ScheduledTask -TaskPath {ps_quote(WINTUNE_TASK_FOLDER)} "
        f"-TaskName {ps_quote(POST_REBOOT_TASK_NAME)} -Confirm:$false "
        "-ErrorAction SilentlyContinue"
    )
