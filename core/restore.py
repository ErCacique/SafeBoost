"""Puntos de restauración del sistema."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from core.constants import (
    RESTORE_FREQUENCY_VALUE,
    RESTORE_POINT_TYPE,
    RSTRUI_EXE,
    SYSTEM_RESTORE_KEY,
    TIMEOUT_RESTORE_POINT,
)
from core.logger import get_logger
from core.process import CommandError, Runner, ps_quote
from core.registry import Registry, RegValue

log = get_logger("restore")


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    message: str
    sequence: int | None = None


class RestoreManager:
    def __init__(self, registry: Registry, runner: Runner, system_drive: str = "C:") -> None:
        self.registry = registry
        self.runner = runner
        self.system_drive = system_drive.rstrip("\\") + "\\"

    def protection_enabled(self) -> bool | None:
        """True/False si se pudo determinar; None si no."""
        # Windows pone RPSessionInterval=1 cuando la Protección del sistema está activa en algún
        # volumen y 0 cuando está desactivada en todos.
        value = self.registry.read("HKLM", SYSTEM_RESTORE_KEY, "RPSessionInterval")
        if value is None or not isinstance(value.data, int):
            return None
        return value.data != 0

    def enable_protection(self) -> RestoreResult:
        res = self.runner.powershell(f"Enable-ComputerRestore -Drive {ps_quote(self.system_drive)}")
        if res.ok:
            log.info("restore_protection_enabled", extra={"drive": self.system_drive})
            return RestoreResult(True, f"Protección del sistema activada en {self.system_drive}")
        return RestoreResult(False, f"No se pudo activar la protección: {res.error_text()}")

    def create(self, description: str) -> RestoreResult:
        """Crea un punto de restauración saltando el límite de uno cada 24 h y lo verifica."""
        previous = self.registry.read("HKLM", SYSTEM_RESTORE_KEY, RESTORE_FREQUENCY_VALUE)
        try:
            # Windows ignora en silencio Checkpoint-Computer si hubo otro punto en las últimas
            # 24 h; con frecuencia 0 se fuerza la creación. Se restaura el valor al terminar.
            self.registry.write(
                "HKLM", SYSTEM_RESTORE_KEY, RESTORE_FREQUENCY_VALUE, RegValue("REG_DWORD", 0)
            )
            before = self._latest_sequence()
            res = self.runner.powershell(
                f"Checkpoint-Computer -Description {ps_quote(description[:255])} "
                f"-RestorePointType {RESTORE_POINT_TYPE}",
                timeout=TIMEOUT_RESTORE_POINT,
            )
            if not res.ok:
                return RestoreResult(False, f"Checkpoint-Computer falló: {res.error_text()}")
            after = self._latest_sequence()
            if after is None or after == before:
                return RestoreResult(
                    False,
                    "No se creó el punto de restauración (¿Protección del sistema desactivada?)",
                )
            log.info("restore_point_created", extra={"sequence": after, "desc": description})
            return RestoreResult(True, f"Punto de restauración #{after} creado", after)
        except CommandError as exc:
            return RestoreResult(False, str(exc))
        finally:
            try:
                if previous is None:
                    self.registry.delete_value("HKLM", SYSTEM_RESTORE_KEY, RESTORE_FREQUENCY_VALUE)
                else:
                    self.registry.write(
                        "HKLM", SYSTEM_RESTORE_KEY, RESTORE_FREQUENCY_VALUE, previous
                    )
            except OSError as exc:
                log.warning("restore_frequency_reset_failed", extra={"err": str(exc)})

    def _latest_sequence(self) -> int | None:
        data = self.runner.powershell_json(
            "$p = Get-ComputerRestorePoint -ErrorAction SilentlyContinue | "
            "Sort-Object SequenceNumber | Select-Object -Last 1;"
            "if ($p) { [int]$p.SequenceNumber | ConvertTo-Json } else { 'null' }"
        )
        return int(data) if data is not None else None

    @staticmethod
    def open_system_restore() -> None:
        """Abre el asistente de Restaurar sistema de Windows."""
        if sys.platform != "win32":
            raise OSError("Solo disponible en Windows")
        subprocess.Popen([str(RSTRUI_EXE)])
