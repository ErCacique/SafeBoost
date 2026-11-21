"""Ajustes de SafeTrim."""

from __future__ import annotations

import logging
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.constants import APP_HOME, APP_VERSION, LOG_DIR
from core.logger import ROOT_LOGGER_NAME, export_logs
from core.restore import RestoreResult
from ui.pages.base import Page, open_path, show_error
from ui.theme import (
    FONT_BODY,
    FONT_H2,
    FONT_SMALL,
    PAD,
    PAD_S,
    RISK_COLORS,
    SECONDARY_BUTTON,
    TEXT_MUTED,
)
from ui.widgets import Card

if TYPE_CHECKING:
    from ui.app import MainWindow


class SettingsPage(Page):
    title = "Ajustes"
    subtitle = f"SafeTrim {APP_VERSION} · Datos en {APP_HOME}"

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        settings = self.state.app.settings
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        safety = self._section(body, "Seguridad")
        self.dry_run = ctk.BooleanVar(value=settings.dry_run)
        ctk.CTkSwitch(
            safety,
            text="Modo simulación (dry-run): mostrar cambios sin ejecutarlos",
            variable=self.dry_run,
            font=FONT_BODY,
            command=self._save,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        self.backups = ctk.BooleanVar(value=settings.export_reg_backups)
        ctk.CTkSwitch(
            safety,
            text="Exportar copias .reg de las claves afectadas",
            variable=self.backups,
            font=FONT_BODY,
            command=self._save,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        self.measure_boot = ctk.BooleanVar(value=settings.measure_boot_after_reboot)
        ctk.CTkSwitch(
            safety,
            text="Medir el arranque automáticamente tras el próximo reinicio (tarea temporal)",
            variable=self.measure_boot,
            font=FONT_BODY,
            command=self._save,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        self.no_restore = ctk.BooleanVar(value=settings.allow_without_restore_point)
        ctk.CTkSwitch(
            safety,
            text="Continuar si no se puede crear el punto de restauración (no recomendado)",
            variable=self.no_restore,
            font=FONT_BODY,
            text_color=RISK_COLORS["alto"],
            command=self._toggle_no_restore,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        protection = self.state.app.engine.restore.protection_enabled()
        text = {True: "activada", False: "DESACTIVADA", None: "desconocida"}[protection]
        row = ctk.CTkFrame(safety, fg_color="transparent")
        row.pack(fill="x", padx=PAD, pady=(0, PAD))
        ctk.CTkLabel(
            row, text=f"Protección del sistema: {text}", font=FONT_SMALL, text_color=TEXT_MUTED
        ).pack(side="left")
        if protection is not True:
            ctk.CTkButton(
                row,
                text="Activar en la unidad del sistema",
                width=220,
                command=self._enable_protection,
            ).pack(side="left", padx=PAD)

        other = self._section(body, "General")
        self.check_updates = ctk.BooleanVar(value=settings.check_updates)
        ctk.CTkSwitch(
            other,
            text="Avisar de versiones nuevas (consulta GitHub al arrancar; no envía datos tuyos)",
            variable=self.check_updates,
            font=FONT_BODY,
            command=self._save,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        ctk.CTkButton(
            other,
            text="Ver la guía de primeros pasos",
            width=240,
            **SECONDARY_BUTTON,
            command=lambda: self.main.show_welcome(
                on_done=lambda: self.dry_run.set(self.state.app.settings.dry_run)
            ),
        ).pack(anchor="w", padx=PAD, pady=(PAD_S, PAD))

        look = self._section(body, "Apariencia")
        self.appearance = ctk.StringVar(value=settings.appearance)
        ctk.CTkSegmentedButton(
            look,
            values=["dark", "light", "system"],
            variable=self.appearance,
            command=self._appearance,
        ).pack(anchor="w", padx=PAD, pady=PAD)

        logs = self._section(body, "Logs")
        self.level = ctk.StringVar(value=settings.log_level)
        row = ctk.CTkFrame(logs, fg_color="transparent")
        row.pack(fill="x", padx=PAD, pady=PAD)
        ctk.CTkOptionMenu(
            row, values=["DEBUG", "INFO", "WARNING"], variable=self.level, command=self._log_level
        ).pack(side="left")
        ctk.CTkButton(row, text="Exportar log…", command=self._export).pack(side="left", padx=PAD)
        ctk.CTkButton(
            row,
            text="Abrir carpeta de logs",
            **SECONDARY_BUTTON,
            command=lambda: open_path(LOG_DIR),
        ).pack(side="left")

    def _section(self, parent: Any, title: str) -> Card:
        ctk.CTkLabel(parent, text=title, font=FONT_H2).pack(anchor="w", pady=(PAD, PAD_S))
        card = Card(parent)
        card.pack(fill="x")
        return card

    def _save(self) -> None:
        settings = self.state.app.settings
        settings.dry_run = self.dry_run.get()
        settings.export_reg_backups = self.backups.get()
        settings.measure_boot_after_reboot = self.measure_boot.get()
        settings.allow_without_restore_point = self.no_restore.get()
        settings.appearance = self.appearance.get()
        settings.log_level = self.level.get()
        settings.check_updates = self.check_updates.get()
        settings.save()
        self.main.refresh_action_bar()

    def _toggle_no_restore(self) -> None:
        if self.no_restore.get() and not messagebox.askyesno(
            "Sin punto de restauración",
            "Si el punto de restauración falla, SafeTrim seguirá aplicando cambios. Deshacer "
            "seguirá funcionando, pero no tendrás la red de seguridad de Windows. ¿Seguro?",
            icon="warning",
            parent=self,
        ):
            self.no_restore.set(False)
        self._save()

    def _enable_protection(self) -> None:
        restore = self.state.app.engine.restore

        def done(result: RestoreResult) -> None:
            show = messagebox.showinfo if result.ok else messagebox.showerror
            show("Protección del sistema", result.message, parent=self)

        self.main.run_long(
            lambda _p, _c: restore.enable_protection(), done, "Protección del sistema"
        )

    def _appearance(self, value: str) -> None:
        ctk.set_appearance_mode(value)
        self._save()

    def _log_level(self, value: str) -> None:
        logging.getLogger(ROOT_LOGGER_NAME).setLevel(value)
        self._save()

    def _export(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Carpeta de destino")
        if not folder:
            return
        try:
            target = export_logs(Path(folder))
        except OSError as exc:
            show_error("Exportar log", exc, self)
            return
        messagebox.showinfo("Exportar log", f"Log exportado en:\n{target}", parent=self)
