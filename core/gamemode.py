"""Modos de un clic: modo juego y modo ahorro (batería).

Cada modo es una sesión normal del motor (se ve y se deshace también desde el Historial), sin
punto de restauración porque solo incluye tweaks reversibles de riesgo bajo. El modo juego puede
activarse solo al abrir un juego si el usuario enciende la vigilancia en segundo plano
(core.tray); por defecto no hay nada residente.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.engine import Engine
from core.logger import get_logger
from core.session import Session
from core.watch import WATCH_DIR

log = get_logger("gamemode")

GAME_MODE_TWEAKS: tuple[str, ...] = (
    "power.high_performance",
    "gaming.gamedvr_off",
    "performance.foreground_priority",
)
BATTERY_MODE_TWEAKS: tuple[str, ...] = (
    "power.dc_battery_saver",
    "power.dc_cpu_max",
    "power.dc_display_off",
)


class TweakMode:
    """Un conjunto fijo de tweaks que se activa y desactiva como una unidad."""

    name = "mode"
    tweaks: tuple[str, ...] = ()

    def __init__(self, engine: Engine, directory: Path = WATCH_DIR) -> None:
        self.engine = engine
        self.path = directory / f"{self.name}.json"

    def active_session(self) -> str | None:
        try:
            sid = json.loads(self.path.read_text(encoding="utf-8")).get("session")
        except (OSError, json.JSONDecodeError):
            return None
        # Si se deshizo desde el Historial, el modo juego ya no está activo.
        for session in self.engine.store.list():
            if session.id == sid:
                return None if session.reverted_by else sid
        return None

    @property
    def active(self) -> bool:
        return self.active_session() is not None

    def candidates(self) -> list[str]:
        """Los del modo que se pueden aplicar en este equipo y aún no están aplicados."""
        out = []
        for tid in self.tweaks:
            if tid not in self.engine.catalog:
                continue
            tweak = self.engine.catalog.get(tid)
            if not self.engine.evaluate(tweak).applicable:
                continue
            if self.engine.detect(tweak).state.value == "applied":
                continue
            out.append(tid)
        return out

    def start(self) -> Session | None:
        ids = self.candidates()
        if not ids:
            return None
        session = self.engine.apply(ids, restore_point=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"session": session.id}), encoding="utf-8")
        log.info("mode_on", extra={"mode": self.name, "session": session.id, "tweaks": ids})
        return session

    def stop(self) -> Session | None:
        sid = self.active_session()
        if sid is None:
            return None
        result = self.engine.revert(sid)
        self.path.unlink(missing_ok=True)
        log.info("mode_off", extra={"mode": self.name, "session": sid})
        return result


class GameMode(TweakMode):
    name = "gamemode"
    tweaks = GAME_MODE_TWEAKS


class BatteryMode(TweakMode):
    """Modo ahorro: solo cambia los valores con batería; enchufado todo sigue igual."""

    name = "batterymode"
    tweaks = BATTERY_MODE_TWEAKS

    def available(self) -> bool:
        return self.engine.env.has_battery
