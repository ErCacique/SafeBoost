"""Ejecución de procesos externos (PowerShell, sc, reg, schtasks...) con timeout y sin consola."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core.constants import POWERSHELL_EXE, SYSTEM32, TIMEOUT_DEFAULT, TIMEOUT_POWERSHELL
from core.logger import get_logger

log = get_logger("process")

CREATE_NO_WINDOW = 0x08000000

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
    """Implementación real basada en subprocess."""

    def run(
        self, args: list[str], timeout: int = TIMEOUT_DEFAULT, encoding: str | None = None
    ) -> CommandResult:
        if not args:
            raise ValueError("args vacío")
        log.debug("exec", extra={"cmd": args[0], "argv": args[1:]})
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NO_WINDOW
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


def ps_quote(value: str) -> str:
    """Literal de cadena PowerShell entre comillas simples (escapa comillas simples)."""
    return "'" + value.replace("'", "''") + "'"


def as_list(value: Any) -> list[Any]:
    """ConvertTo-Json devuelve un objeto suelto si solo hay un elemento; normaliza a lista."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
