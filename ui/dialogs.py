"""Diálogos: revisión previa (con confirmaciones), resumen de sesión y vista previa de deshacer."""

from __future__ import annotations

from collections.abc import Callable
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from core.catalog import Catalog
from core.engine import PlanItem
from core.metrics import Comparison, human_bytes
from core.session import Session
from ui.theme import (
    DANGER,
    FONT_BODY,
    FONT_H2,
    FONT_SMALL,
    PAD,
    PAD_S,
    RISK_COLORS,
    SECONDARY_BUTTON,
    STATUS_LABELS,
    TEXT_MUTED,
)
from ui.widgets import Card, risk_badge


class _Modal(ctk.CTkToplevel):
    def __init__(self, master: Any, title: str, size: str = "900x640") -> None:
        super().__init__(master)
        self.title(title)
        self.geometry(size)
        self.transient(master)
        # grab_set falla si la ventana aún no es visible; se difiere al primer ciclo.
        self.after(50, self._grab)

    def _grab(self) -> None:
        try:
            self.grab_set()
            self.focus_force()
        except Exception:  # noqa: BLE001 - TclError si la ventana se cerró antes
            return


class ReviewDialog(_Modal):
    """Pantalla de revisión previa. En modo simulación solo informa."""

    def __init__(
        self,
        master: Any,
        items: list[PlanItem],
        dry_run: bool,
        on_confirm: Callable[[list[str], set[str]], None],
    ) -> None:
        super().__init__(master, "Simulación" if dry_run else "Revisión de cambios")
        self.items = items
        self.dry_run = dry_run
        self.on_confirm = on_confirm
        self.to_apply = [i for i in items if i.applicability.applicable and not i.already_applied]
        actions = [i for i in self.to_apply if i.tweak.is_action]
        high = [i for i in self.to_apply if i.tweak.confirm_double]

        header = (
            "Modo simulación: esto es exactamente lo que cambiaría. No se ha modificado nada."
            if dry_run
            else "Revisa cada cambio. Antes de aplicar se crea un punto de restauración y "
            "copias .reg."
        )
        ctk.CTkLabel(self, text=header, font=FONT_BODY, wraplength=840, justify="left").pack(
            anchor="w", padx=PAD, pady=(PAD, PAD_S)
        )
        counts = (
            f"{len(self.to_apply)} con cambios · "
            f"{sum(1 for i in items if i.already_applied)} ya aplicados · "
            f"{sum(1 for i in items if not i.applicability.applicable)} no aplicables"
        )
        ctk.CTkLabel(self, text=counts, font=FONT_SMALL, text_color=TEXT_MUTED).pack(
            anchor="w", padx=PAD
        )

        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD_S)
        for item in items:
            self._render_item(body, item)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=PAD, pady=PAD)
        self.reviewed = ctk.BooleanVar(value=False)
        self.irreversible_ok = ctk.BooleanVar(value=not actions)
        self.high_vars: dict[str, ctk.BooleanVar] = {}

        if dry_run:
            ctk.CTkButton(footer, text="Cerrar", command=self.destroy).pack(side="right")
            return

        if actions:
            names = ", ".join(i.tweak.name.removeprefix("Limpiar: ") for i in actions)
            ctk.CTkCheckBox(
                footer,
                text=f"Confirmo las acciones IRREVERSIBLES ({names}): lo borrado no se recupera",
                variable=self.irreversible_ok,
                text_color=RISK_COLORS["alto"],
                command=self._refresh,
            ).pack(anchor="w", pady=2)
        for item in high:
            var = ctk.BooleanVar(value=False)
            self.high_vars[item.tweak.id] = var
            ctk.CTkCheckBox(
                footer,
                text=f"Entiendo el riesgo de seguridad de: {item.tweak.name}",
                variable=var,
                text_color=RISK_COLORS["alto"],
                command=self._refresh,
            ).pack(anchor="w", pady=2)
        ctk.CTkCheckBox(
            footer,
            text="He revisado la lista de cambios",
            variable=self.reviewed,
            command=self._refresh,
        ).pack(anchor="w", pady=2)

        buttons = ctk.CTkFrame(footer, fg_color="transparent")
        buttons.pack(fill="x", pady=(PAD_S, 0))
        ctk.CTkButton(buttons, text="Cancelar", **SECONDARY_BUTTON, command=self.destroy).pack(
            side="right", padx=(PAD_S, 0)
        )
        self.apply_btn = ctk.CTkButton(
            buttons,
            text=f"Aplicar {len(self.to_apply)} cambios",
            state="disabled",
            command=self._confirm,
        )
        self.apply_btn.pack(side="right")

    def _render_item(self, parent: Any, item: PlanItem) -> None:
        card = Card(parent)
        card.pack(fill="x", pady=3)
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=PAD, pady=(PAD_S, 0))
        ctk.CTkLabel(top, text=item.tweak.name, font=FONT_BODY).pack(side="left")
        risk_badge(top, item.tweak.risk).pack(side="left", padx=PAD_S)
        if not item.applicability.applicable:
            lines = ["No aplicable: " + "; ".join(item.applicability.reasons)]
        elif item.already_applied:
            lines = ["Ya aplicado: no hay nada que cambiar", *item.lines]
        else:
            lines = item.lines or ["(sin detalle)"]
        if item.error:
            lines.append(f"Aviso: {item.error}")
        ctk.CTkLabel(
            card,
            text="\n".join(f"• {line}" for line in lines),
            font=FONT_SMALL,
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=820,
            anchor="w",
        ).pack(anchor="w", padx=PAD * 2, pady=(0, PAD_S))

    def _refresh(self) -> None:
        ready = self.reviewed.get() and self.irreversible_ok.get() and bool(self.to_apply)
        self.apply_btn.configure(state="normal" if ready else "disabled")

    def _confirm(self) -> None:
        confirmed: set[str] = set()
        if self.irreversible_ok.get():
            confirmed |= {i.tweak.id for i in self.to_apply if i.tweak.is_action}
        for tid, var in self.high_vars.items():
            if not var.get():
                continue
            # Segunda confirmación, separada de la casilla: exigencia para riesgo alto.
            if messagebox.askyesno(
                "Advertencia de seguridad",
                "Vas a desactivar protecciones de seguridad del procesador.\n\n"
                "El equipo quedará expuesto a ataques de canal lateral (Spectre/Meltdown) que "
                "pueden leer memoria de otros procesos, incluido el navegador.\n\n"
                "¿Confirmas que este equipo está aislado o es de pruebas?",
                icon="warning",
                parent=self,
            ):
                confirmed.add(tid)
        ids = [i.tweak.id for i in self.to_apply]
        self.destroy()
        self.on_confirm(ids, confirmed)


