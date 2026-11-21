"""Gestor de programas de inicio."""

from __future__ import annotations

import threading
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.session import Session
from tweaks.startup import StartupEntry, StartupManager
from ui.pages.base import Page, show_error
from ui.theme import FONT_BODY, FONT_SMALL, PAD, PAD_S, RISK_COLORS, STATE_COLORS, TEXT_MUTED, WRAP
from ui.widgets import Badge, Card
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow

IMPACT_COLORS = {
    "alto": RISK_COLORS["alto"],
    "medio": RISK_COLORS["medio"],
    "bajo": RISK_COLORS["bajo"],
    "desconocido": STATE_COLORS["unknown"],
}
SOURCE_LABELS = {
    "run": "Registro",
    "run32": "Registro (32 bits)",
    "folder": "Carpeta Inicio",
    "task": "Tarea programada",
}


class StartupPage(Page):
    title = "Programas de inicio"
    subtitle = (
        "Se desactivan igual que en el Administrador de tareas (sin borrar nada). El impacto es "
        "una estimación: Windows no expone el valor del Administrador de tareas por API."
    )

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        app = self.state.app
        self.manager = StartupManager(app.registry, app.runner, app.engine.tasks, app.env)
        self.entries: list[StartupEntry] = []
        self.pending: dict[str, bool] = {}
        self._loaded = False

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD, pady=PAD_S)
        ctk.CTkButton(bar, text="Actualizar", width=110, command=self.load).pack(side="left")
        self.apply_btn = ctk.CTkButton(
            bar, text="Aplicar cambios", width=150, state="disabled", command=self._apply
        )
        self.apply_btn.pack(side="left", padx=PAD_S)
        self.status = ctk.CTkLabel(bar, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.status.pack(side="right")
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

    def on_show(self) -> None:
        if not self._loaded:
            self.load()

    def load(self) -> None:
        self._loaded = True
        self.status.configure(text="Analizando programas de inicio…")

        def work(_p: ProgressFn, _c: threading.Event) -> list[StartupEntry]:
            return self.manager.list()

        BackgroundTask(
            self, work, self._render, lambda e: self.status.configure(text=f"Error: {e}")
        ).start()

    def _render(self, entries: list[StartupEntry]) -> None:
        self.entries = entries
        self.pending.clear()
        self.apply_btn.configure(state="disabled")
        for child in self.body.winfo_children():
            child.destroy()
        if not entries:
            ctk.CTkLabel(self.body, text="No hay programas de inicio.", font=FONT_BODY).pack()
        for entry in entries:
            card = Card(self.body)
            card.pack(fill="x", pady=3)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=PAD, pady=(PAD_S, 0))
            var = ctk.BooleanVar(value=entry.enabled)
            ctk.CTkSwitch(
                top,
                text=entry.name,
                variable=var,
                font=FONT_BODY,
                command=lambda e=entry, v=var: self._toggle(e, v.get()),
            ).pack(side="left")
            Badge(top, f"impacto {entry.impact}", IMPACT_COLORS[entry.impact]).pack(
                side="left", padx=PAD_S
            )
            ctk.CTkLabel(
                top, text=SOURCE_LABELS[entry.source], font=FONT_SMALL, text_color=TEXT_MUTED
            ).pack(side="right")
            ctk.CTkLabel(
                card,
                text=f"{entry.command}\n{entry.impact_detail}",
                font=FONT_SMALL,
                text_color=TEXT_MUTED,
                justify="left",
                wraplength=WRAP,
                anchor="w",
            ).pack(anchor="w", padx=PAD * 2, pady=(0, PAD_S))
        enabled = sum(1 for e in entries if e.enabled)
        self.status.configure(text=f"{len(entries)} entradas · {enabled} activas")

    def _toggle(self, entry: StartupEntry, value: bool) -> None:
        if value == entry.enabled:
            self.pending.pop(entry.key, None)
        else:
            self.pending[entry.key] = value
        self.apply_btn.configure(state="normal" if self.pending else "disabled")

    def _apply(self) -> None:
        app = self.state.app
        changes = [(e, self.pending[e.key]) for e in self.entries if e.key in self.pending]
        lines = [f"{'Activar' if v else 'Desactivar'}: {e.name}" for e, v in changes]
        if app.settings.dry_run:
            messagebox.showinfo(
                "Simulación",
                "Modo simulación activo. Se aplicaría:\n\n" + "\n".join(lines),
                parent=self,
            )
            return
        if not messagebox.askyesno("Confirmar", "\n".join(lines) + "\n\n¿Aplicar?", parent=self):
            return

        def work(progress: ProgressFn, _c: threading.Event) -> list[str]:
            session = Session.new("apply", env=app.env.to_dict())
            errors = []
            for index, (entry, value) in enumerate(changes):
                progress(index / len(changes), entry.name)
                try:
                    self.manager.set_enabled(entry, value, session)
                except Exception as exc:  # noqa: BLE001 - se informa por entrada sin abortar
                    errors.append(f"{entry.name}: {exc}")
            if session.changes:
                app.store.save(session)
            return errors

        def done(errors: list[str]) -> None:
            if errors:
                show_error("Algunos cambios fallaron", "\n".join(errors), self)
            self.load()

        self.main.run_long(work, done, "Error en programas de inicio")
