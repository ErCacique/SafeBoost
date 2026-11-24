"""Vigilancia en segundo plano (opcional, desactivada por defecto): un icono junto al reloj que

- avisa en cuanto un programa se añade al inicio de Windows (cada 2 minutos), y
- si el usuario lo pide, activa el modo juego al abrir un juego y lo desactiva al cerrarlo.

Lo arranca la tarea programada \\SafeBoost\\Tray al iniciar sesión (con privilegios elevados, sin
pedir UAC, porque el modo juego cambia ajustes del sistema). SafeBoost sin esta opción sigue sin
dejar nada residente.

La lógica (qué es un juego, cuándo activar o desactivar) está separada del icono para poder
probarla sin Windows.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Any

import psutil

from core.constants import (
    APP_HOME,
    APP_NAME,
    ICON_FILE,
    SAFEBOOST_TASK_FOLDER,
    protected_location,
)
from core.logger import get_logger
from core.process import Runner, ps_quote

if TYPE_CHECKING:
    from core.app import AppContext

log = get_logger("tray")

TRAY_TASK = "Tray"
LOCK_FILE = APP_HOME / "tray.pid"
STARTUP_EVERY_S = 120
GAMES_EVERY_S = 10
# Un juego cerrado un momento (pantalla de carga, relanzador) no desactiva el modo al instante.
GAME_GRACE_S = 30

# Carpetas de instalación de las tiendas de juegos más comunes (en minúsculas).
GAME_DIR_MARKERS: tuple[str, ...] = (
    "\\steamapps\\common\\",
    "\\epic games\\",
    "\\gog galaxy\\games\\",
    "\\gog games\\",
    "\\xboxgames\\",
    "\\riot games\\",
    "\\ubisoft game launcher\\games\\",
    "\\ea games\\",
    "\\battle.net\\",
)
# Lanzadores y ayudantes que viven en esas carpetas pero no son el juego.
NOT_GAMES = frozenset(
    {
        "steam.exe",
        "steamwebhelper.exe",
        "epicgameslauncher.exe",
        "epicwebhelper.exe",
        "galaxyclient.exe",
        "riotclientservices.exe",
        "riotclientux.exe",
        "battle.net.exe",
        "agent.exe",
        "crashreportclient.exe",
        "unitycrashhandler64.exe",
        "easyanticheat.exe",
    }
)


def is_game(exe_path: str) -> bool:
    lowered = exe_path.lower()
    if PureWindowsPath(lowered).name in NOT_GAMES:
        return False
    return any(marker in lowered for marker in GAME_DIR_MARKERS)


def running_games(processes: Iterable[tuple[str, str]] | None = None) -> list[str]:
    """Nombres de los procesos de juego abiertos. `processes` (nombre, ruta) para los tests."""
    if processes is None:
        found = []
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                found.append((proc.info.get("name") or "", proc.info.get("exe") or ""))
            except (psutil.Error, OSError):
                continue
        processes = found
    return sorted({name for name, exe in processes if exe and is_game(exe)})


@dataclass
class GameWatcher:
    """Decide cuándo encender o apagar el modo juego. Solo apaga lo que encendió él."""

    grace_s: float = GAME_GRACE_S
    auto_started: bool = False
    last_seen: float = 0.0

    def tick(self, games: list[str], mode_active: bool, now: float) -> str | None:
        """Devuelve "start", "stop" o None."""
        if games:
            self.last_seen = now
            if not mode_active and not self.auto_started:
                return "start"
            return None
        if self.auto_started and mode_active and now - self.last_seen >= self.grace_s:
            return "stop"
        if self.auto_started and not mode_active:
            self.auto_started = False  # lo apagó el usuario: no volver a tocarlo
        return None


# --------------------------------------------------------------------------- tarea programada


def schedule_tray(runner: Runner, command: list[str], user: str) -> bool:
    """Tarea elevada al iniciar sesión. Solo con la versión instalada (protected_location)."""
    if not protected_location(command):
        log.warning("tray_task_unprotected_exe", extra={"exe": command[0] if command else ""})
        return False
    exe, *args = [*command, "--tray"]
    script = (
        f"$a = New-ScheduledTaskAction -Execute {ps_quote(exe)}"
        + (f" -Argument {ps_quote(' '.join(args))};" if args else ";")
        + f"$t = New-ScheduledTaskTrigger -AtLogOn -User {ps_quote(user)};"
        "$t.Delay = 'PT1M';"
        f"$p = New-ScheduledTaskPrincipal -UserId {ps_quote(user)} -LogonType Interactive"
        " -RunLevel Highest;"
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
        " -ExecutionTimeLimit ([TimeSpan]::Zero);"
        f"Register-ScheduledTask -TaskPath {ps_quote(SAFEBOOST_TASK_FOLDER)}"
        f" -TaskName {ps_quote(TRAY_TASK)} -Action $a -Trigger $t -Principal $p"
        " -Settings $s -Force | Out-Null;"
        f"Start-ScheduledTask -TaskPath {ps_quote(SAFEBOOST_TASK_FOLDER)}"
        f" -TaskName {ps_quote(TRAY_TASK)}"
    )
    result = runner.powershell(script)
    if not result.ok:
        log.warning("tray_task_failed", extra={"err": result.error_text()})
    return result.ok


def remove_tray(runner: Runner) -> None:
    folder, task = ps_quote(SAFEBOOST_TASK_FOLDER), ps_quote(TRAY_TASK)
    runner.powershell(
        f"Stop-ScheduledTask -TaskPath {folder} -TaskName {task} -ErrorAction SilentlyContinue;"
        f"Unregister-ScheduledTask -TaskPath {folder} -TaskName {task} -Confirm:$false"
        " -ErrorAction SilentlyContinue"
    )
    stop_running_tray()


def stop_running_tray() -> None:
    pid = _lock_pid()
    if pid and pid != os.getpid():
        with contextlib.suppress(psutil.Error):
            psutil.Process(pid).terminate()
    LOCK_FILE.unlink(missing_ok=True)


def _lock_pid() -> int | None:
    try:
        pid = int(LOCK_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None
    return pid if psutil.pid_exists(pid) else None


# --------------------------------------------------------------------------- icono


class TrayService:
    def __init__(self, app: AppContext, notify: Callable[[str], None]) -> None:
        from core.gamemode import GameMode

        self.app = app
        self.notify = notify
        self.game_mode = GameMode(app.engine)
        self.watcher = GameWatcher()
        self.stop = threading.Event()

    def check_startup(self) -> None:
        from core.monitor import startup_items
        from core.watch import EventLog, StartupWatch

        new = StartupWatch(events=EventLog()).check(startup_items(self.app))
        for item in new:
            self.notify(
                f"{item.name} se ha añadido al inicio de Windows. "
                "Si no lo quieres, desactívalo en SafeBoost → Inicio."
            )

    def check_games(self) -> None:
        settings = self.app.settings
        if not settings.auto_game_mode or settings.dry_run:
            return
        action = self.watcher.tick(running_games(), self.game_mode.active, time.monotonic())
        if action == "start" and self.game_mode.start() is not None:
            self.watcher.auto_started = True
            self.notify("Modo juego activado. Se desactivará al cerrar el juego.")
        elif action == "stop":
            self.game_mode.stop()
            self.watcher.auto_started = False
            self.notify("Juego cerrado: modo juego desactivado.")

    def loop(self) -> None:
        last_startup = 0.0
        while not self.stop.is_set():
            now = time.monotonic()
            for due, step in (
                (now - last_startup >= STARTUP_EVERY_S, self.check_startup),
                (True, self.check_games),
            ):
                if not due:
                    continue
                try:
                    step()
                except Exception as exc:  # noqa: BLE001 - el icono nunca debe caerse
                    log.warning("tray_step_failed", extra={"step": step.__name__, "err": str(exc)})
            if now - last_startup >= STARTUP_EVERY_S:
                last_startup = now
            self.stop.wait(GAMES_EVERY_S)


def run_tray(build: Callable[..., AppContext], open_app: Callable[[], None]) -> int:
    """Bucle del icono. Devuelve el código de salida del proceso."""
    if _lock_pid():
        log.info("tray_already_running")
        return 0
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="ascii")
    try:
        import pystray
        from PIL import Image

        from core.settings import Settings

        app = build(settings=Settings.load(), warm_checks=False)
        icon: Any = None

        def notify(text: str) -> None:
            if icon is not None:
                icon.notify(text, APP_NAME)

        service = TrayService(app, notify)

        def toggle_auto(_icon: Any, _item: Any) -> None:
            app.settings.auto_game_mode = not app.settings.auto_game_mode
            app.settings.save()

        def quit_tray(_icon: Any, _item: Any) -> None:
            service.stop.set()
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Abrir SafeBoost", lambda _i, _m: open_app(), default=True),
            pystray.MenuItem(
                "Modo juego automático",
                toggle_auto,
                checked=lambda _item: app.settings.auto_game_mode,
            ),
            pystray.MenuItem("Cerrar vigilancia", quit_tray),
        )
        icon = pystray.Icon(APP_NAME, Image.open(ICON_FILE), f"{APP_NAME}: vigilando", menu)
        threading.Thread(target=service.loop, name="tray-loop", daemon=True).start()
        icon.run()
        return 0
    finally:
        LOCK_FILE.unlink(missing_ok=True)
