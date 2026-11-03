"""Página genérica de tweaks por categoría (Bloatware, Servicios, Limpieza, Optimización)."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, ClassVar

import customtkinter as ctk

from core.catalog import CATEGORY_LABELS
from core.context import DetectState
from ui.pages.base import Page
from ui.theme import FONT_SMALL, PAD, PAD_S, SECONDARY_BUTTON, TEXT_MUTED
from ui.widgets import Card, SectionHeader, TweakRow
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow


FILTER_ALL = "Todos"
FILTER_PENDING = "Pendientes"
FILTER_APPLIED = "Aplicados"
FILTER_SELECTED = "Seleccionados"
PENDING_STATES = (DetectState.NOT_APPLIED, DetectState.PARTIAL)


class TweaksPage(Page):
    categories: ClassVar[tuple[str, ...]] = ()

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.rows: dict[str, TweakRow] = {}
        self._detected = False
        self._task: BackgroundTask | None = None

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD, pady=PAD_S)
        ctk.CTkButton(
            bar, text="Seleccionar recomendados", width=180, command=self._select_recommended
        ).pack(side="left")
        ctk.CTkButton(
            bar,
            text="Ninguno",
            width=90,
            **SECONDARY_BUTTON,
            command=self._select_none,
        ).pack(side="left", padx=PAD_S)
        ctk.CTkButton(
            bar,
            text="Detectar estado",
            width=130,
            **SECONDARY_BUTTON,
            command=self.detect,
        ).pack(side="left")
        self.status = ctk.CTkLabel(bar, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.status.pack(side="right")

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=PAD, pady=(0, PAD_S))
        # Sin textvariable: CustomTkinter oculta el placeholder si se usa.
        self.search = ctk.CTkEntry(filters, width=260, placeholder_text="Buscar…")
        self.search.bind("<KeyRelease>", lambda _e: self.apply_filter())
        self.search.pack(side="left")
        self.filter_mode = ctk.StringVar(value=FILTER_ALL)
        ctk.CTkSegmentedButton(
            filters,
            values=[FILTER_ALL, FILTER_PENDING, FILTER_APPLIED, FILTER_SELECTED],
            variable=self.filter_mode,
            command=lambda _v: self.apply_filter(),
        ).pack(side="left", padx=PAD_S)
        self.groups: list[tuple[Any, list[TweakRow]]] = []

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))
        engine = self.state.app.engine
        for category in self.categories:
            tweaks = engine.catalog.by_category(category)
            if not tweaks:
                continue
            SectionHeader(body, CATEGORY_LABELS.get(category, category)).pack(
                fill="x", pady=(PAD, PAD_S)
            )
            card = Card(body)
            card.pack(fill="x")
            group: list[TweakRow] = []
            self.groups.append((card, group))
            for level in (1, 2, 3):
                for tweak in (t for t in tweaks if t.level == level):
                    row = TweakRow(
                        card,
                        tweak,
                        engine.evaluate(tweak),
                        tweak.id in self.state.selected,
                        on_toggle=self.state.toggle,
                        on_param=self.state.set_param,
                        env=self.state.app.env,
                    )
                    row.pack(fill="x", padx=PAD, pady=3)
                    self.rows[tweak.id] = row
                    group.append(row)
        self.state.subscribe(self._sync)

    # ------------------------------------------------------------------ filtros

    def _visible(self, row: TweakRow) -> bool:
        tweak = row.tweak
        text = self.search.get().strip().lower()
        if text and not any(text in s.lower() for s in (tweak.name, tweak.description, tweak.id)):
            return False
        mode = self.filter_mode.get()
        state = self.state.detections.get(tweak.id)
        if mode == FILTER_PENDING:
            return state is not None and state.state in PENDING_STATES
        if mode == FILTER_APPLIED:
            return state is not None and state.state == DetectState.APPLIED
        if mode == FILTER_SELECTED:
            return tweak.id in self.state.selected
        return True

    def apply_filter(self) -> None:
        """Re-empaqueta las filas visibles en su orden original (pack no tiene 'ocultar')."""
        shown = 0
        for _card, rows in self.groups:
            for row in rows:
                row.pack_forget()
            for row in rows:
                if self._visible(row):
                    row.pack(fill="x", padx=PAD, pady=3)
                    shown += 1
        if self.search.get() or self.filter_mode.get() != FILTER_ALL:
            self.status.configure(text=f"{shown} de {len(self.rows)} visibles")

    # ------------------------------------------------------------------ selección

    def _sync(self) -> None:
        for tid, row in self.rows.items():
            row.set_selected(tid in self.state.selected)
        if self.filter_mode.get() == FILTER_SELECTED:
            self.apply_filter()

    def _select_recommended(self) -> None:
        engine = self.state.app.engine
        for tid in self.rows:
            tweak = engine.catalog.get(tid)
            app = engine.evaluate(tweak, self.state.profile or 3)
            if app.preselect:
                self.state.selected.add(tid)
        self.state.notify()

    def _select_none(self) -> None:
        self.state.selected -= set(self.rows)
        self.state.notify()

    # ------------------------------------------------------------------ detección

    def on_show(self) -> None:
        if not self._detected:
            self.detect()

    def detect(self) -> None:
        if self._task is not None and self._task.running:
            return
        engine = self.state.app.engine
        ids = list(self.rows)
        self._detected = True
        self.status.configure(text="Detectando estado actual…")

        def work(progress: ProgressFn, cancel: threading.Event) -> int:
            # Una sola consulta para todas las tareas programadas y AppX de la página.
            engine.prefetch([engine.catalog.get(tid) for tid in ids])
            for index, tid in enumerate(ids):
                if cancel.is_set():
                    break
                self.state.detections[tid] = engine.detect(engine.catalog.get(tid))
                progress((index + 1) / len(ids), tid)
            return len(ids)

        def on_progress(_fraction: float, tid: str) -> None:
            result = self.state.detections.get(tid)
            if result and tid in self.rows:
                self.rows[tid].set_detection(result)

        def on_done(count: int) -> None:
            self.status.configure(text=f"Estado detectado ({count} elementos)")
            self.apply_filter()

        def on_error(exc: BaseException) -> None:
            self.status.configure(text=f"Error al detectar: {exc}")

        self._task = BackgroundTask(self, work, on_done, on_error, on_progress).start()


class BloatwarePage(TweaksPage):
    title = "Bloatware y privacidad"
    subtitle = (
        "Apps preinstaladas, telemetría, publicidad y sugerencias. La eliminación de apps se "
        "revierte reinstalándolas desde Microsoft Store (requiere conexión)."
    )
    categories = ("bloatware", "privacy")


class ServicesPage(TweaksPage):
    title = "Servicios"
    subtitle = (
        "Los servicios pasan a Manual, no a Deshabilitado: siguen arrancando si una app o un "
        "disparador los necesita. Defender, Windows Update, Store y red nunca se tocan."
    )
    categories = ("services",)


class CleanupPage(TweaksPage):
    title = "Limpieza"
    subtitle = (
        "Acciones irreversibles: los archivos borrados no se recuperan y se piden con una "
        "confirmación aparte. Se respetan antigüedades mínimas y los archivos en uso."
    )
    categories = ("cleanup",)


class OptimizationPage(TweaksPage):
    title = "Optimización"
    subtitle = (
        "Efectos visuales, energía, red, juegos, búsqueda, memoria y seguridad. Las opciones "
        "'solo manual' no las activa ningún perfil."
    )
    categories = (
        "visual",
        "power",
        "performance",
        "network",
        "gaming",
        "search",
        "memory",
        "security",
    )
