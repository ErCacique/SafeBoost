"""Dashboard: entorno, métricas en vivo, recomendación, selector de perfil y antes/después."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.catalog import LEVEL_LABELS
from core.engine import DriftItem
from core.metrics import (
    GIB,
    BootInfo,
    Snapshot,
    compare,
    human_bytes,
    last_boot,
    local_time,
    recommend_profile,
    take_snapshot,
)
from core.selection import Selection, SelectionError, load_selection
from ui.pages.base import Page, show_error
from ui.theme import (
    ACCENT,
    FONT_BODY,
    FONT_H2,
    FONT_SMALL,
    METRICS_REFRESH_MS,
    PAD,
    PAD_S,
    RISK_COLORS,
    SECONDARY_BUTTON,
    TEXT_MUTED,
)
from ui.widgets import Card, MetricCard
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow

PROFILE_INFO: dict[int, tuple[str, str]] = {
    1: (
        "Elimina apps preinstaladas, telemetría, ID de publicidad, sugerencias y tareas de "
        "telemetría. Todo reversible.",
        "bajo",
    ),
    2: (
        "Nivel 1 + servicios innecesarios a Manual, efectos visuales de rendimiento, limpieza "
        "(irreversible, confirmación aparte) y plan de energía.",
        "medio",
    ),
    3: (
        "Niveles 1 y 2 + red, prioridad de CPU, Game DVR, HAGS, servicios en segundo plano y "
        "memoria virtual. Algunos cambios requieren reiniciar.",
        "medio",
    ),
}


class DashboardPage(Page):
    title = "Dashboard"
    subtitle = "Estado del equipo, recomendación y selección de perfil."

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.boot: BootInfo | None = None
        self.snapshot: Snapshot | None = None
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._build_env(body)
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x", pady=PAD_S)
        self.cards = {
            key: MetricCard(grid, title)
            for key, title in (
                ("ram", "RAM en uso"),
                ("cpu", "CPU"),
                ("disk", "Disco del sistema"),
                ("proc", "Procesos"),
                ("boot", "Último arranque"),
            )
        }
        for col, card in enumerate(self.cards.values()):
            card.grid(row=0, column=col, sticky="nsew", padx=PAD_S)
            grid.grid_columnconfigure(col, weight=1)

        self.recommendation = ctk.CTkLabel(
            body, text="", font=FONT_BODY, wraplength=950, justify="left", text_color=ACCENT
        )
        self.recommendation.pack(anchor="w", pady=PAD_S)
        self._build_drift(body)
        self._build_profiles(body)
        self._build_compare(body)
        self._load_boot()
        self._refresh_metrics()
        self.check_drift()

    # ------------------------------------------------------------------ secciones

    def _build_env(self, parent: Any) -> None:
        env = self.state.app.env
        card = Card(parent)
        card.pack(fill="x")
        disk = {"ssd": "SSD", "hdd": "HDD"}.get(env.disk_type, "desconocido")
        chassis = {"desktop": "Sobremesa", "laptop": "Portátil"}.get(env.chassis, "desconocido")
        lines = [
            f"{env.os_label} · Edición {env.edition.capitalize()} ({env.edition_id or '?'})",
            f"Disco del sistema: {disk} · {chassis} · Usuario: {env.interactive_user or '?'}",
        ]
        ctk.CTkLabel(card, text="\n".join(lines), font=FONT_BODY, justify="left").pack(
            anchor="w", padx=PAD, pady=PAD
        )
        alerts = list(env.warnings)
        if env.managed:
            alerts.insert(
                0,
                "Equipo gestionado (dominio/Entra ID/MDM): las directivas están desactivadas "
                "para no entrar en conflicto con la política de la organización.",
            )
        if not env.is_admin:
            alerts.insert(0, "Sin privilegios de administrador: solo se puede simular.")
        for alert in alerts:
            ctk.CTkLabel(
                card,
                text=f"⚠ {alert}",
                font=FONT_SMALL,
                wraplength=950,
                justify="left",
                text_color=RISK_COLORS["medio"],
            ).pack(anchor="w", padx=PAD, pady=(0, PAD_S))

    def _build_profiles(self, parent: Any) -> None:
        ctk.CTkLabel(parent, text="Perfil", font=FONT_H2).pack(anchor="w", pady=(PAD, PAD_S))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        self.profile_var = ctk.IntVar(value=self.state.profile or 0)
        for col, level in enumerate((1, 2, 3)):
            text, risk = PROFILE_INFO[level]
            card = Card(row)
            card.grid(row=0, column=col, sticky="nsew", padx=PAD_S)
            row.grid_columnconfigure(col, weight=1)
            ctk.CTkRadioButton(
                card,
                text=f"{level} · {LEVEL_LABELS[level]}",
                variable=self.profile_var,
                value=level,
                font=FONT_H2,
                command=self._choose_profile,
            ).pack(anchor="w", padx=PAD, pady=(PAD, PAD_S))
            ctk.CTkLabel(card, text=text, font=FONT_SMALL, wraplength=280, justify="left").pack(
                anchor="w", padx=PAD
            )
            ctk.CTkLabel(
                card, text=f"Riesgo {risk}", font=FONT_SMALL, text_color=RISK_COLORS[risk]
            ).pack(anchor="w", padx=PAD, pady=(0, PAD))
        self.profile_summary = ctk.CTkLabel(parent, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.profile_summary.pack(anchor="w", pady=PAD_S)
        actions = ctk.CTkFrame(parent, fg_color="transparent")
        actions.pack(anchor="w")
        ctk.CTkButton(
            actions,
            text="Exportar selección…",
            width=160,
            command=self._export_selection,
            **SECONDARY_BUTTON,
        ).pack(side="left")
        ctk.CTkButton(
            actions,
            text="Importar selección…",
            width=160,
            command=self._import_selection,
            **SECONDARY_BUTTON,
        ).pack(side="left", padx=PAD_S)
        self.state.subscribe(self._update_summary)

    def _build_drift(self, parent: Any) -> None:
        """Tarjeta de deriva: solo visible si Windows ha deshecho algo de lo aplicado."""
        self.drift_items: list[DriftItem] = []
        self.drift_card = Card(parent)
        self.drift_label = ctk.CTkLabel(
            self.drift_card,
            text="",
            font=FONT_BODY,
            justify="left",
            wraplength=900,
            text_color=RISK_COLORS["medio"],
        )
        self.drift_label.pack(anchor="w", padx=PAD, pady=(PAD, PAD_S))
        ctk.CTkButton(
            self.drift_card, text="Revisar y reaplicar", width=170, command=self._reapply_drift
        ).pack(anchor="w", padx=PAD, pady=(0, PAD))
        self._drift_anchor = self.recommendation

    def check_drift(self) -> None:
        engine = self.state.app.engine

        def work(_p: ProgressFn, _c: threading.Event) -> list[DriftItem]:
            return engine.drift()

        def done(items: list[DriftItem]) -> None:
            self.drift_items = items
            if not items:
                self.drift_card.pack_forget()
                return
            names = [engine.catalog.get(i.tweak_id).name for i in items]
            shown = "\n".join(f"• {n}" for n in names[:8])
            more = f"\n… y {len(names) - 8} más" if len(names) > 8 else ""
            self.drift_label.configure(
                text=f"Windows ha deshecho {len(items)} cambio(s) que aplicaste "
                f"(suele ocurrir tras una actualización):\n{shown}{more}"
            )
            self.drift_card.pack(fill="x", pady=PAD_S, after=self._drift_anchor)

        BackgroundTask(self, work, done, lambda _e: None).start()

    def _reapply_drift(self) -> None:
        self.state.selected = {i.tweak_id for i in self.drift_items}
        self.state.notify()
        self.main.review()

    # ------------------------------------------------------------------ selección

    def _export_selection(self) -> None:
        if not self.state.selected:
            messagebox.showinfo("Exportar selección", "No hay nada seleccionado.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Exportar selección",
            defaultextension=".json",
            initialfile="wintune-seleccion.json",
            filetypes=[("Selección WinTune", "*.json")],
        )
        if not target:
            return
        selection = Selection(
            tweaks=self.state.ordered_selection(),
            params={k: v for k, v in self.state.params.items() if k in self.state.selected},
            profile=self.state.profile,
        )
        try:
            selection.save(Path(target))
        except OSError as exc:
            show_error("Exportar selección", exc, self)
            return
        messagebox.showinfo(
            "Exportar selección", f"{len(selection.tweaks)} cambios exportados.", parent=self
        )

    def _import_selection(self) -> None:
        source = filedialog.askopenfilename(
            parent=self, title="Importar selección", filetypes=[("Selección WinTune", "*.json")]
        )
        if not source:
            return
        try:
            selection, warnings = load_selection(Path(source), self.state.app.engine.catalog)
        except SelectionError as exc:
            show_error("Importar selección", exc, self)
            return
        self.state.selected = set(selection.tweaks)
        self.state.params = {k: dict(v) for k, v in selection.params.items()}
        self.state.profile = selection.profile
        self.profile_var.set(selection.profile or 0)
        self.state.notify()
        text = f"{len(selection.tweaks)} cambios importados."
        if warnings:
            text += "\n\nAvisos:\n" + "\n".join(warnings[:10])
        messagebox.showinfo("Importar selección", text, parent=self)

    def _build_compare(self, parent: Any) -> None:
        ctk.CTkLabel(parent, text="Antes / después", font=FONT_H2).pack(
            anchor="w", pady=(PAD, PAD_S)
        )
        self.compare_card = Card(parent)
        self.compare_card.pack(fill="x")
        self.compare_label = ctk.CTkLabel(
            self.compare_card, text="", font=FONT_BODY, justify="left"
        )
        self.compare_label.pack(anchor="w", padx=PAD, pady=PAD)
        self.update_compare()

    # ------------------------------------------------------------------ comportamiento

    def _choose_profile(self) -> None:
        self.state.apply_profile(self.profile_var.get())

    def _update_summary(self) -> None:
        count = len(self.state.selected)
        level = self.state.profile
        prefix = f"Perfil {LEVEL_LABELS[level]}: " if level else ""
        self.profile_summary.configure(
            text=f"{prefix}{count} cambios seleccionados. Ajusta la selección en cada sección."
        )

    def update_compare(self) -> None:
        metrics = self.state.app.metrics
        sessions = [s for s in self.state.app.store.list() if s.kind == "apply"]
        for session in sessions:
            before = metrics.get(session.id, "before")
            after = metrics.get(session.id, "after")
            if not (before and after):
                continue
            cmp = compare(before, after)
            lines = [
                f"Sesión {session.id}",
                f"RAM libre: {human_bytes(before.ram_available)} → "
                f"{human_bytes(after.ram_available)} ({human_bytes(cmp.ram_freed)})",
                f"Procesos: {before.process_count} → {after.process_count} "
                f"({cmp.process_delta:+d})",
                f"Espacio liberado: {human_bytes(cmp.disk_freed)}",
            ]
            reboot = metrics.get(session.id, "after_reboot")
            if reboot and reboot.boot and before.boot:
                delta = reboot.boot.boot_ms - before.boot.boot_ms
                lines.append(
                    f"Arranque: {before.boot.boot_ms / 1000:.1f} s → "
                    f"{reboot.boot.boot_ms / 1000:.1f} s ({delta / 1000:+.1f} s)"
                )
                lines.append(f"Procesos tras reiniciar: {reboot.process_count}")
            else:
                lines.append("Arranque: reinicia el equipo para medir el después.")
            self.compare_label.configure(text="\n".join(lines))
            return
        self.compare_label.configure(text="Aún no hay sesiones aplicadas.")

    def _load_boot(self) -> None:
        app = self.state.app

        def work(_p: ProgressFn, _c: threading.Event) -> BootInfo | None:
            app.metrics.capture_post_reboot(app.runner, app.env.system_drive)
            return last_boot(app.runner)

        def done(boot: BootInfo | None) -> None:
            self.boot = boot
            if boot:
                self.cards["boot"].set(f"{boot.boot_ms / 1000:.1f} s", local_time(boot.timestamp))
            else:
                self.cards["boot"].set("n/d", "Sin datos de diagnóstico")
            self.update_compare()

        BackgroundTask(self, work, done, lambda _e: self.cards["boot"].set("n/d")).start()

    def _refresh_metrics(self) -> None:
        try:
            snap = take_snapshot(self.state.app.env.system_drive, cpu_interval=0)
        except OSError:
            snap = None
        if snap:
            self.snapshot = snap
            self.cards["ram"].set(
                f"{snap.ram_percent:.0f} %",
                f"{human_bytes(snap.ram_used)} de {snap.ram_total / GIB:.0f} GB",
            )
            self.cards["cpu"].set(f"{snap.cpu_percent:.0f} %")
            used = snap.disk_total - snap.disk_free
            self.cards["disk"].set(
                f"{used / snap.disk_total * 100:.0f} %", f"{human_bytes(snap.disk_free)} libres"
            )
            self.cards["proc"].set(str(snap.process_count))
            level, why = recommend_profile(self.state.app.env, snap)
            self.recommendation.configure(
                text=f"Recomendación: perfil {level} · {LEVEL_LABELS[level]}. {why}"
            )
        self.after(METRICS_REFRESH_MS, self._refresh_metrics)
