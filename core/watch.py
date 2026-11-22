"""Vigilancia: que el equipo no vuelva a degradarse sin que nadie se entere.

- Programas de inicio nuevos desde la última vez que se abrió SafeTrim.
- Historial de salud (arranque, RAM, disco, programas de inicio) para ver cuándo empeoró.
- Foto del sistema antes de instalar algo y comparación después.
- Mantenimiento mensual programado (opcional) con su informe.

Todo se guarda en APP_HOME/watch como JSON legible. Las funciones de análisis son puras.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.constants import APP_HOME, SAFETRIM_TASK_FOLDER, SERVICES_KEY
from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote
from core.programs import list_programs
from core.registry import Registry

log = get_logger("watch")

WATCH_DIR = APP_HOME / "watch"
HISTORY_MAX = 400  # ~un año de arranques diarios
TREND_RECENT = 3
TREND_BASELINE = 7
TREND_MIN_DELTA_MS = 15_000
TREND_MIN_RATIO = 1.3
MAINTENANCE_TASK = "Maintenance"
MAINTENANCE_CLEANUPS = ("cleanup.temp_user", "cleanup.temp_windows", "cleanup.thumbnails")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- eventos


class EventLog:
    """Qué ha pasado en el equipo (programa de inicio nuevo, mantenimiento…), con fecha."""

    def __init__(self, directory: Path = WATCH_DIR) -> None:
        self.path = directory / "events.jsonl"

    def add(self, kind: str, text: str, when: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"when": when or _now(), "kind": kind, "text": text}) + "\n")

    def all(self) -> list[dict[str, str]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


# --------------------------------------------------------------------------- programas de inicio


@dataclass(frozen=True)
class StartupItem:
    key: str
    name: str


class StartupWatch:
    """Compara los elementos actuales con los conocidos la última vez (por defecto, programas de
    inicio activos; con otro nombre y tipo sirve para los programas instalados)."""

    def __init__(
        self,
        directory: Path = WATCH_DIR,
        events: EventLog | None = None,
        name: str = "startup_known.json",
        kind: str = "startup_added",
    ) -> None:
        self.path = directory / name
        self.kind = kind
        self.events = events or EventLog(directory)

    def check(self, current: Iterable[StartupItem]) -> list[StartupItem]:
        """Devuelve los nuevos y los da por conocidos. La primera vez solo crea la referencia."""
        current = list(current)
        known = _read_json(self.path, None)
        _write_json(self.path, sorted({i.key for i in current}))
        if known is None:
            return []
        new = [i for i in current if i.key not in set(known)]
        for item in new:
            self.events.add(self.kind, item.name)
        return new


# --------------------------------------------------------------------------- historial de salud


@dataclass
class HealthRecord:
    when: str
    boot_ms: int | None
    boot_stamp: str  # instante del arranque medido: evita guardar dos veces el mismo
    ram_total: int
    ram_used: int
    disk_free: int
    processes: int
    startup_count: int


class HealthHistory:
    def __init__(self, directory: Path = WATCH_DIR) -> None:
        self.path = directory / "history.json"

    def load(self) -> list[HealthRecord]:
        raw = _read_json(self.path, [])
        out = []
        for item in raw if isinstance(raw, list) else []:
            try:
                out.append(HealthRecord(**item))
            except TypeError:
                continue
        return out

    def add(self, record: HealthRecord) -> bool:
        """Un registro por arranque (o por día si no se conoce el arranque)."""
        records = self.load()
        key = record.boot_stamp or record.when[:10]
        if any((r.boot_stamp or r.when[:10]) == key for r in records):
            return False
        records.append(record)
        _write_json(self.path, [asdict(r) for r in records[-HISTORY_MAX:]])
        return True


@dataclass
class Trend:
    since: str  # fecha (YYYY-MM-DD) desde la que empeoró
    before_ms: int
    after_ms: int
    causes: list[str] = field(default_factory=list)  # eventos cercanos a esa fecha

    @property
    def delta_ms(self) -> int:
        return self.after_ms - self.before_ms


def boot_trend(records: list[HealthRecord], events: list[dict[str, str]]) -> Trend | None:
    """¿Arranca claramente más lento últimamente? Mediana de los últimos arranques frente a la
    de los anteriores; si empeoró, busca qué se instaló o añadió al inicio por esas fechas."""
    boots = [r for r in records if r.boot_ms]
    if len(boots) < TREND_RECENT + 3:
        return None
    recent = boots[-TREND_RECENT:]
    baseline = boots[-(TREND_RECENT + TREND_BASELINE) : -TREND_RECENT]
    after = int(statistics.median(r.boot_ms or 0 for r in recent))
    before = int(statistics.median(r.boot_ms or 0 for r in baseline))
    if after - before < TREND_MIN_DELTA_MS or after < before * TREND_MIN_RATIO:
        return None
    # Primer arranque del tramo lento: el primero por encima del punto medio a partir del cual
    # ya no se vuelve a la normalidad (la mediana de lo que sigue también está por encima).
    threshold = (before + after) / 2
    first = len(boots) - TREND_RECENT
    for i in range(max(len(boots) - TREND_RECENT - TREND_BASELINE, 1), len(boots)):
        rest = [r.boot_ms or 0 for r in boots[i:]]
        if (boots[i].boot_ms or 0) >= threshold and statistics.median(rest) >= threshold:
            first = i
            break
    since = boots[first].when[:10]
    start = boots[first - 1].when[:10]  # último arranque normal: la causa está entre ambos
    causes = [
        e["text"]
        for e in events
        if e.get("kind") in ("startup_added", "program_installed")
        and start <= str(e.get("when", ""))[:10] <= since
    ]
    return Trend(since, before, after, causes)


@dataclass
class Improvement:
    boot_before: int | None
    boot_after: int | None
    ram_before: int
    ram_after: int
    startup_before: int
    startup_after: int


def improvement_summary(records: list[HealthRecord], since: str) -> Improvement | None:
    """Medianas antes y después de la primera sesión aplicada (`since`, ISO). Para decir
    "desde que usas SafeTrim: arranque 134 s → 60 s, 11 → 5 programas de inicio"."""
    before = [r for r in records if r.when < since]
    after = [r for r in records if r.when >= since]
    if len(before) < 2 or len(after) < 2:
        return None

    def med(items: list[HealthRecord], attr: str) -> int | None:
        values = [getattr(r, attr) for r in items if getattr(r, attr)]
        return int(statistics.median(values)) if values else None

    return Improvement(
        med(before, "boot_ms"),
        med(after, "boot_ms"),
        med(before, "ram_used") or 0,
        med(after, "ram_used") or 0,
        med(before, "startup_count") or 0,
        med(after, "startup_count") or 0,
    )


# --------------------------------------------------------------------------- foto antes/después


def take_snapshot(registry: Registry, runner: Runner, startup: Iterable[StartupItem]) -> dict:
    """Servicios (con tipo de inicio), tareas programadas, programas de inicio e instalados."""
    services: dict[str, str] = {}
    for name in registry.subkeys("HKLM", SERVICES_KEY):
        path = f"{SERVICES_KEY}\\{name}"
        kind = registry.read("HKLM", path, "Type")
        start = registry.read("HKLM", path, "Start")
        # Solo servicios Win32 (0x10 propio, 0x20 compartido): los drivers no interesan aquí.
        if kind is None or start is None or not int(str(kind.data or 0)) & 0x30:
            continue
        services[name] = {0: "boot", 1: "system", 2: "auto", 3: "manual", 4: "disabled"}.get(
            int(str(start.data or 0)), str(start.data)
        )
    try:
        tasks = sorted(
            str(t)
            for t in as_list(
                runner.powershell_json(
                    "@(Get-ScheduledTask | ForEach-Object { $_.TaskPath + $_.TaskName })"
                    " | ConvertTo-Json -Compress"
                )
            )
        )
    except CommandError as exc:
        log.warning("snapshot_tasks_failed", extra={"err": str(exc)})
        tasks = []
    return {
        "taken": _now(),
        "services": services,
        "tasks": tasks,
        "startup": {i.key: i.name for i in startup},
        "programs": {p.key: p.name for p in list_programs(registry)},
    }


@dataclass
class SnapshotDiff:
    programs_added: list[str] = field(default_factory=list)
    programs_removed: list[str] = field(default_factory=list)
    startup_added: list[str] = field(default_factory=list)
    services_added: list[str] = field(default_factory=list)
    services_changed: list[str] = field(default_factory=list)
    tasks_added: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not any(asdict(self).values())


def diff_snapshots(before: dict, after: dict) -> SnapshotDiff:
    def added(key: str) -> list[str]:
        old, new = before.get(key) or {}, after.get(key) or {}
        if isinstance(new, list):
            return sorted(set(new) - set(old))
        return sorted(new[k] for k in new.keys() - old.keys())

    old_services, new_services = before.get("services") or {}, after.get("services") or {}
    return SnapshotDiff(
        programs_added=added("programs"),
        programs_removed=sorted(
            (before.get("programs") or {})[k]
            for k in (before.get("programs") or {}).keys() - (after.get("programs") or {}).keys()
        ),
        startup_added=added("startup"),
        services_added=sorted(new_services.keys() - old_services.keys()),
        services_changed=sorted(
            f"{name}: {old_services[name]} → {new_services[name]}"
            for name in new_services.keys() & old_services.keys()
            if new_services[name] != old_services[name]
        ),
        tasks_added=added("tasks"),
    )


class SnapshotStore:
    def __init__(self, directory: Path = WATCH_DIR) -> None:
        self.path = directory / "install_snapshot.json"

    def save(self, snapshot: dict) -> None:
        _write_json(self.path, snapshot)

    def load(self) -> dict | None:
        data = _read_json(self.path, None)
        return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- mantenimiento mensual


@dataclass
class MaintenanceReport:
    when: str
    freed_bytes: int = 0
    drift: list[str] = field(default_factory=list)
    new_startup: list[str] = field(default_factory=list)
    error: str = ""
    seen: bool = False  # el usuario ya lo vio en el Dashboard


class MaintenanceStore:
    def __init__(self, directory: Path = WATCH_DIR) -> None:
        self.path = directory / "maintenance.json"

    def save(self, report: MaintenanceReport) -> None:
        _write_json(self.path, asdict(report))

    def load(self) -> MaintenanceReport | None:
        data = _read_json(self.path, None)
        try:
            return MaintenanceReport(**data) if isinstance(data, dict) else None
        except TypeError:
            return None

    def mark_seen(self) -> None:
        report = self.load()
        if report and not report.seen:
            report.seen = True
            self.save(report)


def schedule_maintenance(runner: Runner, command: list[str], user: str) -> bool:
    """Cada 4 semanas, como el usuario con sesión y con privilegios elevados (sin contraseña:
    solo se ejecuta si ha iniciado sesión). Si el equipo estaba apagado, se hace al encenderlo."""
    exe, *args = [*command, "--maintenance"]
    script = (
        f"$a = New-ScheduledTaskAction -Execute {ps_quote(exe)}"
        + (f" -Argument {ps_quote(' '.join(args))};" if args else ";")
        + "$t = New-ScheduledTaskTrigger -Weekly -WeeksInterval 4 -DaysOfWeek Sunday -At 12:00;"
        f"$p = New-ScheduledTaskPrincipal -UserId {ps_quote(user)} -LogonType Interactive"
        " -RunLevel Highest;"
        "$s = New-ScheduledTaskSettingsSet -StartWhenAvailable"
        " -ExecutionTimeLimit (New-TimeSpan -Minutes 30);"
        f"Register-ScheduledTask -TaskPath {ps_quote(SAFETRIM_TASK_FOLDER)}"
        f" -TaskName {ps_quote(MAINTENANCE_TASK)} -Action $a -Trigger $t -Principal $p"
        " -Settings $s -Force | Out-Null"
    )
    result = runner.powershell(script)
    if not result.ok:
        log.warning("maintenance_task_failed", extra={"err": result.error_text()})
    return result.ok


def remove_maintenance(runner: Runner) -> None:
    runner.powershell(
        f"Unregister-ScheduledTask -TaskPath {ps_quote(SAFETRIM_TASK_FOLDER)}"
        f" -TaskName {ps_quote(MAINTENANCE_TASK)} -Confirm:$false -ErrorAction SilentlyContinue"
    )
