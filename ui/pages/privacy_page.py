"""Privacidad: qué apps han usado la cámara, el micrófono y la ubicación, y cuándo."""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.privacy import CapabilityReport, read_privacy
from ui.pages.base import Page
from ui.theme import (
    DANGER,
    FONT_BODY,
    FONT_H2,
    FONT_SMALL,
    PAD,
    PAD_S,
    RISK_COLORS,
    SECONDARY_BUTTON,
    TEXT_MUTED,
    WRAP,
)
from ui.widgets import Card
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow

MAX_APPS = 10


def open_settings(uri: str) -> None:
    if sys.platform == "win32":
        os.startfile(uri)  # noqa: S606 - URI ms-settings fija
    else:
        webbrowser.open(uri)


class PrivacyPage(Page):
    title = "Privacidad"
    subtitle = (
        "Qué programas han usado la cámara, el micrófono y la ubicación, y cuándo. Para quitar "
        "un permiso se abre la página correspondiente de Configuración de Windows."
    )

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self._loaded = False

    def on_show(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        registry = self.state.app.registry

        def work(_p: ProgressFn, _c: threading.Event) -> list[CapabilityReport]:
            return read_privacy(registry)

        BackgroundTask(self, work, self.render, lambda _e: None).start()

    def render(self, reports: list[CapabilityReport]) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        for report in reports:
            head = ctk.CTkFrame(self.body, fg_color="transparent")
            head.pack(fill="x", pady=(PAD, PAD_S))
            ctk.CTkLabel(head, text=report.label, font=FONT_H2).pack(side="left")
            status = {True: "permitido", False: "bloqueado para todas las apps", None: ""}[
                report.globally_allowed
            ]
            if status:
                ctk.CTkLabel(
                    head, text=f"  ({status})", font=FONT_SMALL, text_color=TEXT_MUTED
                ).pack(side="left")
            ctk.CTkButton(
                head,
                text="Abrir ajustes de Windows",
                width=200,
                **SECONDARY_BUTTON,
                command=lambda uri=report.settings_uri: open_settings(uri),
            ).pack(side="right")
            card = Card(self.body)
            card.pack(fill="x")
            if not report.apps:
                ctk.CTkLabel(card, text="Ningún programa lo ha usado.", font=FONT_BODY).pack(
                    anchor="w", padx=PAD, pady=PAD
                )
                continue
            for app in report.apps[:MAX_APPS]:
                row = ctk.CTkFrame(card, fg_color="transparent")
                row.pack(fill="x", padx=PAD, pady=2)
                when = (
                    app.last_start.astimezone().strftime("%Y-%m-%d %H:%M")
                    if app.last_start
                    else "?"
                )
                ctk.CTkLabel(row, text=app.app, font=FONT_BODY).pack(side="left")
                if app.in_use:
                    ctk.CTkLabel(
                        row, text="  EN USO AHORA", font=FONT_SMALL, text_color=DANGER
                    ).pack(side="left")
                if app.allowed is False:
                    ctk.CTkLabel(
                        row, text="  (bloqueado)", font=FONT_SMALL, text_color=RISK_COLORS["bajo"]
                    ).pack(side="left")
                ctk.CTkLabel(
                    row, text=f"último uso: {when}", font=FONT_SMALL, text_color=TEXT_MUTED
                ).pack(side="right")
            if len(report.apps) > MAX_APPS:
                ctk.CTkLabel(
                    card,
                    text=f"… y {len(report.apps) - MAX_APPS} más",
                    font=FONT_SMALL,
                    text_color=TEXT_MUTED,
                    wraplength=WRAP,
                ).pack(anchor="w", padx=PAD)
            ctk.CTkFrame(card, height=PAD_S, fg_color="transparent").pack()
