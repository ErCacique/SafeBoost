"""Une la vigilancia con el resto del programa: se ejecuta al abrir SafeTrim (en segundo plano)
y en el mantenimiento mensual. Separado de core.watch para que este no dependa de los handlers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from core.app import AppContext
from core.logger import get_logger
from core.metrics import last_boot, take_snapshot
from core.programs import list_programs
from core.watch import (
    WATCH_DIR,
    EventLog,
    HealthHistory,
    HealthRecord,
    StartupItem,
    StartupWatch,
    Trend,
    boot_trend,
)
from tweaks.startup import StartupManager

log = get_logger("monitor")


@dataclass
class WatchResult:
    new_startup: list[StartupItem] = field(default_factory=list)
    new_programs: list[StartupItem] = field(default_factory=list)
    trend: Trend | None = None


def startup_items(app: AppContext) -> list[StartupItem]:
    manager = StartupManager(app.registry, app.runner, app.engine.tasks, app.env)
    return [StartupItem(e.key, e.name) for e in manager.list() if e.enabled]


def refresh(app: AppContext, directory: Path = WATCH_DIR) -> WatchResult:
    """Detecta programas de inicio e instalados nuevos, guarda un registro de salud y calcula si
    el arranque ha empeorado. Cada parte es independiente: un fallo no impide las demás."""
    events = EventLog(directory)
    result = WatchResult()
    items: list[StartupItem] = []
    try:
        items = startup_items(app)
        result.new_startup = StartupWatch(directory, events).check(items)
    except Exception as exc:  # noqa: BLE001 - la vigilancia nunca debe romper el arranque
        log.warning("watch_startup_failed", extra={"err": str(exc)})
    try:
        programs = [StartupItem(p.key, p.name) for p in list_programs(app.registry)]
        result.new_programs = StartupWatch(
            directory, events, "programs_known.json", "program_installed"
        ).check(programs)
    except Exception as exc:  # noqa: BLE001
        log.warning("watch_programs_failed", extra={"err": str(exc)})
    try:
        boot = last_boot(app.runner)
        snap = take_snapshot(app.env.system_drive, cpu_interval=0)
        history = HealthHistory(directory)
        history.add(
            HealthRecord(
                when=datetime.now().isoformat(timespec="seconds"),
                boot_ms=boot.boot_ms if boot else None,
                boot_stamp=boot.timestamp if boot else "",
                ram_total=snap.ram_total,
                ram_used=snap.ram_used,
                disk_free=snap.disk_free,
                processes=snap.process_count,
                startup_count=len(items),
            )
        )
        result.trend = boot_trend(history.load(), events.all())
    except Exception as exc:  # noqa: BLE001
        log.warning("watch_history_failed", extra={"err": str(exc)})
    return result
