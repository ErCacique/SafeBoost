"""Gestión de paquetes AppX: inventario, eliminación (instalado + aprovisionado) y reinstalación."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from core.constants import PROTECTED_APPX_PREFIXES, TIMEOUT_APPX, TIMEOUT_WINGET
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
    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self._inventory: AppxInventory | None = None

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
            else:
                errors.append(f"{full_name}: {res.error_text()}")
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

    def reinstall(self, package: str, store_id: str | None, store_name: str) -> None:
        winget = self.winget_path
        if winget is None:
            raise AppxError(
                "winget no está disponible; reinstala la app desde Microsoft Store: " + store_name
            )
        selector = ["--id", store_id] if store_id else ["--name", store_name, "--exact"]
        args = [
            winget,
            "install",
            *selector,
            "--source",
            "msstore",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--silent",
            "--disable-interactivity",
        ]
        try:
            result = self.runner.run(args, timeout=TIMEOUT_WINGET, encoding="utf-8")
        except CommandError as exc:
            raise AppxError(str(exc)) from exc
        if not result.ok:
            raise AppxError(f"winget no pudo reinstalar {store_name}: {result.error_text()}")
        self.invalidate()
        log.info("appx_reinstalled", extra={"package": package, "store_id": store_id})