class SummaryDialog(_Modal):
    def __init__(
        self,
        master: Any,
        session: Session,
        catalog: Catalog,
        comparison: Comparison | None = None,
        title: str = "Resumen",
    ) -> None:
        super().__init__(master, title, "860x600")
        summary = session.summary()
        parts = [f"{STATUS_LABELS[k]}: {v}" for k, v in summary.items() if v]
        ctk.CTkLabel(self, text=" · ".join(parts) or "Sin resultados", font=FONT_H2).pack(
            anchor="w", padx=PAD, pady=(PAD, 0)
        )
        if session.restore_point:
            ctk.CTkLabel(
                self, text=session.restore_point, font=FONT_SMALL, text_color=TEXT_MUTED
            ).pack(anchor="w", padx=PAD)
        if comparison:
            text = (
                f"RAM libre: {human_bytes(comparison.ram_freed)} · "
                f"Procesos: {comparison.process_delta:+d} · "
                f"Espacio liberado: {human_bytes(comparison.disk_freed)}"
            )
            ctk.CTkLabel(self, text=text, font=FONT_BODY).pack(anchor="w", padx=PAD, pady=PAD_S)
        reboot = [
            tid
            for tid, r in session.results.items()
            if r.status == "applied" and tid in catalog and catalog.get(tid).reboot_required
        ]
        if reboot:
            ctk.CTkLabel(
                self,
                text="Reinicia el equipo para completar algunos cambios. Tras reiniciar, "
                "WinTune medirá el nuevo tiempo de arranque.",
                font=FONT_BODY,
                text_color=RISK_COLORS["medio"],
                wraplength=800,
                justify="left",
            ).pack(anchor="w", padx=PAD)

        body = ctk.CTkScrollableFrame(self)
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD_S)
        order = {
            "failed": 0,
            "partial": 1,
            "irreversible": 2,
            "applied": 3,
            "reverted": 3,
            "skipped": 4,
        }
        for tid, result in sorted(session.results.items(), key=lambda kv: order[kv[1].status]):
            name = catalog.get(tid).name if tid in catalog else tid
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", pady=1)
            color = DANGER if result.status in ("failed", "partial") else TEXT_MUTED
            ctk.CTkLabel(
                row,
                text=STATUS_LABELS[result.status],
                width=100,
                anchor="w",
                font=FONT_SMALL,
                text_color=color,
            ).pack(side="left")
            ctk.CTkLabel(row, text=name, anchor="w", font=FONT_BODY).pack(side="left")
            ctk.CTkLabel(
                row,
                text=result.message,
                anchor="w",
                justify="left",
                font=FONT_SMALL,
                text_color=TEXT_MUTED,
                wraplength=380,
            ).pack(side="right")
        ctk.CTkButton(self, text="Cerrar", command=self.destroy).pack(
            side="right", padx=PAD, pady=PAD
        )
