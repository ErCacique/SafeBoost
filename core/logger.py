"""Logging estructurado (JSON Lines) con salida a fichero rotativo y a una cola para la UI."""

from __future__ import annotations

import json
import logging
import queue
import shutil
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from core.constants import LOG_BACKUP_COUNT, LOG_DIR, LOG_FILE_NAME, LOG_MAX_BYTES

ROOT_LOGGER_NAME = "safetrim"

# Atributos estándar de LogRecord que no se vuelcan como campos estructurados.
_RESERVED = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None)).keys()
    | {"message", "asctime"}
)


class JsonFormatter(logging.Formatter):
    """Formatea cada registro como un objeto JSON en una línea."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class UiFormatter(logging.Formatter):
    """Formato legible para el log en vivo de la interfaz."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        tweak = getattr(record, "tweak", None)
        prefix = f"[{tweak}] " if tweak else ""
        return f"{ts} {record.levelname:<7} {prefix}{record.getMessage()}"


class QueueForwardHandler(logging.Handler):
    """Envía líneas formateadas a una cola que la UI consume desde el hilo principal."""

    def __init__(self, target: queue.Queue[str]) -> None:
        super().__init__()
        self.target = target
        self.setFormatter(UiFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.target.put_nowait(self.format(record))
        except queue.Full:
            # Si la UI no consume, se descarta antes que bloquear el hilo de trabajo.
            pass
        except Exception:  # noqa: BLE001 - contrato de logging.Handler
            self.handleError(record)


_ui_queue: queue.Queue[str] = queue.Queue(maxsize=10_000)


def setup_logging(log_dir: Path = LOG_DIR, level: int = logging.INFO) -> Path:
    """Configura el logger raíz de SafeTrim. Idempotente. Devuelve la ruta del fichero de log."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(level)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        file_handler = RotatingFileHandler(
            log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)
    if not any(isinstance(h, QueueForwardHandler) for h in root.handlers):
        root.addHandler(QueueForwardHandler(_ui_queue))
    root.propagate = False
    return log_file


def get_logger(name: str) -> logging.Logger:
    """Logger hijo de 'safetrim'. Usar extra={...} para campos estructurados."""
    if name.startswith(ROOT_LOGGER_NAME):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def ui_log_queue() -> queue.Queue[str]:
    return _ui_queue


def export_logs(destination: Path, log_dir: Path = LOG_DIR) -> Path:
    """Copia el log actual y sus rotaciones a destination (carpeta). Devuelve la carpeta creada."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = destination / f"SafeTrim-logs-{stamp}"
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(log_dir.glob(f"{LOG_FILE_NAME}*")):
        shutil.copy2(path, target / path.name)
    return target
