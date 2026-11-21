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
                "SafeTrim medirá el nuevo tiempo de arranque.",
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


# Texto de cada paso: (título, párrafos). Se mantiene aquí para poder probarlo sin Tk.
WELCOME_STEPS: list[tuple[str, list[str]]] = [
    (
        "Bienvenido a SafeTrim",
        [
            "SafeTrim quita apps preinstaladas, reduce la telemetría y ajusta servicios para "
            "que Windows vaya más ligero.",
            "Empieza en MODO SIMULACIÓN: puedes pulsar “Simular” todas las veces que "
            "quieras para ver qué cambiaría, sin tocar nada.",
            "Si el equipo va lento y no sabes por qué, empieza por la página Diagnóstico.",
        ],
    ),
    (
        "Tu red de seguridad",
        [
            "Antes de cambiar nada, SafeTrim crea un punto de restauración de Windows y copias "
            ".reg de cada clave que toca. Si la Protección del sistema está apagada, se para y "
            "te ofrece activarla en Ajustes.",
            "Todo se puede deshacer desde “Historial / Deshacer”, salvo las limpiezas "
            "de archivos, que te pide confirmar aparte.",
            "Nunca toca Windows Defender, Windows Update, la Microsoft Store, la red ni los "
            "drivers.",
        ],
    ),
    (
        "Cómo aplicar los cambios",
        [
            "1. En el Dashboard, elige un perfil. Empieza por el recomendado o por el 1.",
            "2. Pulsa “Simular” y lee la lista de cambios.",
            "3. Pasa a modo real: aquí abajo o en Ajustes → Modo simulación.",
            "4. Pulsa “Revisar y aplicar”, confirma y reinicia el equipo.",
        ],
    ),
]


class WelcomeWizard(_Modal):
    """Guía de primer arranque en tres pasos. Al terminar marca first_run=False."""

    def __init__(
        self,
        master: Any,
        can_go_real: bool,
        why_not: str,
        on_done: Callable[[bool], None],
    ) -> None:
        super().__init__(master, "Primeros pasos", "640x460")
        self.on_done = on_done
        self.step = 0
        self.go_real = ctk.BooleanVar(value=False)
        self.protocol("WM_DELETE_WINDOW", self._finish)

        self.counter = ctk.CTkLabel(self, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.counter.pack(anchor="w", padx=PAD * 2, pady=(PAD * 2, 0))
        self.heading = ctk.CTkLabel(self, text="", font=FONT_H2)
        self.heading.pack(anchor="w", padx=PAD * 2, pady=(0, PAD))
        self.body = Card(self)
        self.body.pack(fill="both", expand=True, padx=PAD * 2)

        self.real_switch = ctk.CTkSwitch(
            self,
            text="Pasar a modo real ahora (podrás volver a simulación en Ajustes)",
            variable=self.go_real,
            font=FONT_BODY,
        )
        self.real_note = ctk.CTkLabel(
            self, text=why_not, font=FONT_SMALL, text_color=RISK_COLORS["medio"], wraplength=560
        )
        if not can_go_real:
            self.real_switch.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", side="bottom", padx=PAD * 2, pady=PAD * 2)
        self.next_btn = ctk.CTkButton(footer, text="Siguiente", width=120, command=self._next)
        self.next_btn.pack(side="right")
        self.back_btn = ctk.CTkButton(
            footer, text="Atrás", width=100, **SECONDARY_BUTTON, command=self._back
        )
        self.back_btn.pack(side="right", padx=PAD_S)
        ctk.CTkButton(
            footer, text="Saltar", width=90, **SECONDARY_BUTTON, command=self._finish
        ).pack(side="left")
        self._render()

    def _render(self) -> None:
        title, paragraphs = WELCOME_STEPS[self.step]
        last = self.step == len(WELCOME_STEPS) - 1
        self.counter.configure(text=f"Paso {self.step + 1} de {len(WELCOME_STEPS)}")
        self.heading.configure(text=title)
        for child in self.body.winfo_children():
            child.destroy()
        for text in paragraphs:
            ctk.CTkLabel(self.body, text=text, font=FONT_BODY, wraplength=540, justify="left").pack(
                anchor="w", padx=PAD, pady=PAD_S
            )
        self.back_btn.configure(state="normal" if self.step else "disabled")
        self.next_btn.configure(text="Empezar" if last else "Siguiente")
        if last:
            self.real_switch.pack(anchor="w", padx=PAD * 2, pady=(PAD, 0))
            if self.real_note.cget("text"):
                self.real_note.pack(anchor="w", padx=PAD * 2)
        else:
            self.real_switch.pack_forget()
            self.real_note.pack_forget()

    def _next(self) -> None:
        if self.step == len(WELCOME_STEPS) - 1:
            self._finish()
            return
        self.step += 1
        self._render()

    def _back(self) -> None:
        if self.step:
            self.step -= 1
            self._render()

    def _finish(self) -> None:
        go_real = bool(self.go_real.get()) and self.real_switch.cget("state") != "disabled"
        self.destroy()
        self.on_done(go_real)
