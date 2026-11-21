"""Modo juego: activa con un clic los ajustes que ayudan al jugar y los deshace igual de rápido.

Es una sesión normal del motor (se ve y se deshace también desde el Historial), sin punto de
restauración porque solo incluye tweaks reversibles de riesgo bajo. No se activa solo al abrir un
juego: eso exigiría dejar SafeTrim residente vigilando procesos, y no lo hace.
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


class GameMode:
    def __init__(self, engine: Engine, directory: Path = WATCH_DIR) -> None:
        self.engine = engine
        self.path = directory / "gamemode.json"

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
        """Los del modo juego que se pueden aplicar en este equipo y aún no están aplicados."""
        out = []
        for tid in GAME_MODE_TWEAKS:
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
        log.info("game_mode_on", extra={"session": session.id, "tweaks": ids})
        return session

    def stop(self) -> Session | None:
        sid = self.active_session()
        if sid is None:
            return None
        result = self.engine.revert(sid)
        self.path.unlink(missing_ok=True)
        log.info("game_mode_off", extra={"session": sid})
        return result
