"""Evolución: tiempo de arranque a lo largo del tiempo, qué ha cambiado en el equipo y la foto
del sistema antes y después de instalar un programa."""

from __future__ import annotations

import threading
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.metrics import local_time
from core.watch import (
    EventLog,
    HealthHistory,
    HealthRecord,
    SnapshotDiff,
    SnapshotStore,
    boot_trend,
    diff_snapshots,
    take_snapshot,
)
from ui.pages.base import Page
from ui.theme import (
    ACCENT,
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

CHART_POINTS = 30
CHART_HEIGHT = 180
EVENT_LABELS = {
    "startup_added": "Nuevo programa de inicio",
    "program_installed": "Programa instalado",
    "maintenance": "Mantenimiento",
}


def chart_points(
    records: list[HealthRecord], width: int, height: int, pad: int = 30
) -> list[tuple[float, float, HealthRecord]]:
    """Coordenadas (x, y) de cada arranque medido para dibujarlo. Función pura."""
    boots = [r for r in records if r.boot_ms][-CHART_POINTS:]
    if not boots:
        return []
    top = max(r.boot_ms or 0 for r in boots) * 1.1 or 1
    step = (width - 2 * pad) / max(len(boots) - 1, 1)
    return [
        (pad + i * step, height - pad - (r.boot_ms or 0) / top * (height - 2 * pad), r)
        for i, r in enumerate(boots)
    ]


class EvolutionPage(Page):
    title = "Evolución"
    subtitle = (
        "Cómo cambia el equipo con el tiempo: tiempo de arranque, programas que se añaden y qué "
        "instala cada programa."
    )

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

        self._title("Tiempo de arranque")
        chart_card = Card(self.body)
        chart_card.pack(fill="x", pady=PAD_S)
        dark = ctk.get_appearance_mode() == "Dark"
        self.chart = ctk.CTkCanvas(
            chart_card,
            height=CHART_HEIGHT,
            highlightthickness=0,
            bg="#20232a" if dark else "#f2f3f5",
        )
        self.chart.pack(fill="x", padx=PAD, pady=PAD)
        self.chart.bind("<Configure>", lambda _e: self.draw_chart())
        self.trend_label = ctk.CTkLabel(
            chart_card, text="", font=FONT_BODY, wraplength=WRAP, justify="left"
        )
        self.trend_label.pack(anchor="w", padx=PAD, pady=(0, PAD))

        self._title("Lo que ha cambiado")
        self.events_card = Card(self.body)
        self.events_card.pack(fill="x", pady=PAD_S)

        self._title("Qué instala un programa")
        snap_card = Card(self.body)
        snap_card.pack(fill="x", pady=PAD_S)
        ctk.CTkLabel(
            snap_card,
            text="1. Antes de instalar algo, toma una foto del sistema. 2. Instálalo. "
            "3. Compara: verás qué servicios, tareas programadas y programas de inicio ha añadido "
            "el instalador, también los que no avisa.",
            font=FONT_BODY,
            wraplength=WRAP,
            justify="left",
        ).pack(anchor="w", padx=PAD, pady=(PAD, PAD_S))
        row = ctk.CTkFrame(snap_card, fg_color="transparent")
        row.pack(anchor="w", padx=PAD, pady=(0, PAD_S))
        self.snap_btn = ctk.CTkButton(row, text="Tomar foto ahora", command=self.take_photo)
        self.snap_btn.pack(side="left")
        self.compare_btn = ctk.CTkButton(
            row, text="Comparar con la foto", **SECONDARY_BUTTON, command=self.compare
        )
        self.compare_btn.pack(side="left", padx=PAD_S)
        self.snap_status = ctk.CTkLabel(snap_card, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.snap_status.pack(anchor="w", padx=PAD)
        self.diff_label = ctk.CTkLabel(
            snap_card, text="", font=FONT_BODY, wraplength=WRAP, justify="left"
        )
        self.diff_label.pack(anchor="w", padx=PAD, pady=(PAD_S, PAD))
        self._refresh_snapshot_status()

    def on_show(self) -> None:
        self.draw_chart()
        self.render_events()

    def _title(self, text: str) -> None:
        ctk.CTkLabel(self.body, text=text, font=FONT_H2).pack(anchor="w", pady=(PAD, PAD_S))

    # ------------------------------------------------------------------ gráfica

    def draw_chart(self) -> None:
        records = HealthHistory().load()
        canvas = self.chart
        canvas.delete("all")
        width = max(canvas.winfo_width(), 300)
        height = CHART_HEIGHT
        points = chart_points(records, width, height)
        muted = "#9aa3b2"
        line = "#3b82f6"
        if len(points) < 2:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Aún no hay suficientes arranques medidos. SafeTrim guarda uno cada vez que "
                "lo abres tras reiniciar.",
                fill=muted,
                width=width - 40,
            )
        else:
            top = max(r.boot_ms or 0 for _x, _y, r in points)
            canvas.create_text(4, 12, text=f"{top / 1000:.0f} s", anchor="w", fill=muted)
            canvas.create_text(4, height - 30, text="0 s", anchor="w", fill=muted)
            canvas.create_line(
                *[c for x, y, _r in points for c in (x, y)], fill=line, width=2, smooth=True
            )
            for x, y, _r in points:
                canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=line, outline=line)
            first, last = points[0][2], points[-1][2]
            canvas.create_text(
                points[0][0], height - 10, text=first.when[:10], anchor="w", fill=muted
            )
            canvas.create_text(
                points[-1][0], height - 10, text=last.when[:10], anchor="e", fill=muted
            )
        trend = boot_trend(records, EventLog().all())
        boots = [r for r in records if r.boot_ms]
        if trend:
            causes = (
                " Coincide con: " + ", ".join(trend.causes[:5]) + "."
                if trend.causes
                else " No se registró ningún programa nuevo por esas fechas."
            )
            self.trend_label.configure(
                text=f"Desde el {trend.since} arranca unos {trend.delta_ms / 1000:.0f} s más "
                f"lento ({trend.before_ms / 1000:.0f} s → {trend.after_ms / 1000:.0f} s).{causes}",
                text_color=RISK_COLORS["medio"],
            )
        elif boots:
            self.trend_label.configure(
                text=f"Último arranque: {boots[-1].boot_ms / 1000:.1f} s. Sin empeoramiento "
                "apreciable.",
                text_color=ACCENT,
            )
        else:
            self.trend_label.configure(text="")

    # ------------------------------------------------------------------ eventos

    def render_events(self) -> None:
        for child in self.events_card.winfo_children():
            child.destroy()
        events = EventLog().all()[-15:][::-1]
        if not events:
            ctk.CTkLabel(
                self.events_card,
                text="Nada todavía. Aquí aparecerán los programas que se instalen o se añadan al "
                "inicio, y los mantenimientos.",
                font=FONT_BODY,
                wraplength=WRAP,
                justify="left",
            ).pack(anchor="w", padx=PAD, pady=PAD)
            return
        for event in events:
            label = EVENT_LABELS.get(event.get("kind", ""), event.get("kind", ""))
            ctk.CTkLabel(
                self.events_card,
                text=f"{local_time(event.get('when', ''))}  ·  {label}: {event.get('text', '')}",
                font=FONT_BODY,
                anchor="w",
            ).pack(anchor="w", padx=PAD, pady=1)
        ctk.CTkFrame(self.events_card, height=PAD_S, fg_color="transparent").pack()

    # ------------------------------------------------------------------ foto antes/después

    def _refresh_snapshot_status(self) -> None:
        snapshot = SnapshotStore().load()
        self.compare_btn.configure(state="normal" if snapshot else "disabled")
        self.snap_status.configure(
            text=f"Foto guardada: {local_time(snapshot['taken'])}"
            if snapshot
            else "Sin foto todavía."
        )

    def _snapshot_work(self) -> dict:
        from core.monitor import startup_items  # import diferido: carga los handlers de inicio

        app = self.state.app
        return take_snapshot(app.registry, app.runner, startup_items(app))

    def take_photo(self) -> None:
        self.snap_btn.configure(state="disabled", text="Tomando foto…")

        def work(_p: ProgressFn, _c: threading.Event) -> dict:
            return self._snapshot_work()

        def done(snapshot: dict) -> None:
            SnapshotStore().save(snapshot)
            self.snap_btn.configure(state="normal", text="Tomar foto ahora")
            self.diff_label.configure(text="")
            self._refresh_snapshot_status()

        def failed(exc: BaseException) -> None:
            self.snap_btn.configure(state="normal", text="Tomar foto ahora")
            messagebox.showerror("Foto del sistema", str(exc), parent=self)

        BackgroundTask(self, work, done, failed).start()

    def compare(self) -> None:
        before = SnapshotStore().load()
        if not before:
            return
        self.compare_btn.configure(state="disabled", text="Comparando…")

        def work(_p: ProgressFn, _c: threading.Event) -> SnapshotDiff:
            return diff_snapshots(before, self._snapshot_work())

        def done(diff: SnapshotDiff) -> None:
            self.compare_btn.configure(state="normal", text="Comparar con la foto")
            self.diff_label.configure(text=describe_diff(diff))

        def failed(exc: BaseException) -> None:
            self.compare_btn.configure(state="normal", text="Comparar con la foto")
            messagebox.showerror("Comparar", str(exc), parent=self)

        BackgroundTask(self, work, done, failed).start()


def describe_diff(diff: SnapshotDiff) -> str:
    if diff.empty:
        return "No ha cambiado nada desde la foto."
    parts = []
    for title, items in (
        ("Programas instalados", diff.programs_added),
        ("Programas desinstalados", diff.programs_removed),
        ("Programas de inicio nuevos (revísalos en Inicio)", diff.startup_added),
        ("Servicios nuevos", diff.services_added),
        ("Servicios con otro tipo de inicio", diff.services_changed),
        ("Tareas programadas nuevas", diff.tasks_added),
    ):
        if items:
            shown = "\n".join(f"  • {i}" for i in items[:12])
            more = f"\n  … y {len(items) - 12} más" if len(items) > 12 else ""
            parts.append(f"{title} ({len(items)}):\n{shown}{more}")
    return "\n\n".join(parts)
