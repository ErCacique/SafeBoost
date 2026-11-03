"""Juegos: comprobación de soporte de HAGS (Hardware-Accelerated GPU Scheduling)."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from core.constants import MIN_BUILD_WIN10, TIMEOUT_DXDIAG
from core.context import HandlerContext
from core.logger import get_logger
from core.process import CommandError, resolve_exe

log = get_logger("tweaks.gaming")

# Las etiquetas del informe de texto de dxdiag no se traducen.
_HAGS_RE = re.compile(r"Hardware Scheduling:\s*Supported:\s*(True|False)", re.IGNORECASE)
_WDDM_RE = re.compile(r"Driver Model:\s*WDDM\s*(\d+)\.(\d+)", re.IGNORECASE)
MIN_WDDM = (2, 7)


def parse_dxdiag(text: str) -> bool:
    """True si alguna GPU declara soporte de HAGS (o, sin esa línea, WDDM >= 2.7)."""
    flags = [m.group(1).lower() == "true" for m in _HAGS_RE.finditer(text)]
    if flags:
        return any(flags)
    versions = [(int(a), int(b)) for a, b in _WDDM_RE.findall(text)]
    return any(v >= MIN_WDDM for v in versions)


def hags_supported(ctx: HandlerContext) -> bool:
    if ctx.env.build and ctx.env.build < MIN_BUILD_WIN10:
        return False
    with tempfile.TemporaryDirectory(prefix="safetrim-") as tmp:
        report = Path(tmp) / "dxdiag.txt"
        try:
            result = ctx.runner.run(
                [resolve_exe("dxdiag.exe"), "/whql:off", "/t", str(report)], timeout=TIMEOUT_DXDIAG
            )
        except CommandError as exc:
            log.warning("dxdiag_failed", extra={"err": str(exc)})
            return False
        if not result.ok or not report.exists():
            return False
        text = report.read_text(encoding="utf-8", errors="replace")
    supported = parse_dxdiag(text)
    log.info("hags_support", extra={"supported": supported})
    return supported
