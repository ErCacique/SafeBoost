"""Punto de entrada de SafeTrim.

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
from typing import TYPE_CHECKING

from core.constants import APP_NAME, APP_VERSION
from core.environment import is_admin
from core.logger import get_logger, setup_logging

if TYPE_CHECKING:
    from core.migration import MigrationResult


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
    parser.add_argument(
        "--apply-selection",
        metavar="ARCHIVO",
        help="aplica una selección exportada (sin --yes solo muestra la simulación)",
    )
    parser.add_argument("--yes", action="store_true", help="confirma la aplicación por CLI")
    parser.add_argument(
        "--include-irreversible",
        action="store_true",
        help="con --apply-selection: incluye las acciones irreversibles (limpieza)",
    )
    # Uso interno: lo lanza la tarea programada tras reiniciar para medir el arranque.
    parser.add_argument("--capture-boot", action="store_true", help=argparse.SUPPRESS)
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

        from core.constants import ICON_FILE

        if not ICON_FILE.exists():
            raise OSError(f"Falta el icono empaquetado: {ICON_FILE}")

        import tweaks.startup  # noqa: F401
    except (HandlerError, ImportError, OSError, ValueError) as exc:
        if sys.stderr:
            print(f"self-test FALLÓ: {exc}", file=sys.stderr)
        return 1
    if sys.stdout:
        print(f"self-test OK: {len(catalog.tweaks)} tweaks, {len(refs)} handlers")
    return 0


def _attach_console() -> None:
    """El .exe no tiene consola (--noconsole): para la CLI se engancha a la de quien lo lanzó."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    if ctypes.windll.kernel32.AttachConsole(-1):  # type: ignore[attr-defined]
        # CONOUT$ es un dispositivo de Windows, no una ruta: Path no aporta nada aquí.
        stream = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: PTH123, SIM115
        sys.stdout = sys.stderr = stream


def apply_selection_cli(path: str, yes: bool, include_irreversible: bool, demo: bool) -> int:
    """Aplica una selección exportada sin interfaz.

    Códigos de salida: 0 correcto, 1 sin permisos, 2 archivo/condiciones previas, 3 hubo fallos.
    Los tweaks de riesgo alto (doble confirmación) nunca se aplican por CLI.
    """
    from pathlib import Path

    from core.app import build_context
    from core.engine import PreflightError
    from core.selection import SelectionError, load_selection
    from core.settings import Settings

    _attach_console()
    if not demo:
        if sys.platform != "win32":
            print("La CLI solo funciona en Windows (o con --demo).")
            return 2
        if not is_admin():
            print("Ejecuta SafeTrim desde una consola abierta como administrador.")
            return 1
    migration = None if demo else _migrate_from_wintune()
    setup_logging()
    if migration is not None and migration.migrated:
        print(f"Datos de WinTune copiados a SafeTrim: {', '.join(migration.copied)}")
    settings = Settings.load()
    if demo:
        from core.demo import DemoRunner, demo_environment, demo_registry

        app = build_context(
            settings=settings,
            backend=(demo_backend := demo_registry()),
            runner=DemoRunner(demo_backend),
            env=demo_environment(),
        )
    else:
        app = build_context(settings=settings)
    engine = app.engine
    try:
        selection, warnings = load_selection(Path(path), engine.catalog)
    except SelectionError as exc:
        print(f"Error: {exc}")
        return 2
    for warning in warnings:
        print(f"Aviso: {warning}")
    high_risk = [t for t in selection.tweaks if engine.catalog.get(t).confirm_double]
    for tid in high_risk:
        print(f"Omitido (riesgo alto, solo desde la interfaz): {tid}")
    ids = [t for t in selection.tweaks if t not in high_risk]

    print(f"\nSimulación de {len(ids)} tweaks ({app.env.os_label}):")
    for item in engine.plan(ids, selection.params):
        if not item.applicability.applicable:
            print(f"  - {item.tweak.id}: no aplicable ({'; '.join(item.applicability.reasons)})")
        elif item.already_applied:
            print(f"  = {item.tweak.id}: ya aplicado")
        else:
            print(f"  + {item.tweak.id}")
            for line in item.lines:
                print(f"      {line}")
    if not yes:
        print("\nSolo simulación. Añade --yes para aplicar.")
        return 0

    actions = {t for t in ids if engine.catalog.get(t).is_action}
    if actions and not include_irreversible:
        print(f"\n{len(actions)} acciones irreversibles se omitirán (usa --include-irreversible).")
    try:
        session = engine.apply(
            ids,
            selection.params,
            profile=selection.profile,
            confirmed=actions if include_irreversible else set(),
        )
    except PreflightError as exc:
        print(f"\nNo se aplicó nada: {exc}")
        return 2
    print(f"\nSesión {session.id}:")
    for tid, result in session.results.items():
        print(f"  [{result.status}] {tid}: {result.message}")
    summary = session.summary()
    print("Resumen: " + ", ".join(f"{k}={v}" for k, v in summary.items() if v))
    return 3 if summary["failed"] or summary["partial"] else 0


def _migrate_from_wintune() -> MigrationResult | None:
    """Copia los datos de WinTune (nombre anterior) para poder seguir deshaciendo sesiones."""
    from core.migration import migrate_legacy_data
    from core.process import SubprocessRunner

    try:
        return migrate_legacy_data(SubprocessRunner() if sys.platform == "win32" else None)
    except OSError:
        # Nunca bloquear el arranque por la migración: los datos antiguos siguen intactos.
        return None


def capture_boot() -> int:
    """Medición tras reinicio (tarea programada como SYSTEM). Sin interfaz.

    Guarda la medición 'after_reboot' de las sesiones pendientes y elimina la tarea cuando ya
    no queda ninguna. Si el evento de arranque aún no se ha registrado, la tarea se conserva
    para el siguiente inicio de sesión.
    """
    import os

    from core.metrics import MetricsStore, remove_post_reboot_task
    from core.process import SubprocessRunner

    setup_logging()
    log = get_logger("capture_boot")
    runner = SubprocessRunner()
    store = MetricsStore()
    try:
        captured = store.capture_post_reboot(runner, os.environ.get("SYSTEMDRIVE", "C:"))
    except OSError as exc:
        log.error("capture_boot_failed", extra={"err": str(exc)})
        return 1
    log.info("capture_boot", extra={"captured": captured})
    if not store.pending_reboot_sessions():
        remove_post_reboot_task(runner)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)
    if args.self_test:
        return self_test()
    if args.capture_boot:
        return capture_boot()
    if args.apply_selection:
        return apply_selection_cli(
            args.apply_selection, args.yes, args.include_irreversible, args.demo
        )

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

    # Antes de leer los ajustes: la migración trae también settings.json de WinTune.
    migration = None if args.demo else _migrate_from_wintune()
    settings = Settings.load()
    setup_logging(level=getattr(logging, settings.log_level, logging.INFO))
    log = get_logger("main")
    log.info("start", extra={"version": APP_VERSION, "demo": args.demo})
    if migration is not None:
        log.info(
            "legacy_migration", extra={"migrated": migration.migrated, "reason": migration.reason}
        )

    ctk.set_appearance_mode(settings.appearance)
    ctk.set_default_color_theme(COLOR_THEME)

    def builder() -> AppContext:
        if args.demo:
            from core.demo import DemoRunner, demo_environment, demo_registry

            return build_context(
                settings=settings,
                backend=(demo_backend := demo_registry()),
                runner=DemoRunner(demo_backend),
                env=demo_environment(),
            )
        return build_context(settings=settings)

    window = MainWindow(builder)
    window.mainloop()
    log.info("exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
