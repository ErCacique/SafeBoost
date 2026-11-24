"""Gestión de paquetes AppX: inventario, eliminación (instalado + aprovisionado) y reinstalación."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from core.constants import (
    PROTECTED_APPX_PREFIXES,
    SAFEBOOST_TASK_FOLDER,
    TIMEOUT_APPX,
    TIMEOUT_WINGET,
)
from core.logger import get_logger
from core.process import CommandError, Runner, as_list, ps_quote

log = get_logger("appx")


class AppxError(RuntimeError):
    pass


def is_protected_package(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in PROTECTED_APPX_PREFIXES)


@dataclass
class AppxInventory:
    """Nombres de paquetes instalados (cualquier usuario) y aprovisionados en la imagen."""

    installed: dict[str, list[str]] = field(default_factory=dict)  # Name -> [PackageFullName]
    provisioned: dict[str, list[str]] = field(default_factory=dict)  # DisplayName -> [PackageName]

    def present(self, name: str) -> bool:
        key = name.lower()
        return key in self.installed or key in self.provisioned


class AppxManager:
    """Gestión de AppX.

    `user_sid`: SID del usuario interactivo, para el reintento por usuario al eliminar.
    `run_as`: cuenta del usuario interactivo si NO es la que ejecuta SafeBoost elevado; en ese
    caso la reinstalación con winget se lanza en su sesión (las apps de la Store son por
    usuario: instalarlas desde la cuenta elevada las dejaría en el perfil equivocado).
    """

    def __init__(
        self, runner: Runner, user_sid: str | None = None, run_as: str | None = None
    ) -> None:
        self.runner = runner
        self.user_sid = user_sid
        self.run_as = run_as
        self._inventory: AppxInventory | None = None
        self._notes: list[str] = []

    def pop_notes(self) -> list[str]:
        """Avisos de la última operación (p. ej. eliminación solo para un usuario)."""
        notes, self._notes = self._notes, []
        return notes

    def inventory(self, refresh: bool = False) -> AppxInventory:
        """Una sola consulta a PowerShell para todo el catálogo (Get-AppxPackage es lento)."""
        if self._inventory is not None and not refresh:
            return self._inventory
        script = (
            "$i = @(Get-AppxPackage -AllUsers | Select-Object Name,PackageFullName);"
            "$p = @(Get-AppxProvisionedPackage -Online | Select-Object DisplayName,PackageName);"
            "@{installed=$i; provisioned=$p} | ConvertTo-Json -Depth 3 -Compress"
        )
        try:
            data = self.runner.powershell_json(script, timeout=TIMEOUT_APPX) or {}
        except CommandError as exc:
            raise AppxError(f"No se pudo inventariar AppX: {exc}") from exc
        inv = AppxInventory()
        for item in as_list(data.get("installed")):
            inv.installed.setdefault(item["Name"].lower(), []).append(item["PackageFullName"])
        for item in as_list(data.get("provisioned")):
            inv.provisioned.setdefault(item["DisplayName"].lower(), []).append(item["PackageName"])
        self._inventory = inv
        return inv

    def invalidate(self) -> None:
        self._inventory = None

    def remove(self, name: str, provisioned: bool) -> list[str]:
        """Elimina el paquete para todos los usuarios y, opcionalmente, de la imagen.

        Devuelve la lista de nombres completos eliminados. Lanza AppxError si algo falla.
        """
        if is_protected_package(name):
            raise AppxError(f"{name} está en la lista de protección")
        inv = self.inventory()
        removed: list[str] = []
        errors: list[str] = []
        for full_name in inv.installed.get(name.lower(), []):
            res = self.runner.powershell(
                f"Remove-AppxPackage -AllUsers -Package {ps_quote(full_name)}",
                timeout=TIMEOUT_APPX,
            )
            if res.ok:
                removed.append(full_name)
                continue
            # -AllUsers falla con algunos paquetes en Windows 10 (p. ej. 0x80070032, "la
            # solicitud no es compatible"). Se reintenta solo para el usuario interactivo.
            scope = f" -User {ps_quote(self.user_sid)}" if self.user_sid else ""
            retry = self.runner.powershell(
                f"Remove-AppxPackage -Package {ps_quote(full_name)}{scope}",
                timeout=TIMEOUT_APPX,
            )
            if retry.ok:
                removed.append(full_name)
                self._notes.append(
                    f"{name}: no se pudo eliminar para todos los usuarios "
                    f"({res.error_text()}); eliminado solo para el usuario actual"
                )
            else:
                errors.append(
                    f"{full_name}: {res.error_text()} (reintento por usuario: {retry.error_text()})"
                )
        if provisioned:
            for pkg in inv.provisioned.get(name.lower(), []):
                res = self.runner.powershell(
                    "Remove-AppxProvisionedPackage -Online "
                    f"-PackageName {ps_quote(pkg)} | Out-Null",
                    timeout=TIMEOUT_APPX,
                )
                if res.ok:
                    removed.append(pkg)
                else:
                    errors.append(f"{pkg}: {res.error_text()}")
        self.invalidate()
        if errors:
            raise AppxError("; ".join(errors))
        log.info("appx_removed", extra={"package": name, "items": removed})
        return removed

    @cached_property
    def winget_path(self) -> str | None:
        found = shutil.which("winget")
        if found:
            return found
        # Alias de ejecución de la Store; puede no estar en PATH en procesos elevados.
        candidate = Path.home() / "AppData" / "Local" / "Microsoft" / "WindowsApps" / "winget.exe"
        return str(candidate) if candidate.exists() else None

    @staticmethod
    def _winget_args(store_id: str | None, store_name: str) -> list[str]:
        selector = ["--id", store_id] if store_id else ["--name", store_name, "--exact"]
        return [
            "install",
            *selector,
            "--source",
            "msstore",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--silent",
            "--disable-interactivity",
        ]

    def reinstall(self, package: str, store_id: str | None, store_name: str) -> None:
        if self.run_as:
            self._reinstall_as_user(package, store_id, store_name)
            return
        winget = self.winget_path
        if winget is None:
            raise AppxError(
                "winget no está disponible; reinstala la app desde Microsoft Store: " + store_name
            )
        args = [winget, *self._winget_args(store_id, store_name)]
        try:
            result = self.runner.run(args, timeout=TIMEOUT_WINGET, encoding="utf-8")
        except CommandError as exc:
            raise AppxError(str(exc)) from exc
        if not result.ok:
            raise AppxError(f"winget no pudo reinstalar {store_name}: {result.error_text()}")
        self.invalidate()
        log.info("appx_reinstalled", extra={"package": package, "store_id": store_id})

    def _reinstall_as_user(self, package: str, store_id: str | None, store_name: str) -> None:
        """Ejecuta winget en la sesión del usuario interactivo mediante una tarea temporal.

        Con LogonType Interactive la tarea corre en la sesión ya abierta del usuario, sin
        necesitar su contraseña. Se espera a que termine, se lee LastTaskResult y se elimina.
        """
        if self.run_as is None:
            raise AppxError("No hay usuario interactivo para reinstalar en su sesión")
        name = f"Reinstall-{uuid.uuid4().hex[:8]}"
        winget_line = subprocess.list2cmdline(["winget", *self._winget_args(store_id, store_name)])
        script = (
            f"$path = {ps_quote(SAFEBOOST_TASK_FOLDER)}; $name = {ps_quote(name)};"
            "$a = New-ScheduledTaskAction -Execute 'cmd.exe' "
            f"-Argument {ps_quote('/c ' + winget_line)};"
            f"$p = New-ScheduledTaskPrincipal -UserId {ps_quote(self.run_as)} "
            "-LogonType Interactive -RunLevel Limited;"
            "Register-ScheduledTask -TaskPath $path -TaskName $name -Action $a -Principal $p "
            "-Force | Out-Null;"
            "try {"
            " Start-ScheduledTask -TaskPath $path -TaskName $name;"
            f" $deadline = (Get-Date).AddSeconds({TIMEOUT_WINGET});"
            " do { Start-Sleep -Seconds 2;"
            "  $state = (Get-ScheduledTask -TaskPath $path -TaskName $name).State;"
            "  $res = (Get-ScheduledTaskInfo -TaskPath $path -TaskName $name).LastTaskResult"
            " } while (($state -eq 'Running' -or $res -eq 267011) -and (Get-Date) -lt $deadline);"
            " @{state=[string]$state; result=[int64]$res} | ConvertTo-Json -Compress"
            "} finally {"
            " Unregister-ScheduledTask -TaskPath $path -TaskName $name -Confirm:$false"
            "}"
        )
        try:
            data = self.runner.powershell_json(script, timeout=TIMEOUT_WINGET + 60) or {}
        except CommandError as exc:
            raise AppxError(f"No se pudo lanzar winget en la sesión del usuario: {exc}") from exc
        if data.get("state") == "Running":
            raise AppxError(f"winget no terminó a tiempo al reinstalar {store_name}")
        if int(data.get("result", -1)) != 0:
            raise AppxError(
                f"winget no pudo reinstalar {store_name} en la sesión de {self.run_as} "
                f"(código {data.get('result')})"
            )
        self.invalidate()
        log.info(
            "appx_reinstalled",
            extra={"package": package, "store_id": store_id, "as_user": self.run_as},
        )
