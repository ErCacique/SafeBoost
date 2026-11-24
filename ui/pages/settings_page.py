"""Ajustes de SafeBoost."""

from __future__ import annotations

import logging
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.constants import APP_HOME, APP_NAME, APP_VERSION, LOG_DIR, self_command
from core.i18n import LANGUAGES, _
from core.license import (
    Branding,
    LicenseError,
    load_license,
    remove_license,
    save_license,
    set_logo,
)
from core.logger import ROOT_LOGGER_NAME, export_logs
from core.restore import RestoreResult
from core.tray import remove_tray, schedule_tray
from core.update_check import UpdateCheck, check_update
from core.watch import remove_maintenance, schedule_maintenance
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
    WRAP,
)
from ui.widgets import Card
from ui.worker import BackgroundTask

if TYPE_CHECKING:
    from ui.app import MainWindow


class SettingsPage(Page):
    title = "Ajustes"
    subtitle = f"SafeBoost {APP_VERSION} · Datos en {APP_HOME}"

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
        update_row = ctk.CTkFrame(other, fg_color="transparent")
        update_row.pack(anchor="w", padx=PAD, pady=(0, PAD_S))
        self.update_check_btn = ctk.CTkButton(
            update_row,
            text=_("Buscar actualizaciones"),
            width=190,
            **SECONDARY_BUTTON,
            command=self._check_now,
        )
        self.update_check_btn.pack(side="left")
        self.update_status = ctk.CTkLabel(
            update_row, text=f"{APP_NAME} {APP_VERSION}", font=FONT_SMALL, text_color=TEXT_MUTED
        )
        self.update_status.pack(side="left", padx=PAD)
        self.maintenance = ctk.BooleanVar(value=settings.maintenance)
        ctk.CTkSwitch(
            other,
            text="Mantenimiento mensual: limpiar temporales, comprobar cambios deshechos y "
            "avisar de programas nuevos (tarea programada cada 4 semanas)",
            variable=self.maintenance,
            font=FONT_BODY,
            command=self._toggle_maintenance,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        self.background = ctk.BooleanVar(value=settings.background_watch)
        ctk.CTkSwitch(
            other,
            text="Vigilancia en segundo plano: icono junto al reloj que avisa al momento cuando "
            "un programa se añade al inicio",
            variable=self.background,
            font=FONT_BODY,
            command=self._toggle_background,
        ).pack(anchor="w", padx=PAD, pady=PAD_S)
        self.auto_game = ctk.BooleanVar(value=settings.auto_game_mode)
        ctk.CTkSwitch(
            other,
            text="Con la vigilancia: activar el modo juego al abrir un juego (Steam, Epic, GOG, "
            "Xbox…) y desactivarlo al cerrarlo",
            variable=self.auto_game,
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

        lang_row = ctk.CTkFrame(other, fg_color="transparent")
        lang_row.pack(anchor="w", padx=PAD, pady=(0, PAD))
        ctk.CTkLabel(
            lang_row, text=_("Idioma (requiere reiniciar SafeBoost)"), font=FONT_BODY
        ).pack(side="left")
        self.language = ctk.StringVar(value=LANGUAGES.get(settings.language, "Español"))
        ctk.CTkOptionMenu(
            lang_row,
            values=list(LANGUAGES.values()),
            variable=self.language,
            command=lambda _v: self._save(),
        ).pack(side="left", padx=PAD)

        self._build_license(body)

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
        settings.maintenance = self.maintenance.get()
        settings.background_watch = self.background.get()
        settings.auto_game_mode = self.auto_game.get()
        names = {v: k for k, v in LANGUAGES.items()}
        settings.language = names.get(self.language.get(), "es")
        settings.save()
        self.main.refresh_action_bar()

    def _toggle_maintenance(self) -> None:
        app = self.state.app
        enabled = self.maintenance.get()
        user = app.env.interactive_user

        def work(_p: Any, _c: Any) -> bool:
            if not enabled:
                remove_maintenance(app.runner)
                return True
            return bool(user) and schedule_maintenance(app.runner, self_command(), user)

        def done(ok: bool) -> None:
            if not ok:
                self.maintenance.set(False)
                messagebox.showerror(
                    "Mantenimiento mensual",
                    "No se pudo programar la tarea. Revisa el log para ver el motivo.",
                    parent=self,
                )
            self._save()

        self.main.run_long(work, done, "Mantenimiento mensual")

    def _toggle_no_restore(self) -> None:
        if self.no_restore.get() and not messagebox.askyesno(
            "Sin punto de restauración",
            "Si el punto de restauración falla, SafeBoost seguirá aplicando cambios. Deshacer "
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

    def _toggle_background(self) -> None:
        app = self.state.app
        enabled = self.background.get()
        user = app.env.interactive_user

        def work(_p: Any, _c: Any) -> bool:
            if not enabled:
                remove_tray(app.runner)
                return True
            return bool(user) and schedule_tray(app.runner, self_command(), user)

        def done(ok: bool) -> None:
            if not ok:
                self.background.set(False)
                messagebox.showerror(
                    "Vigilancia en segundo plano",
                    "No se pudo programar la tarea. Revisa el log para ver el motivo.",
                    parent=self,
                )
            self._save()

        self.main.run_long(work, done, "Vigilancia en segundo plano")

    # ------------------------------------------------------------------ edición Técnico

    def _build_license(self, body: Any) -> None:
        card = self._section(body, "Edición Técnico")
        self.license_label = ctk.CTkLabel(
            card, text="", font=FONT_BODY, wraplength=WRAP, justify="left"
        )
        self.license_label.pack(anchor="w", padx=PAD, pady=(PAD, PAD_S))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(anchor="w", padx=PAD, pady=(0, PAD_S))
        ctk.CTkButton(row, text="Introducir licencia…", command=self._enter_license).pack(
            side="left"
        )
        self.remove_license_btn = ctk.CTkButton(
            row, text="Quitar licencia", **SECONDARY_BUTTON, command=self._remove_license
        )
        self.remove_license_btn.pack(side="left", padx=PAD_S)
        self.brand_frame = ctk.CTkFrame(card, fg_color="transparent")
        branding = Branding.load()
        self.brand_business = ctk.StringVar(value=branding.business)
        self.brand_contact = ctk.StringVar(value=branding.contact)
        for label, var in (
            ("Nombre o empresa", self.brand_business),
            ("Contacto (teléfono, web…)", self.brand_contact),
        ):
            line = ctk.CTkFrame(self.brand_frame, fg_color="transparent")
            line.pack(fill="x", pady=2)
            ctk.CTkLabel(line, text=label, font=FONT_BODY, width=200, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(line, textvariable=var, width=320)
            entry.pack(side="left")
            entry.bind("<FocusOut>", lambda _e: self._save_branding())
        logo_row = ctk.CTkFrame(self.brand_frame, fg_color="transparent")
        logo_row.pack(fill="x", pady=(PAD_S, 0))
        ctk.CTkButton(
            logo_row, text="Elegir logo (PNG o JPG)…", **SECONDARY_BUTTON, command=self._pick_logo
        ).pack(side="left")
        self.logo_label = ctk.CTkLabel(logo_row, text="", font=FONT_BODY)
        self.logo_label.pack(side="left", padx=PAD)
        self._refresh_license()

    def _refresh_license(self) -> None:
        lic = load_license()
        if lic is None:
            self.license_label.configure(
                text="Sin licencia. Con la edición Técnico, el informe para el cliente lleva tu "
                "nombre, tu contacto y tu logo. El resto de SafeBoost es igual en las dos "
                "ediciones."
            )
            self.remove_license_btn.pack_forget()
            self.brand_frame.pack_forget()
            return
        until = f"hasta el {lic.expires}" if lic.expires else "sin caducidad"
        self.license_label.configure(
            text=f"Edición {lic.edition_label} · {lic.holder} · {until}. Estos datos aparecen en "
            "la cabecera del informe para el cliente (Diagnóstico → Informe para el cliente)."
        )
        self.remove_license_btn.pack(side="left", padx=PAD_S)
        self.brand_frame.pack(fill="x", padx=PAD, pady=(0, PAD))
        self.logo_label.configure(text="Logo elegido" if Branding.load().has_logo else "Sin logo")

    def _enter_license(self) -> None:
        text = ctk.CTkInputDialog(
            title="Licencia Técnico", text="Pega la licencia (empieza por ST1.):"
        ).get_input()
        if not text:
            return
        try:
            lic = save_license(text)
        except LicenseError as exc:
            messagebox.showerror("Licencia", str(exc), parent=self)
            return
        messagebox.showinfo("Licencia", f"Licencia activada para {lic.holder}.", parent=self)
        self._refresh_license()

    def _remove_license(self) -> None:
        if messagebox.askyesno(
            "Licencia",
            "¿Quitar la licencia de este equipo? Podrás volver a introducirla.",
            parent=self,
        ):
            remove_license()
            self._refresh_license()

    def _save_branding(self) -> None:
        branding = Branding.load()
        branding.business = self.brand_business.get().strip()
        branding.contact = self.brand_contact.get().strip()
        branding.save()

    def _pick_logo(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Logo para el informe",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg")],
        )
        if not path:
            return
        self._save_branding()
        try:
            set_logo(Path(path), Branding.load())
        except (LicenseError, OSError) as exc:
            messagebox.showerror("Logo", str(exc), parent=self)
            return
        self._refresh_license()

    # ------------------------------------------------------------------ actualizaciones

    def _check_now(self) -> None:
        self.update_check_btn.configure(state="disabled")
        self.update_status.configure(text=_("Comprobando…"), text_color=TEXT_MUTED)

        def work(_p: Any, _c: Any) -> UpdateCheck:
            return check_update()

        def done(result: UpdateCheck) -> None:
            self.update_check_btn.configure(state="normal")
            if result.status == "latest":
                self.update_status.configure(
                    text=_("Tienes la última versión ({v})", v=APP_VERSION),
                    text_color=RISK_COLORS["bajo"],
                )
                return
            if result.status == "error":
                self.update_status.configure(
                    text=_("No se pudo comprobar: {why}", why=_(result.message)),
                    text_color=RISK_COLORS["medio"],
                )
                return
            info = result.info
            assert info is not None  # noqa: S101 - status "new" siempre trae la versión
            self.update_status.configure(
                text=_("Hay una versión nueva: {v}", v=info.version),
                text_color=RISK_COLORS["medio"],
            )
            if messagebox.askyesno(
                _("Buscar actualizaciones"),
                _(
                    "Hay una versión nueva de SafeBoost: {v} (tienes {mine}). ¿Descargarla e "
                    "instalarla ahora? Tus datos se conservan.",
                    v=info.version,
                    mine=APP_VERSION,
                ),
                parent=self,
            ):
                from ui.pages.dashboard import DashboardPage

                dashboard = self.main.page("dashboard")
                if isinstance(dashboard, DashboardPage):
                    dashboard.show_update(info)
                    dashboard._install_update()

        def failed(exc: BaseException) -> None:
            self.update_check_btn.configure(state="normal")
            self.update_status.configure(
                text=_("No se pudo comprobar: {why}", why=str(exc)), text_color=RISK_COLORS["medio"]
            )

        BackgroundTask(self, work, done, failed).start()
