"""Historial de sesiones, Deshacer y Restaurar sistema."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.constants import BACKUP_DIR
from core.report import render_session_html
from core.restore import RestoreManager
from core.session import Session
from ui.dialogs import SummaryDialog
from ui.pages.base import Page, open_path, show_error
from ui.theme import FONT_BODY, FONT_SMALL, PAD, PAD_S, SECONDARY_BUTTON, STATUS_LABELS, TEXT_MUTED
from ui.widgets import Card
from ui.worker import ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow


class HistoryPage(Page):
    title = "Historial y deshacer"
    subtitle = (
        "Cada sesión guarda el estado previo de lo que cambió. 'Deshacer' lo restaura en orden "
        "inverso. Para volver atrás todo el sistema, usa 'Restaurar sistema'."
    )

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD, pady=PAD_S)
        ctk.CTkButton(bar, text="Restaurar sistema…", command=self._system_restore).pack(
            side="left"
        )
        ctk.CTkButton(
            bar,
            text="Carpeta de copias .reg",
            **SECONDARY_BUTTON,
            command=lambda: open_path(BACKUP_DIR),
        ).pack(side="left", padx=PAD_S)
        ctk.CTkButton(
            bar,
            text="Actualizar",
            **SECONDARY_BUTTON,
            width=100,
            command=self.refresh,
        ).pack(side="left")
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        sessions = self.state.app.store.list()
        if not sessions:
            ctk.CTkLabel(self.body, text="Todavía no hay sesiones.", font=FONT_BODY).pack(
                anchor="w"
            )
        by_id = {s.id: s for s in sessions}
        for session in sessions:
            self._render(session, by_id.get(session.reverted_by or ""))

    def _render(self, session: Session, revert: Session | None = None) -> None:
        card = Card(self.body)
        card.pack(fill="x", pady=3)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=PAD, pady=PAD_S)
        kind = "Aplicación" if session.kind == "apply" else f"Reversión de {session.parent_id}"
        ctk.CTkLabel(
            top, text=f"{session.created.replace('T', ' ')} · {kind}", font=FONT_BODY
        ).pack(side="left")
        summary = " · ".join(f"{STATUS_LABELS[k]} {v}" for k, v in session.summary().items() if v)
        ctk.CTkLabel(
            card, text=summary or "Sin cambios", font=FONT_SMALL, text_color=TEXT_MUTED
        ).pack(anchor="w", padx=PAD, pady=(0, PAD_S))
        ctk.CTkButton(
            top,
            text="Detalle",
            width=80,
            **SECONDARY_BUTTON,
            command=lambda s=session: SummaryDialog(
                self, s, self.state.app.engine.catalog, title=f"Sesión {s.id}"
            ),
        ).pack(side="right", padx=(PAD_S, 0))
        ctk.CTkButton(
            top,
            text="Informe",
            width=80,
            **SECONDARY_BUTTON,
            command=lambda s=session: self._export_report(s),
        ).pack(side="right", padx=(PAD_S, 0))
        if session.kind == "apply":
            failed = revert is not None and any(
                r.status in ("failed", "partial") for r in revert.results.values()
            )
            if session.reverted_by and failed:
                # Reintentar es seguro: restaurar un snapshot ya restaurado no cambia nada.
                ctk.CTkButton(
                    top,
                    text="Reintentar deshacer",
                    width=150,
                    command=lambda s=session: self._undo(s),
                ).pack(side="right")
            elif session.reverted_by:
                ctk.CTkLabel(
                    top,
                    text=f"Revertida ({session.reverted_by})",
                    font=FONT_SMALL,
                    text_color=TEXT_MUTED,
                ).pack(side="right")
            elif any(r.status in ("applied", "partial") for r in session.results.values()):
                ctk.CTkButton(
                    top, text="Deshacer", width=90, command=lambda s=session: self._undo(s)
                ).pack(side="right")

    def _export_report(self, session: Session) -> None:
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar informe",
            defaultextension=".html",
            initialfile=f"SafeTrim-{session.id}.html",
            filetypes=[("Informe HTML", "*.html")],
        )
        if not target:
            return
        app = self.state.app
        try:
            Path(target).write_text(
                render_session_html(session, app.engine.catalog, app.metrics), encoding="utf-8"
            )
        except OSError as exc:
            show_error("Guardar informe", exc, self)
            return
        messagebox.showinfo("Informe", f"Informe guardado en:\n{target}", parent=self)

    def _undo(self, session: Session) -> None:
        engine = self.state.app.engine

        def preview_work(_p: ProgressFn, _c: threading.Event) -> Session:
            return engine.revert(session.id, dry_run=True)

        self.main.run_long(
            preview_work,
            lambda preview: self._confirm_undo(session, preview),
            error_title="No se puede deshacer",
        )

    def _confirm_undo(self, session: Session, preview: Session) -> None:
        engine = self.state.app.engine
        lines = []
        for tid, result in preview.results.items():
            name = engine.catalog.get(tid).name if tid in engine.catalog else tid
            detail = "; ".join(result.details[:3]) or result.message
            lines.append(f"• {name}: {detail}")
        if self.state.app.settings.dry_run:
            messagebox.showinfo("Simulación de deshacer", "\n".join(lines[:40]), parent=self)
            return
        text = "\n".join(lines[:25]) + ("\n…" if len(lines) > 25 else "")
        if not messagebox.askyesno(
            "Deshacer sesión", f"Se revertirá:\n\n{text}\n\n¿Continuar?", parent=self
        ):
            return

        def work(progress: ProgressFn, cancel: threading.Event) -> Session:
            return engine.revert(session.id, progress=progress, cancel=cancel)

        def done(result: Session) -> None:
            SummaryDialog(self, result, engine.catalog, title="Reversión")
            self.refresh()
            self.main.invalidate_detections()

        self.main.run_long(work, on_done=done, error_title="Error al deshacer")

    def _system_restore(self) -> None:
        if not messagebox.askyesno(
            "Restaurar sistema",
            "Se abrirá el asistente de Restaurar sistema de Windows. Restaurar a un punto "
            "anterior reinicia el equipo. ¿Abrir?",
            parent=self,
        ):
            return
        try:
            RestoreManager.open_system_restore()
        except OSError as exc:
            show_error("Restaurar sistema", exc, self)
