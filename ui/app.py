"""Ventana principal: sidebar, páginas, barra de acciones, progreso y log en vivo."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.app import AppContext
from core.constants import APP_HOME, APP_NAME, APP_VERSION, ICON_FILE, self_command
from core.engine import PlanItem
from core.logger import get_logger, ui_log_queue
from core.metrics import (
    Comparison,
    compare,
    last_boot,
    schedule_post_reboot_capture,
    take_snapshot,
)
from core.session import Session
from ui.dialogs import ReviewDialog, SummaryDialog
from ui.pages.base import Page, show_error
from ui.pages.dashboard import DashboardPage
from ui.pages.history import HistoryPage
from ui.pages.settings_page import SettingsPage
from ui.pages.startup_page import StartupPage
from ui.pages.tweaks_page import (
    BloatwarePage,
    CleanupPage,
    OptimizationPage,
    ServicesPage,
    TweaksPage,
)
from ui.state import UiState
from ui.theme import (
    BG_SIDEBAR,
    DANGER,
    FONT_BODY,
    FONT_H2,
    FONT_SMALL,
    PAD,
    PAD_S,
    RISK_COLORS,
    SECONDARY_BUTTON,
    SIDEBAR_WIDTH,
    TEXT_MUTED,
    WINDOW_MIN,
    WINDOW_SIZE,
    WINDOW_TITLE,
)
from ui.widgets import LogPanel, ProgressBar
from ui.worker import BackgroundTask, ProgressFn

log = get_logger("ui")

PAGES: list[tuple[str, str, type[Page]]] = [
    ("dashboard", "Dashboard", DashboardPage),
    ("bloatware", "Bloatware", BloatwarePage),
    ("startup", "Inicio", StartupPage),
    ("services", "Servicios", ServicesPage),
    ("cleanup", "Limpieza", CleanupPage),
    ("optimization", "Optimización", OptimizationPage),
    ("history", "Historial / Deshacer", HistoryPage),
    ("settings", "Ajustes", SettingsPage),
]


class MainWindow(ctk.CTk):
    def __init__(self, builder: Callable[[], AppContext]) -> None:
        super().__init__()
        self.title(f"{WINDOW_TITLE} {APP_VERSION}")
        self.geometry(WINDOW_SIZE)
        self.minsize(*WINDOW_MIN)
        if sys.platform == "win32" and ICON_FILE.exists():
            # Llamarlo antes de 200 ms evita que CustomTkinter ponga su icono por defecto.
            self.iconbitmap(str(ICON_FILE))
        # No se llama "state": CTk ya tiene un método state() (estado de la ventana).
        self.ui: UiState | None = None
        self.pages: dict[str, Page] = {}
        self.current: str | None = None
        self.task: BackgroundTask | None = None
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.loading = ctk.CTkLabel(
            self,
            text="Detectando entorno (versión, edición, disco, dominio, impresoras)…",
            font=FONT_H2,
        )
        self.loading.pack(expand=True)
        BackgroundTask(self, lambda _p, _c: builder(), self._build, self._fatal).start()

    # ================================================================== construcción

    def _fatal(self, exc: BaseException) -> None:
        log.error("startup_failed", extra={"err": str(exc)})
        messagebox.showerror(APP_NAME, f"No se pudo iniciar SafeTrim:\n\n{exc}")
        self.destroy()

    def _build(self, app: AppContext) -> None:
        self.loading.destroy()
        self.ui = UiState(app)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=BG_SIDEBAR)
        sidebar.grid(row=0, column=0, rowspan=3, sticky="nsw")
        sidebar.grid_propagate(False)
        ctk.CTkLabel(sidebar, text=APP_NAME, font=("Segoe UI", 24, "bold")).pack(
            pady=(PAD * 2, PAD)
        )
        self.nav: dict[str, ctk.CTkButton] = {}
        for key, label, _cls in PAGES:
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                height=36,
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray75", "gray25"),
                command=lambda k=key: self.show(k),
            )
            btn.pack(fill="x", padx=PAD_S, pady=2)
            self.nav[key] = btn
        self.mode_label = ctk.CTkLabel(sidebar, text="", font=FONT_SMALL, wraplength=180)
        self.mode_label.pack(side="bottom", pady=PAD)

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_action_bar()
        self.log_panel = LogPanel(self, ui_log_queue())
        self.log_visible = False

        self.ui.subscribe(self.refresh_action_bar)
        self.refresh_action_bar()
        self.show("dashboard")

    def _build_action_bar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0)
        bar.grid(row=1, column=1, sticky="ew")
        self.selection_label = ctk.CTkLabel(bar, text="", font=FONT_BODY)
        self.selection_label.pack(side="left", padx=PAD, pady=PAD_S)
        self.log_btn = ctk.CTkButton(
            bar,
            text="Mostrar log",
            width=110,
            **SECONDARY_BUTTON,
            command=self.toggle_log,
        )
        self.log_btn.pack(side="right", padx=PAD, pady=PAD_S)
        self.cancel_btn = ctk.CTkButton(
            bar, text="Cancelar", width=90, fg_color=DANGER, command=self._cancel
        )
        self.apply_btn = ctk.CTkButton(
            bar, text="Revisar y aplicar", width=150, command=self.review
        )
        self.apply_btn.pack(side="right", padx=PAD_S, pady=PAD_S)
        self.sim_btn = ctk.CTkButton(
            bar,
            text="Simular",
            width=100,
            **SECONDARY_BUTTON,
            command=self.simulate,
        )
        self.sim_btn.pack(side="right", pady=PAD_S)
        self.progress = ProgressBar(bar)
        self.progress.pack(side="left", fill="x", expand=True, padx=PAD)

    # ================================================================== navegación

    def show(self, key: str) -> None:
        if key not in self.pages:
            cls = next(c for k, _l, c in PAGES if k == key)
            page = cls(self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        page = self.pages[key]
        page.tkraise()
        for name, btn in self.nav.items():
            btn.configure(fg_color=("gray75", "gray25") if name == key else "transparent")
        self.current = key
        page.on_show()

    def toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_panel.grid(row=2, column=1, sticky="nsew", padx=PAD, pady=(0, PAD))
            self.log_btn.configure(text="Ocultar log")
        else:
            self.log_panel.grid_forget()
            self.log_btn.configure(text="Mostrar log")

    def refresh_action_bar(self) -> None:
        if self.ui is None:
            return
        app = self.ui.app
        count = len(self.ui.selected)
        os_allowed = app.env.supported or app.settings.allow_unsupported_os
        self.selection_label.configure(text=f"{count} cambios seleccionados")
        if app.settings.dry_run:
            self.mode_label.configure(
                text="MODO SIMULACIÓN\nno se cambia nada", text_color=RISK_COLORS["medio"]
            )
        elif not os_allowed:
            self.mode_label.configure(
                text="Windows no soportado\nsolo simulación", text_color=DANGER
            )
        elif not app.env.is_admin:
            self.mode_label.configure(text="Sin permisos de administrador", text_color=DANGER)
        else:
            self.mode_label.configure(text="Modo real", text_color=TEXT_MUTED)
        busy = self.ui.busy
        can_apply = (
            count > 0 and not busy and app.env.is_admin and os_allowed and not app.settings.dry_run
        )
        self.apply_btn.configure(state="normal" if can_apply else "disabled")
        self.sim_btn.configure(state="normal" if count > 0 and not busy else "disabled")

    def invalidate_detections(self) -> None:
        if self.ui is None:  # interfaz aún no construida
            return
        self.ui.detections.clear()
        for key, page in self.pages.items():
            if isinstance(page, TweaksPage):
                page._detected = False
                if key == self.current:
                    page.detect()

    # ================================================================== tareas largas

    def run_long(
        self,
        work: Callable[[ProgressFn, threading.Event], Any],
        on_done: Callable[[Any], Any],
        error_title: str = "Error",
    ) -> None:
        if self.ui is None:  # interfaz aún no construida
            return
        if self.ui.busy:
            return
        self.ui.busy = True
        self.refresh_action_bar()
        self.cancel_btn.pack(side="right", padx=PAD_S, pady=PAD_S)

        def finish() -> None:
            if self.ui is None:  # interfaz aún no construida
                return
            self.ui.busy = False
            self.cancel_btn.pack_forget()
            self.refresh_action_bar()

        def done(result: Any) -> None:
            finish()
            self.progress.reset("Terminado")
            on_done(result)

        def failed(exc: BaseException) -> None:
            finish()
            self.progress.reset("Error")
            show_error(error_title, exc, self)

        self.task = BackgroundTask(self, work, done, failed, self.progress.update_progress)
        self.task.start()

    def _cancel(self) -> None:
        if self.task is not None:
            self.task.cancel()
            self.progress.update_progress(0, "Cancelando tras el paso actual…")

    # ================================================================== flujo principal

    def simulate(self) -> None:
        self._plan(dry_run=True)

    def review(self) -> None:
        if self.ui is None:  # interfaz aún no construida
            return
        self._plan(dry_run=self.ui.app.settings.dry_run)

    def _plan(self, dry_run: bool) -> None:
        if self.ui is None:  # interfaz aún no construida
            return
        state = self.ui
        ids = state.ordered_selection()
        params = dict(state.params)

        def work(progress: ProgressFn, _c: threading.Event) -> list[PlanItem]:
            progress(0.1, "Simulando cambios…")
            return state.app.engine.plan(ids, params)

        def done(items: list[PlanItem]) -> None:
            ReviewDialog(self, items, dry_run, on_confirm=self._apply)

        self.run_long(work, done, "Error en la simulación")

    def _apply(self, ids: list[str], confirmed: set[str]) -> None:
        if self.ui is None:  # interfaz aún no construida
            return
        state = self.ui
        app = state.app
        params = dict(state.params)

        def work(progress: ProgressFn, cancel: threading.Event) -> tuple[Session, Comparison]:
            progress(0.0, "Midiendo estado inicial…")
            before = take_snapshot(app.env.system_drive)
            before.boot = last_boot(app.runner)
            session = app.engine.apply(
                ids,
                params,
                profile=state.profile,
                confirmed=confirmed,
                progress=progress,
                cancel=cancel,
            )
            after = take_snapshot(app.env.system_drive)
            after.boot = before.boot
            app.metrics.save(session.id, "before", before)
            app.metrics.save(session.id, "after", after)
            if app.settings.measure_boot_after_reboot and any(
                r.status in ("applied", "partial") for r in session.results.values()
            ):
                progress(1.0, "Programando la medición tras reiniciar…")
                schedule_post_reboot_capture(app.runner, self_command(), APP_HOME)
            return session, compare(before, after)

        def done(result: tuple[Session, Comparison]) -> None:
            session, comparison = result
            SummaryDialog(self, session, app.engine.catalog, comparison)
            self.invalidate_detections()
            dashboard = self.pages.get("dashboard")
            if isinstance(dashboard, DashboardPage):
                dashboard.update_compare()
                dashboard.check_drift()

        self.run_long(work, done, "No se pudo aplicar")

    def _on_close(self) -> None:
        if (
            self.ui is not None
            and self.ui.busy
            and not messagebox.askyesno(
                APP_NAME,
                "Hay una operación en curso. Si cierras ahora, se detendrá tras el paso actual y "
                "la sesión quedará registrada hasta ese punto. ¿Cerrar?",
                parent=self,
            )
        ):
            return
        if self.task is not None:
            self.task.cancel()
        self.destroy()
