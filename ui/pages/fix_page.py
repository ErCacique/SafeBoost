"""Arreglar mi PC (paso 1 de 2): el plan para este equipo, con una casilla por cambio.

El paso 2 son la revisión y el resumen de siempre (ReviewDialog y SummaryDialog, con el antes y
el después): esta página solo prepara la selección, así que aplicar y deshacer siguen pasando por
el mismo motor y el mismo historial.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.fixplan import FixPlan, build_plan
from core.i18n import _
from ui.icons import icon
from ui.pages.base import Page, show_error
from ui.theme import (
    BG_CARD_HI,
    FONT_BODY,
    FONT_H2,
    FONT_HERO,
    FONT_SMALL,
    PAD,
    PAD_S,
    PRIMARY_BUTTON,
    SECONDARY_BUTTON,
    TEXT_MUTED,
    WRAP,
)
from ui.widgets import Card, Chip, IconBadge
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow

PROFILE_NAMES = {1: "Conservador", 2: "Equilibrado", 3: "Máximo"}


def compute_plan(app: Any) -> FixPlan:
    """Diagnóstico + programas de inicio + limpiezas disponibles → plan (en segundo plano)."""
    from core.diagnostics import collect
    from core.fixplan import FIX_CLEANUPS
    from core.metrics import recommend_profile
    from tweaks.startup import StartupManager

    report = collect(app.env, app.registry, app.runner)
    entries = StartupManager(app.registry, app.runner, app.engine.tasks, app.env).list()
    startup = [(e.name, _file_of(e.command), e.impact) for e in entries if e.enabled]
    engine = app.engine
    cleanups = [
        tid
        for tid in FIX_CLEANUPS
        if tid in engine.catalog and engine.evaluate(engine.catalog.get(tid)).applicable
    ]
    return build_plan(report, recommend_profile(app.env, report.snapshot), startup, cleanups)


def _file_of(command: str) -> str:
    from tweaks.startup import executable_from_command

    exe = executable_from_command(command)
    return exe.name if exe else ""


class FixPage(Page):
    title = "Arreglar mi PC"
    subtitle = ""

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.plan: FixPlan | None = None
        self._running = False
        self.choices: dict[str, ctk.BooleanVar] = {}
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

    # ------------------------------------------------------------------ datos

    def on_show(self) -> None:
        if self.plan is None:
            self.load()

    def load(self) -> None:
        if self._running:
            return
        self._running = True
        self._clear()
        ctk.CTkLabel(
            self.body,
            text=_("Preparando el plan para tu equipo… (unos segundos; no se cambia nada)"),
            font=FONT_BODY,
            text_color=TEXT_MUTED,
        ).pack(anchor="w", pady=PAD)
        app = self.state.app

        def work(_p: ProgressFn, _c: threading.Event) -> FixPlan:
            return compute_plan(app)

        def done(plan: FixPlan) -> None:
            self._running = False
            self.plan = plan
            self.render(plan)

        def failed(exc: BaseException) -> None:
            self._running = False
            self._clear()
            show_error(_("Arreglar mi PC"), exc, self)

        BackgroundTask(self, work, done, failed).start()

    # ------------------------------------------------------------------ presentación

    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.choices = {}

    def _back(self) -> None:
        from ui.app import HOME_OF

        self.main.show(HOME_OF.get(self.main.mode, "home"))

    def render(self, plan: FixPlan) -> None:
        self._clear()
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x", pady=(PAD_S, PAD_S))
        ctk.CTkButton(
            top,
            text=_("Volver"),
            image=icon("back", ("#1b1f24", "#c9d0db"), 16),
            compound="left",
            width=100,
            **SECONDARY_BUTTON,
            command=self._back,
        ).pack(side="left")
        ctk.CTkButton(
            top, text=_("Volver a calcular"), width=150, **SECONDARY_BUTTON, command=self.load
        ).pack(side="right")
        Chip(self.body, _("PASO 1 DE 2 · REVISA EL PLAN"), "info").pack(anchor="w", pady=(PAD, 0))
        ctk.CTkLabel(
            self.body,
            text=_("Esto es lo que haremos para acelerar tu PC"),
            font=FONT_HERO,
            anchor="w",
        ).pack(anchor="w", pady=(PAD_S, 0))
        ctk.CTkLabel(
            self.body,
            text=_(
                "Lo hemos elegido según tu equipo. Quita lo que no quieras. Antes de aplicar verás "
                "el detalle de cada cambio, y todo se puede deshacer desde «Deshacer cambios»."
            ),
            font=FONT_BODY,
            text_color=TEXT_MUTED,
            wraplength=WRAP,
            justify="left",
        ).pack(anchor="w", pady=(PAD_S, PAD))

        if plan.first:
            self._notice(_("Antes de nada"), plan.first, "warning", "alert")

        if plan.level is not None:
            name = _(PROFILE_NAMES.get(plan.level, ""))
            self._choice(
                "profile",
                "sliders",
                _("Aplicar el perfil {n} · {name}", n=plan.level, name=name),
                plan.why,
            )
        if plan.cleanups:
            self._choice(
                "cleanup",
                "trash",
                _("Borrar archivos temporales y miniaturas"),
                _("Libera espacio. No se puede deshacer, por eso se confirma aparte."),
            )
        if plan.level is None and not plan.cleanups:
            self._notice(_("No hay cambios que aplicar ahora"), [plan.why], "neutral", "check")
        if plan.startup:
            names = ", ".join(c.name for c in plan.startup[:5])
            self._link(
                "clock",
                _("Revisar {n} programas que se abren al encender", n=len(plan.startup)),
                names,
                lambda: self.main.show("startup"),
            )
        if plan.hardware:
            self._notice(_("Lo que ningún ajuste arregla"), plan.hardware, "info", "memory")

        footer = ctk.CTkFrame(self.body, fg_color="transparent")
        footer.pack(fill="x", pady=(PAD, PAD))
        self.apply_btn = ctk.CTkButton(
            footer,
            text="",
            image=icon("bolt", ("#ffffff", "#ffffff"), 18),
            compound="left",
            font=(FONT_H2[0], 15, "bold"),
            height=46,
            width=220,
            **PRIMARY_BUTTON,
            command=self.apply,
        )
        self.apply_btn.pack(side="left")
        ctk.CTkLabel(
            footer,
            text="  "
            + (
                _("Todo se puede deshacer salvo la limpieza de archivos")
                if plan.cleanups
                else _("Todo se puede deshacer")
            ),
            image=icon("undo", ("#1e7d46", "#6ee7a0"), 16),
            compound="left",
            font=FONT_SMALL,
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=PAD)
        self._update_count()

    def _row(self, icon_name: str, tone: str) -> tuple[Card, ctk.CTkFrame]:
        card = Card(self.body)
        card.pack(fill="x", pady=PAD_S)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=PAD + 4, pady=PAD + 2)
        IconBadge(row, icon_name, tone, 40).pack(side="left", anchor="n")
        texts = ctk.CTkFrame(row, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, padx=(PAD, 0))
        return card, texts

    def _choice(self, key: str, icon_name: str, title: str, detail: str) -> None:
        _card, texts = self._row(icon_name, "info")
        var = ctk.BooleanVar(value=True)
        self.choices[key] = var
        ctk.CTkCheckBox(
            texts,
            text=title,
            variable=var,
            font=FONT_H2,
            command=self._update_count,
        ).pack(anchor="w")
        ctk.CTkLabel(
            texts,
            text=detail,
            font=FONT_BODY,
            text_color=TEXT_MUTED,
            wraplength=WRAP - 100,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=(30, 0), pady=(2, 0))

    def _link(self, icon_name: str, title: str, detail: str, command: Any) -> None:
        _card, texts = self._row(icon_name, "warning")
        ctk.CTkLabel(texts, text=title, font=FONT_H2, anchor="w").pack(anchor="w")
        ctk.CTkLabel(
            texts,
            text=detail,
            font=FONT_BODY,
            text_color=TEXT_MUTED,
            wraplength=WRAP - 100,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(2, PAD_S))
        ctk.CTkButton(
            texts, text=_("Ver en Arranque"), width=150, **SECONDARY_BUTTON, command=command
        ).pack(anchor="w")

    def _notice(self, title: str, lines: list[str], tone: str, icon_name: str) -> None:
        card, texts = self._row(icon_name, tone)
        card.configure(fg_color=BG_CARD_HI)
        ctk.CTkLabel(texts, text=title, font=FONT_H2, anchor="w").pack(anchor="w")
        for line in lines:
            ctk.CTkLabel(
                texts,
                text=f"• {line}",
                font=FONT_BODY,
                text_color=TEXT_MUTED,
                wraplength=WRAP - 100,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))

    def _update_count(self) -> None:
        count = sum(1 for v in self.choices.values() if v.get())
        self.apply_btn.configure(
            text=_("Aplicar {n} cambios", n=count) if count != 1 else _("Aplicar 1 cambio"),
            state="normal" if count else "disabled",
        )

    # ------------------------------------------------------------------ acción

    def apply(self) -> None:
        plan = self.plan
        if plan is None:
            return
        state = self.state
        chosen = {k for k, v in self.choices.items() if v.get()}
        if "profile" in chosen and plan.level is not None:
            state.apply_profile(plan.level)
            dashboard = self.main.pages.get("dashboard")
            if dashboard is not None and hasattr(dashboard, "profile_var"):
                dashboard.profile_var.set(plan.level)
        if "cleanup" in chosen:
            state.selected |= set(plan.cleanups)
        state.notify()
        # Tras aplicar, el Inicio y este plan se recalculan al volver a mostrarlos.
        self.plan = None
        home = self.main.pages.get("home")
        if home is not None and hasattr(home, "data"):
            home.data = None
        # Paso 2: la revisión de siempre (en modo simulación, solo la simulación).
        if state.app.settings.dry_run:
            self.main.simulate()
        else:
            self.main.review()
