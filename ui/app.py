"""Ventana principal: sidebar, páginas, barra de acciones, progreso y log en vivo."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.app import AppContext
from core.constants import (
    APP_NAME,
    APP_VERSION,
    ICON_FILE,
    PORTABLE_MODE,
    self_command,
)
from core.engine import PlanItem
from core.i18n import _
from core.logger import get_logger, ui_log_queue
from core.metrics import (
    Comparison,
    compare,
    last_boot,
    process_user,
    schedule_post_reboot_capture,
    take_snapshot,
)
from core.session import Session
from core.update_check import ReleaseInfo, check_latest
from ui.dialogs import ReviewDialog, SummaryDialog, WelcomeWizard
from ui.icons import icon
from ui.pages.base import Page, show_error
from ui.pages.dashboard import DashboardPage
from ui.pages.diagnostics_page import DiagnosticsPage
from ui.pages.evolution_page import EvolutionPage
from ui.pages.history import HistoryPage
from ui.pages.home_page import HomePage
from ui.pages.privacy_page import PrivacyPage
from ui.pages.settings_page import SettingsPage
from ui.pages.space_page import SpacePage
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
    BG_APP,
    BG_SIDEBAR,
    DANGER,
    FONT_BODY,
    FONT_H2,
    FONT_NAV,
    FONT_SMALL,
    NAV_ACTIVE,
    NAV_HOVER,
    PAD,
    PAD_S,
    RISK_COLORS,
    SCREEN_MARGIN,
    SECONDARY_BUTTON,
    SIDEBAR_WIDTH,
    TEXT,
    TEXT_MUTED,
    WINDOW_MIN,
    WINDOW_SIZE,
    WINDOW_TITLE,
)
from ui.widgets import LogPanel, ProgressBar
from ui.worker import BackgroundTask, ProgressFn

log = get_logger("ui")

PAGES: list[tuple[str, str, type[Page]]] = [
    ("home", "Inicio", HomePage),
    ("dashboard", "Dashboard", DashboardPage),
    ("diagnostics", "Diagnóstico", DiagnosticsPage),
    ("evolution", "Evolución", EvolutionPage),
    ("privacy", "Privacidad", PrivacyPage),
    ("space", "Espacio", SpacePage),
    ("bloatware", "Bloatware", BloatwarePage),
    ("startup", "Inicio de Windows", StartupPage),
    ("services", "Servicios", ServicesPage),
    ("cleanup", "Limpieza", CleanupPage),
    ("optimization", "Optimización", OptimizationPage),
    ("history", "Historial / Deshacer", HistoryPage),
    ("settings", "Ajustes", SettingsPage),
]

# Menú de cada modo: (clave de página, texto, icono). None como clave = título de grupo.
NavItem = tuple[str | None, str, str]
EASY_NAV: list[NavItem] = [
    ("home", "Inicio", "home"),
    ("diagnostics", "Revisar el PC", "pulse"),
    ("startup", "Arranque", "clock"),
    ("space", "Espacio", "trash"),
    ("evolution", "Evolución", "chart"),
    ("privacy", "Privacidad", "lock"),
    ("history", "Deshacer cambios", "undo"),
    ("settings", "Ajustes", "gear"),
]
ADVANCED_NAV: list[NavItem] = [
    (None, "EQUIPO", ""),
    ("dashboard", "Panel", "home"),
    ("diagnostics", "Diagnóstico", "pulse"),
    ("evolution", "Evolución", "chart"),
    ("privacy", "Privacidad", "lock"),
    ("space", "Espacio", "drive"),
    (None, "OPTIMIZAR", ""),
    ("bloatware", "Bloatware", "apps"),
    ("startup", "Inicio de Windows", "clock"),
    ("services", "Servicios", "server"),
    ("cleanup", "Limpieza", "sparkle"),
    ("optimization", "Optimización", "sliders"),
    (None, "SAFEBOOST", ""),
    ("history", "Historial y deshacer", "undo"),
    ("settings", "Ajustes", "gear"),
]
MODES = {"easy": EASY_NAV, "advanced": ADVANCED_NAV}
HOME_OF = {"easy": "home", "advanced": "dashboard"}


def fit_window(screen_w: int, screen_h: int, scaling: float) -> tuple[str, tuple[int, int], bool]:
    """Geometría para una pantalla de screen_w x screen_h píxeles físicos con ese escalado.

    Devuelve (geometría "AxB+X+Y" en píxeles lógicos, tamaño mínimo, maximizar). Función pura
    para poder probarla sin pantalla.
    """
    scaling = scaling or 1.0
    avail_w = int(screen_w / scaling) - SCREEN_MARGIN[0]
    avail_h = int(screen_h / scaling) - SCREEN_MARGIN[1]
    width = max(min(WINDOW_SIZE[0], avail_w), 640)
    height = max(min(WINDOW_SIZE[1], avail_h), 480)
    minimum = (min(WINDOW_MIN[0], width), min(WINDOW_MIN[1], height))
    maximize = width < WINDOW_SIZE[0] or height < WINDOW_SIZE[1]
    x = max((avail_w + SCREEN_MARGIN[0] - width) // 2, 0)
    y = max((avail_h - height) // 3, 0)
    return f"{width}x{height}+{x}+{y}", minimum, maximize


class MainWindow(ctk.CTk):
    def __init__(self, builder: Callable[[Callable[[str], None]], AppContext]) -> None:
        super().__init__()
        self.title(f"{WINDOW_TITLE} {APP_VERSION}")
        self._fit_to_screen()
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
            text=_("Detectando entorno (versión, edición, disco, dominio, impresoras)…"),
            font=FONT_H2,
        )
        self.loading.pack(expand=True)
        self.loading_step = ctk.CTkLabel(self, text="", font=FONT_BODY, text_color=TEXT_MUTED)
        self.loading_step.pack(pady=(0, PAD * 4))
        BackgroundTask(
            self,
            lambda progress, _c: builder(lambda step: progress(0.0, step)),
            self._build,
            self._fatal,
            self._loading_progress,
        ).start()

    def _loading_progress(self, _fraction: float, step: str) -> None:
        if self.loading_step.winfo_exists():
            self.loading_step.configure(text=f"{step}…")

    def report_callback_exception(self, exc: type, val: BaseException, tb: Any) -> None:
        """Errores en callbacks de Tk: informe en disco y aviso con dónde está."""
        from core.crash import write_report

        path = write_report(exc, val, tb, "interfaz")
        where = f"\n\nInforme guardado en:\n{path}" if path else ""
        messagebox.showerror(
            APP_NAME,
            f"Algo ha fallado: {val}{where}\n\nAjustes → Exportar log incluye este informe para "
            "que puedas enviarlo. SafeBoost sigue funcionando.",
            parent=self,
        )

    def _fit_to_screen(self) -> None:
        """Ajusta la ventana a la pantalla: centrada si cabe, maximizada si no."""
        geometry, minimum, maximize = fit_window(
            self.winfo_screenwidth(),
            self.winfo_screenheight(),
            ctk.ScalingTracker.get_window_scaling(self),
        )
        self.geometry(geometry)
        self.minsize(*minimum)
        if maximize and sys.platform == "win32":
            self.after(0, lambda: self.state("zoomed"))

    # ================================================================== construcción

    def _fatal(self, exc: BaseException) -> None:
        log.error("startup_failed", extra={"err": str(exc)})
        messagebox.showerror(APP_NAME, f"No se pudo iniciar SafeBoost:\n\n{exc}")
        self.destroy()

    def _build(self, app: AppContext) -> None:
        self.loading.destroy()
        self.loading_step.destroy()
        self.ui = UiState(app)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.configure(fg_color=BG_APP)
        sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0, fg_color=BG_SIDEBAR)
        sidebar.grid(row=0, column=0, rowspan=3, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar,
            text=f"  {APP_NAME}",
            image=icon("rocket", ("#2563eb", "#2f7bf5"), 26),
            compound="left",
            font=(FONT_H2[0], 20, "bold"),
            anchor="w",
        ).pack(fill="x", padx=PAD, pady=(PAD * 2, PAD))
        self.mode_label = ctk.CTkLabel(sidebar, text="", font=FONT_SMALL, wraplength=190)
        self.mode_label.pack(side="bottom", pady=(PAD_S, PAD))
        mode = app.settings.ui_mode if app.settings.ui_mode in MODES else "easy"
        self.mode_var = ctk.StringVar(value=_("Fácil") if mode == "easy" else _("Avanzado"))
        ctk.CTkSegmentedButton(
            sidebar,
            values=[_("Fácil"), _("Avanzado")],
            variable=self.mode_var,
            command=self._change_mode,
            height=34,
        ).pack(side="bottom", fill="x", padx=PAD, pady=(PAD_S, 0))
        ctk.CTkLabel(sidebar, text=_("Vista"), font=FONT_SMALL, text_color=TEXT_MUTED).pack(
            side="bottom", anchor="w", padx=PAD + 2
        )
        self.nav_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        self.nav_frame.pack(fill="both", expand=True)
        self.nav: dict[str, ctk.CTkButton] = {}
        self.mode = mode
        self._build_nav()

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_action_bar()
        self.log_panel = LogPanel(self, ui_log_queue())
        self.log_visible = False

        self.ui.subscribe(self.refresh_action_bar)
        self.refresh_action_bar()
        self.show(HOME_OF[self.mode])
        if app.settings.first_run:
            self.after(400, self.show_welcome)
        self._check_updates()
        self._run_slow_checks()
        self._run_watch()

    def _run_watch(self) -> None:
        """Vigilancia al abrir: programas nuevos, registro de salud e informe de mantenimiento."""
        if self.ui is None:
            return
        app = self.ui.app

        def work(_p: ProgressFn, _c: threading.Event) -> Any:
            from core.monitor import refresh  # carga los handlers de inicio: fuera del arranque

            return refresh(app)

        def done(result: Any) -> None:
            page = self.pages.get("dashboard")
            if isinstance(page, DashboardPage):
                page.show_watch(result)

        BackgroundTask(self, work, done, lambda _e: None).start()

    def _run_slow_checks(self) -> None:
        """Comprobaciones lentas (dxdiag para HAGS) con la ventana ya abierta; al terminar se
        refrescan las páginas para que el tweak afectado aparezca con su estado real."""
        if self.ui is None:
            return
        engine = self.ui.app.engine

        def done(resolved: list[str]) -> None:
            if resolved:
                self.invalidate_detections()

        BackgroundTask(self, lambda _p, _c: engine.run_slow_checks(), done, lambda _e: None).start()

    def show_welcome(self, on_done: Callable[[], None] | None = None) -> None:
        if self.ui is None:
            return
        app = self.ui.app
        if not app.env.supported:
            why = "Este Windows no está soportado: SafeBoost solo puede simular."
        elif not app.env.is_admin:
            why = "Sin permisos de administrador: solo se puede simular."
        else:
            why = ""

        def done(go_real: bool) -> None:
            app.settings.first_run = False
            if go_real:
                app.settings.dry_run = False
            try:
                app.settings.save()
            except OSError as exc:
                log.warning("settings_save_failed", extra={"err": str(exc)})
            self.refresh_action_bar()
            if on_done is not None:
                on_done()

        WelcomeWizard(self, can_go_real=not why, why_not=why, on_done=done)

    def _check_updates(self) -> None:
        if self.ui is None or not self.ui.app.settings.check_updates:
            return

        def done(info: ReleaseInfo | None) -> None:
            if info is None:
                return
            for key in ("home", "dashboard"):
                page = self.pages.get(key)
                if isinstance(page, (HomePage, DashboardPage)):
                    page.show_update(info)

        BackgroundTask(self, lambda _p, _c: check_latest(), done, lambda _e: None).start()

    def _build_action_bar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0, fg_color=BG_SIDEBAR)
        bar.grid(row=1, column=1, sticky="ew")
        self.selection_label = ctk.CTkLabel(bar, text="", font=FONT_BODY)
        self.selection_label.pack(side="left", padx=PAD, pady=PAD_S)
        self.log_btn = ctk.CTkButton(
            bar,
            text=_("Mostrar log"),
            width=110,
            **SECONDARY_BUTTON,
            command=self.toggle_log,
        )
        self.log_btn.pack(side="right", padx=PAD, pady=PAD_S)
        self.cancel_btn = ctk.CTkButton(
            bar, text=_("Cancelar"), width=90, fg_color=DANGER, command=self._cancel
        )
        self.apply_btn = ctk.CTkButton(
            bar, text=_("Revisar y aplicar"), width=150, command=self.review
        )
        self.apply_btn.pack(side="right", padx=PAD_S, pady=PAD_S)
        self.sim_btn = ctk.CTkButton(
            bar,
            text=_("Simular"),
            width=100,
            **SECONDARY_BUTTON,
            command=self.simulate,
        )
        self.sim_btn.pack(side="right", pady=PAD_S)
        self.progress = ProgressBar(bar)
        self.progress.pack(side="left", fill="x", expand=True, padx=PAD)

    # ================================================================== navegación

    def _build_nav(self) -> None:
        for child in self.nav_frame.winfo_children():
            child.destroy()
        self.nav = {}
        easy = self.mode == "easy"
        for key, label, icon_name in MODES[self.mode]:
            if key is None:
                ctk.CTkLabel(
                    self.nav_frame,
                    text=_(label),
                    font=(FONT_SMALL[0], 10, "bold"),
                    text_color=TEXT_MUTED,
                    anchor="w",
                ).pack(fill="x", padx=PAD + 4, pady=(PAD_S, 0))
                continue
            btn = ctk.CTkButton(
                self.nav_frame,
                text=f"  {_(label)}",
                image=icon(icon_name, ("#3b4350", "#aeb6c4"), 18 if easy else 16),
                compound="left",
                anchor="w",
                font=FONT_NAV if easy else FONT_BODY,
                # Avanzado: 30 px para que las 12 secciones quepan en 1366x768 al 125 %.
                height=40 if easy else 30,
                corner_radius=10,
                fg_color="transparent",
                text_color=TEXT,
                hover_color=NAV_HOVER,
                command=lambda k=key: self.show(k),
            )
            btn.pack(fill="x", padx=PAD_S + 2, pady=1)
            self.nav[key] = btn
        if self.current is not None:
            self._highlight(self.current)

    def _highlight(self, key: str) -> None:
        for name, btn in self.nav.items():
            btn.configure(fg_color=NAV_ACTIVE if name == key else "transparent")

    def _change_mode(self, value: str) -> None:
        if self.ui is None:
            return
        self.mode = "easy" if value == _("Fácil") else "advanced"
        settings = self.ui.app.settings
        settings.ui_mode = self.mode
        settings.save()
        self._build_nav()
        valid = {key for key, _l, _i in MODES[self.mode] if key}
        if self.current not in valid:
            self.show(HOME_OF[self.mode])

    def page(self, key: str) -> Page:
        """Página ya creada o nueva, sin mostrarla (para usar sus acciones desde otra página)."""
        if key not in self.pages:
            cls = next(c for k, _l, c in PAGES if k == key)
            page = cls(self.content, self)
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[key] = page
        return self.pages[key]

    def show(self, key: str) -> None:
        page = self.page(key)
        page.tkraise()
        self._highlight(key)
        self.current = key
        page.on_show()

    def toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_panel.grid(row=2, column=1, sticky="nsew", padx=PAD, pady=(0, PAD))
            self.log_btn.configure(text=_("Ocultar log"))
        else:
            self.log_panel.grid_forget()
            self.log_btn.configure(text=_("Mostrar log"))

    def refresh_action_bar(self) -> None:
        if self.ui is None:
            return
        app = self.ui.app
        count = len(self.ui.selected)
        os_allowed = app.env.supported or app.settings.allow_unsupported_os
        self.selection_label.configure(text=_("{n} cambios seleccionados", n=count))
        if app.settings.dry_run:
            self.mode_label.configure(
                text=_("MODO SIMULACIÓN\nno se cambia nada"), text_color=RISK_COLORS["medio"]
            )
        elif not os_allowed:
            self.mode_label.configure(
                text=_("Windows no soportado\nsolo simulación"), text_color=DANGER
            )
        elif not app.env.is_admin:
            self.mode_label.configure(text=_("Sin permisos de administrador"), text_color=DANGER)
        else:
            self.mode_label.configure(text=_("Modo real"), text_color=TEXT_MUTED)
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
            # En modo portable el USB puede no estar tras reiniciar: no se programa la tarea.
            if (
                not PORTABLE_MODE
                and app.settings.measure_boot_after_reboot
                and any(r.status in ("applied", "partial") for r in session.results.values())
            ):
                progress(1.0, "Programando la medición tras reiniciar…")
                schedule_post_reboot_capture(app.runner, self_command(), process_user())
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
