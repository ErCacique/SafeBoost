"""Ejecución de procesos externos (PowerShell, sc, reg, schtasks...) con timeout y sin consola."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.constants import (
    POWERSHELL_EXE,
    POWERSHELL_MAX_CONCURRENT,
    SYSTEM32,
    TIMEOUT_DEFAULT,
    TIMEOUT_POWERSHELL,
)
from core.logger import get_logger

log = get_logger("process")

CREATE_NO_WINDOW = 0x08000000
# Los procesos hijos (PowerShell, sc, reg...) no compiten con la interfaz ni con lo que el
# usuario esté haciendo: en un equipo flojo, la diferencia entre "va a tirones" y "va bien".
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

# Compartido por todos los SubprocessRunner: el límite es del equipo, no de cada instancia.
_POWERSHELL_SLOTS = threading.BoundedSemaphore(POWERSHELL_MAX_CONCURRENT)

# Las herramientas de consola de Windows escriben en la página de códigos OEM (p. ej. cp850).
_CONSOLE_ENCODING = "oem" if sys.platform == "win32" else "utf-8"

# Fuerza UTF-8 en la salida de PowerShell 5.1 para que tildes y ñ lleguen intactas.
_PS_PRELUDE = (
    "$ErrorActionPreference='Stop';"
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
    "$ProgressPreference='SilentlyContinue';"
)


class CommandError(RuntimeError):
    """Un comando terminó con error o no se pudo ejecutar."""

    def __init__(self, message: str, result: CommandResult | None = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def error_text(self) -> str:
        text = (self.stderr or self.stdout).strip()
        return text.splitlines()[-1] if text else f"código de salida {self.returncode}"


class Runner(Protocol):
    """Interfaz inyectable (los tests usan un FakeRunner)."""

    def run(
        self, args: list[str], timeout: int = TIMEOUT_DEFAULT, encoding: str | None = None
    ) -> CommandResult: ...

    def powershell(self, script: str, timeout: int = TIMEOUT_POWERSHELL) -> CommandResult: ...

    def powershell_json(self, script: str, timeout: int = TIMEOUT_POWERSHELL) -> Any: ...


def resolve_exe(name: str) -> str:
    """Resuelve un ejecutable de sistema contra System32 para evitar secuestro por PATH."""
    candidate = SYSTEM32 / name
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    return name


class SubprocessRunner:
    """Implementación real basada en subprocess.

    `low_priority` lanza los procesos hijos por debajo de lo normal. Durante la detección del
    arranque se desactiva: con la CPU ocupada (p. ej. Windows Update), una prioridad baja deja
    esas consultas al final de la cola y el usuario espera más.
    """

    def __init__(self, low_priority: bool = True) -> None:
        self.low_priority = low_priority

    def run(
        self, args: list[str], timeout: int = TIMEOUT_DEFAULT, encoding: str | None = None
    ) -> CommandResult:
        if not args:
            raise ValueError("args vacío")
        log.debug("exec", extra={"cmd": args[0], "argv": args[1:]})
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NO_WINDOW | (
                BELOW_NORMAL_PRIORITY_CLASS if self.low_priority else 0
            )
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                timeout=timeout,
                check=False,
                encoding=encoding or _CONSOLE_ENCODING,
                errors="replace",
                stdin=subprocess.DEVNULL,
                **kwargs,
            )
        except FileNotFoundError as exc:
            raise CommandError(f"No se encontró el ejecutable: {args[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandError(f"Tiempo agotado ({timeout}s): {Path(args[0]).name}") from exc
        result = CommandResult(tuple(args), proc.returncode, proc.stdout or "", proc.stderr or "")
        if not result.ok:
            log.debug(
                "exec_failed",
                extra={"cmd": args[0], "rc": result.returncode, "err": result.error_text()},
            )
        return result

    def powershell(self, script: str, timeout: int = TIMEOUT_POWERSHELL) -> CommandResult:
        args = [
            str(POWERSHELL_EXE) if POWERSHELL_EXE.exists() else "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _PS_PRELUDE + script,
        ]
        with _POWERSHELL_SLOTS:
            return self.run(args, timeout=timeout, encoding="utf-8")

    def powershell_json(self, script: str, timeout: int = TIMEOUT_POWERSHELL) -> Any:
        """Ejecuta script y parsea la salida como JSON (el script debe acabar en ConvertTo-Json)."""
        result = self.powershell(script, timeout=timeout)
        if not result.ok:
            raise CommandError(f"PowerShell falló: {result.error_text()}", result)
        text = result.stdout.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise CommandError(f"Salida JSON inválida de PowerShell: {text[:200]}", result) from exc


# PowerShell acepta como comilla simple también las tipográficas ‘ ’ ‚ ‛: si no se escapan, un
# nombre como «Spotify’; Remove-Item …» cerraría la cadena e inyectaría órdenes (con permisos de
# administrador). Cada una se duplica, que es el escape que PowerShell entiende para todas.
_PS_SINGLE_QUOTES = ("'", "\u2018", "\u2019", "\u201a", "\u201b")


def ps_quote(value: str) -> str:
    """Literal de cadena PowerShell entre comillas simples, seguro para cualquier texto."""
    for quote in _PS_SINGLE_QUOTES:
        value = value.replace(quote, quote * 2)
    return "'" + value + "'"


def as_list(value: Any) -> list[Any]:
    """ConvertTo-Json devuelve un objeto suelto si solo hay un elemento; normaliza a lista."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
