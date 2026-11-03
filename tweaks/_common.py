"""Utilidades compartidas por los handlers."""

from __future__ import annotations

import os
import re
from pathlib import Path

from core.constants import ALLOWED_COMMAND_EXES
from core.context import HandlerContext, HandlerError
from core.process import as_list

GUID_RE = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")

PROFILE_LIST_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"


def user_profile_dir(ctx: HandlerContext) -> Path:
    """Carpeta de perfil del usuario interactivo (no la de la cuenta elevada)."""
    sid = ctx.env.interactive_sid
    if sid:
        value = ctx.registry.read("HKLM", f"{PROFILE_LIST_KEY}\\{sid}", "ProfileImagePath")
        if value is not None and isinstance(value.data, str):
            return Path(os.path.expandvars(value.data))
    return Path.home()


def user_local_appdata(ctx: HandlerContext) -> Path:
    return user_profile_dir(ctx) / "AppData" / "Local"


def run_tool(ctx: HandlerContext, exe: str, args: list[str], what: str) -> str:
    """Ejecuta powercfg/netsh (lista blanca) o lo planifica en dry-run."""
    ctx.guard.check_command(exe)
    return ctx.run_checked([str(ALLOWED_COMMAND_EXES[exe]), *args], what)


def ps_json(ctx: HandlerContext, script: str) -> list[dict]:
    try:
        return [dict(x) for x in as_list(ctx.runner.powershell_json(script))]
    except Exception as exc:
        raise HandlerError(str(exc)) from exc


def ps_run(ctx: HandlerContext, script: str, what: str) -> None:
    """Ejecuta un script de PowerShell que modifica el sistema, o lo planifica en dry-run."""
    if ctx.dry_run:
        ctx.plan(what)
        return
    result = ctx.runner.powershell(script)
    if not result.ok:
        raise HandlerError(f"{what}: {result.error_text()}")
