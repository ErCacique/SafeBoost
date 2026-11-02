"""Estado compartido de la UI: selección de tweaks, parámetros, perfil y detecciones."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.app import AppContext
from core.catalog import Tweak, profile_selection
from core.context import DetectResult

Listener = Callable[[], None]


@dataclass
class UiState:
    app: AppContext
    profile: int | None = None
    selected: set[str] = field(default_factory=set)
    params: dict[str, dict[str, Any]] = field(default_factory=dict)
    detections: dict[str, DetectResult] = field(default_factory=dict)
    busy: bool = False
    _listeners: list[Listener] = field(default_factory=list)

    # ------------------------------------------------------------------ suscripción

    def subscribe(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------------ selección

    def apply_profile(self, level: int) -> None:
        engine = self.app.engine
        self.profile = level
        self.selected = set(profile_selection(engine.catalog, self.app.env, level, engine.check))
        self.notify()

    def toggle(self, tweak_id: str, value: bool) -> None:
        if value:
            self.selected.add(tweak_id)
        else:
            self.selected.discard(tweak_id)
        self.notify()

    def set_param(self, tweak_id: str, name: str, value: Any) -> None:
        self.params.setdefault(tweak_id, {})[name] = value

    def ordered_selection(self) -> list[str]:
        """Orden del catálogo: bloatware antes que limpieza, etc."""
        return [t.id for t in self.app.engine.catalog.tweaks if t.id in self.selected]

    def selected_tweaks(self) -> list[Tweak]:
        return [self.app.engine.catalog.get(t) for t in self.ordered_selection()]
