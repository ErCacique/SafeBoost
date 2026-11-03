"""Punto de entrada de WinTune.

Uso:
    python main.py           Windows, consola elevada (se autoeleva si hace falta)
    python main.py --demo    Entorno simulado; funciona en cualquier SO y no toca el sistema
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import subprocess
import sys

from core.constants import APP_NAME, APP_VERSION
from core.environment import is_admin
from core.logger import get_logger, setup_logging


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=APP_NAME, description="Optimización reversible de Windows"
    )
    parser.add_argument("--demo", action="store_true", help="entorno simulado, sin cambios reales")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="comprueba catálogo y handlers dentro del ejecutable y sale (código 0 = OK)",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser.parse_args(argv)


def _relaunch_elevated(argv: list[str]) -> bool:
    """Relanza el proceso con UAC. El .exe ya lo pide por manifest; esto cubre `python main.py`."""
    if getattr(sys, "frozen", False):
        executable, params = sys.executable, argv
    else:
        executable, params = sys.executable, [sys.argv[0], *argv]
    # ShellExecuteW devuelve > 32 si consiguió lanzar el proceso.
    rc = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", executable, subprocess.list2cmdline(params), None, 1
    )
    return int(rc) > 32


def self_test() -> int:
    """Verifica que el binario incluye el catálogo y todos los handlers que referencia.

    Los handlers se importan dinámicamente, así que un fallo de empaquetado solo aparecería
    al aplicar un tweak concreto; esto lo detecta en el pipeline de release.
    """
    from core.catalog import Catalog
    from core.context import HandlerError, resolve_handler

    try:
        catalog = Catalog.load()
        refs = {
            op["ref"]
            for tweak in catalog.tweaks
            for op in (*tweak.apply, *tweak.revert, *tweak.detect)
            if op["op"] == "handler"
        } | {t.requires["check"] for t in catalog.tweaks if t.requires.get("check")}
        for ref in sorted(refs):
            resolve_handler(ref)
        import customtkinter  # noqa: F401

        import tweaks.startup  # noqa: F401
    except (HandlerError, ImportError, OSError, ValueError) as exc:
        if sys.stderr:
            print(f"self-test FALLÓ: {exc}", file=sys.stderr)
        return 1
    if sys.stdout:
        print(f"self-test OK: {len(catalog.tweaks)} tweaks, {len(refs)} handlers")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)
    if args.self_test:
        return self_test()

    if not args.demo:
        if sys.platform != "win32":
            print(f"{APP_NAME} solo funciona en Windows. Usa --demo para ver la interfaz.")
            return 2
        if not is_admin():
            return 0 if _relaunch_elevated(argv) else 1

    # Imports diferidos: la UI y el settings tocan disco y Tk solo cuando de verdad arrancan.
    import customtkinter as ctk

    from core.app import AppContext, build_context
    from core.settings import Settings
    from ui.app import MainWindow
    from ui.theme import COLOR_THEME

    settings = Settings.load()
    setup_logging(level=getattr(logging, settings.log_level, logging.INFO))
    log = get_logger("main")
    log.info("start", extra={"version": APP_VERSION, "demo": args.demo})

    ctk.set_appearance_mode(settings.appearance)
    ctk.set_default_color_theme(COLOR_THEME)

    def builder() -> AppContext:
        if args.demo:
            from core.demo import DemoRunner, demo_environment, demo_registry

            return build_context(
                settings=settings,
                backend=demo_registry(),
                runner=DemoRunner(),
                env=demo_environment(),
            )
        return build_context(settings=settings)

    window = MainWindow(builder)
    window.mainloop()
    log.info("exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
