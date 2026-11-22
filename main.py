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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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
    parser.add_argument(
        "--undo-all",
        action="store_true",
        help="kit de rescate: deshace todas las sesiones aplicadas, sin interfaz (pide "
        "confirmación salvo con --yes); funciona también en modo seguro",
    )
    # Uso interno: lo lanza la tarea mensual de mantenimiento (Ajustes → Mantenimiento mensual).
    parser.add_argument("--maintenance", action="store_true", help=argparse.SUPPRESS)
    # Uso interno: lo lanza la tarea programada tras reiniciar para medir el arranque.
    parser.add_argument("--capture-boot", action="store_true", help=argparse.SUPPRESS)
    # Uso interno: icono de vigilancia junto al reloj (tarea \SafeTrim\Tray, opcional).
    parser.add_argument("--tray", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    return parser.parse_args(argv)


def _relaunch_elevated(argv: list[str]) -> bool:
    """Relanza el proceso con UAC. El .exe ya lo pide por manifest; esto cubre `python main.py`."""
    if getattr(sys, "frozen", False):
        executable, params = sys.executable, argv
    else:
        executable, params = sys.executable, [sys.argv[0], *argv]
    # ShellExecuteW devuelve > 32 si consiguió lanzar el proceso.
    rc = ctypes.windll.shell32.ShellExecuteW(
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


def _attach_console(allocate: bool = False) -> bool:
    """El .exe no tiene consola (--noconsole): para la CLI se engancha a la de quien lo lanzó.

    Con `allocate`, si no hay consola padre (lanzado desde un acceso directo) abre una propia.
    Devuelve True si la consola es nueva: entonces hay que pausar antes de salir para que el
    usuario pueda leer el resultado.
    """
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    kernel32 = ctypes.windll.kernel32
    created = False
    if not kernel32.AttachConsole(-1):
        if not (allocate and kernel32.AllocConsole()):
            return False
        created = True
    # CONOUT$/CONIN$ son dispositivos de Windows, no rutas: Path no aporta nada aquí.
    stream = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: PTH123, SIM115
    sys.stdout = sys.stderr = stream
    sys.stdin = open("CONIN$", encoding="utf-8", errors="replace")  # noqa: PTH123, SIM115
    return created


def _ask(question: str) -> bool:
    try:
        return input(f"{question} (s/N): ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except (EOFError, OSError):
        return False


def undo_all_cli(yes: bool, demo: bool, ask: Callable[[str], bool] = _ask) -> int:
    """Kit de rescate: deshace todas las sesiones aplicadas y no deshechas, de la más reciente a
    la más antigua, sin interfaz gráfica.

    Códigos de salida: 0 correcto o nada que deshacer, 1 sin permisos, 2 cancelado,
    3 alguna sesión no se pudo deshacer por completo.
    """
    from core.app import build_context
    from core.engine import PreflightError
    from core.settings import Settings

    if not demo:
        if sys.platform != "win32":
            print("El kit de rescate solo funciona en Windows (o con --demo).")
            return 2
        if not is_admin():
            print("Ejecuta SafeTrim como administrador para deshacer los cambios.")
            return 1
    setup_logging()
    settings = Settings.load()
    if demo:
        from core.demo import DemoRunner, demo_environment, demo_registry

        app = build_context(
            settings=settings,
            backend=(demo_backend := demo_registry()),
            runner=DemoRunner(demo_backend),
            env=demo_environment(),
            warm_checks=False,
        )
    else:
        # Sin comprobaciones de hardware: deshacer no las necesita y así arranca antes.
        app = build_context(settings=settings, warm_checks=False)
    pending = [s for s in app.store.list() if s.kind == "apply" and not s.reverted_by]
    if not pending:
        print("No hay cambios de SafeTrim que deshacer.")
        return 0
    print(f"SafeTrim {APP_VERSION} · kit de rescate\n")
    print(f"Se van a deshacer {len(pending)} sesión(es), de la más reciente a la más antigua:")
    for session in pending:
        applied = sum(r.status in ("applied", "partial") for r in session.results.values())
        print(f"  {session.created.replace('T', ' ')}  ·  {applied} cambio(s)  ·  {session.id}")
    print(
        "\nLas limpiezas de archivos no se pueden deshacer. Si algo falla, también puedes usar "
        "Restaurar sistema (rstrui.exe)."
    )
    if not yes and not ask("\n¿Deshacer ahora?"):
        print("Cancelado: no se ha cambiado nada.")
        return 2
    incomplete = 0
    for session in pending:
        try:
            result = app.engine.revert(session.id)
        except PreflightError as exc:
            print(f"\n[{session.id}] No se pudo deshacer: {exc}")
            incomplete += 1
            continue
        summary = result.summary()
        failed = summary.get("failed", 0) + summary.get("partial", 0)
        incomplete += bool(failed)
        line = f"\n[{session.id}] revertidos: {summary.get('reverted', 0)}"
        print(line + (f" · con problemas: {failed}" if failed else ""))
        for tid, item in result.results.items():
            if item.status in ("failed", "partial"):
                print(f"    {tid}: {item.message}")
    print("\nHecho. Reinicia el equipo para que todos los cambios surtan efecto.")
    return 3 if incomplete else 0


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


def maintenance(build: Callable[..., Any] | None = None) -> int:
    """Mantenimiento mensual sin interfaz: deriva, limpieza segura y vigilancia, con informe.

    Solo limpia temporales y miniaturas (las mismas reglas de antigüedad que la interfaz), sin
    punto de restauración porque no recupera archivos. El informe aparece en el Dashboard la
    próxima vez que se abra SafeTrim.
    """
    from datetime import datetime

    from core.engine import PreflightError
    from core.metrics import human_bytes
    from core.monitor import refresh
    from core.settings import Settings
    from core.watch import MAINTENANCE_CLEANUPS, EventLog, MaintenanceReport, MaintenanceStore

    setup_logging()
    log = get_logger("maintenance")
    if build is None:
        from core.app import build_context

        build = build_context
    app = build(settings=Settings.load(), warm_checks=False)
    engine = app.engine
    report = MaintenanceReport(when=datetime.now().isoformat(timespec="seconds"))
    try:
        report.drift = [engine.catalog.get(d.tweak_id).name for d in engine.drift()]
    except Exception as exc:  # noqa: BLE001 - cada parte del mantenimiento es independiente
        log.warning("maintenance_drift_failed", extra={"err": str(exc)})
    ids = [
        tid
        for tid in MAINTENANCE_CLEANUPS
        if tid in engine.catalog and engine.evaluate(engine.catalog.get(tid)).applicable
    ]
    if ids:
        try:
            session = engine.apply(ids, confirmed=set(ids), restore_point=False)
            report.freed_bytes = sum(
                int(state.get("freed_bytes", 0)) for state in session.handler_state.values()
            )
        except PreflightError as exc:
            report.error = str(exc)
    watch = refresh(app)
    report.new_startup = [i.name for i in watch.new_startup]
    MaintenanceStore().save(report)
    EventLog().add("maintenance", f"Mantenimiento: {human_bytes(report.freed_bytes)} liberados")
    log.info("maintenance_done", extra={"report": report.__dict__})
    return 1 if report.error else 0


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


def tray() -> int:
    """Icono de vigilancia en segundo plano (Ajustes → Vigilancia en segundo plano)."""
    from core.app import build_context
    from core.constants import self_command
    from core.tray import run_tray

    setup_logging()

    def open_app() -> None:
        subprocess.Popen(self_command(), close_fds=True)

    return run_tray(build_context, open_app)


def main(argv: list[str] | None = None) -> int:
    from core.crash import install as install_crash_reports

    install_crash_reports()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(argv)
    if args.self_test:
        return self_test()
    if args.capture_boot:
        return capture_boot()
    if args.maintenance:
        return maintenance()
    if args.tray:
        return tray()
    if args.undo_all:
        new_console = _attach_console(allocate=True)
        code = undo_all_cli(args.yes, args.demo)
        if new_console:
            input("\nPulsa Enter para cerrar…")
        return code
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
    from core.i18n import set_language

    set_language(settings.language)
    setup_logging(level=getattr(logging, settings.log_level, logging.INFO))
    log = get_logger("main")
    log.info("start", extra={"version": APP_VERSION, "demo": args.demo})
    if migration is not None:
        log.info(
            "legacy_migration", extra={"migrated": migration.migrated, "reason": migration.reason}
        )

    ctk.set_appearance_mode(settings.appearance)
    ctk.set_default_color_theme(COLOR_THEME)

    def builder(progress: Callable[[str], None]) -> AppContext:
        if args.demo:
            from core.demo import DemoRunner, demo_environment, demo_registry

            return build_context(
                settings=settings,
                backend=(demo_backend := demo_registry()),
                runner=DemoRunner(demo_backend),
                env=demo_environment(),
                defer_slow_checks=True,
                progress=progress,
            )
        return build_context(settings=settings, defer_slow_checks=True, progress=progress)

    window = MainWindow(builder)
    window.mainloop()
    log.info("exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
