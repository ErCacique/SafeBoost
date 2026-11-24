"""Informes de error sin conexión: si algo falla, queda un informe legible para enviarlo.

Captura excepciones no controladas del proceso, de los hilos y de los callbacks de Tk. Escribe
APP_HOME/crashes/crash-<fecha>.txt con la traza, la versión y el sistema. No envía nada: el
usuario decide si lo exporta (Ajustes → Exportar log incluye los informes).
"""

from __future__ import annotations

import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType

from core.constants import APP_HOME, APP_VERSION
from core.logger import get_logger

log = get_logger("crash")

CRASH_DIR = APP_HOME / "crashes"
MAX_REPORTS = 20


def write_report(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
    where: str = "proceso",
    directory: Path | None = None,
) -> Path | None:
    directory = directory or CRASH_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        path = directory / f"crash-{stamp}.txt"
        text = (
            f"SafeBoost {APP_VERSION} · {datetime.now().isoformat(timespec='seconds')}\n"
            f"Dónde: {where}\n"
            f"Sistema: {platform.platform()} · Python {platform.python_version()}\n\n"
            + "".join(traceback.format_exception(exc_type, exc, tb))
        )
        path.write_text(text, encoding="utf-8")
        reports = sorted(directory.glob("crash-*.txt"))
        for old in reports[:-MAX_REPORTS]:
            old.unlink(missing_ok=True)
        log.error("crash_report", extra={"file": str(path), "where": where, "err": str(exc)})
        return path
    except OSError:
        return None


def install() -> None:
    """Engancha los manejadores globales (proceso e hilos). Tk se engancha en la ventana."""

    def process_hook(t: type[BaseException], e: BaseException, tb: TracebackType | None) -> None:
        write_report(t, e, tb, "proceso")
        sys.__excepthook__(t, e, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            name = args.thread.name if args.thread else "?"
            write_report(args.exc_type, args.exc_value, args.exc_traceback, f"hilo {name}")

    sys.excepthook = process_hook
    threading.excepthook = thread_hook


def reports(directory: Path | None = None) -> list[Path]:
    directory = directory or CRASH_DIR
    return sorted(directory.glob("crash-*.txt"), reverse=True) if directory.exists() else []
