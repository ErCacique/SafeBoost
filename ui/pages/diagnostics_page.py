"""Diagnóstico: por qué va lento el equipo, en lenguaje claro. Solo lee, nunca cambia nada."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.diagnostics import DiagnosticReport, Finding, ProcessUsage, collect
from core.metrics import human_bytes
from ui.pages.base import Page
from ui.theme import (
    ACCENT,
    DANGER,
    FONT_BODY,
    FONT_H2,
    FONT_SMALL,
    PAD,
    PAD_S,
    RISK_COLORS,
    TEXT_MUTED,
)
from ui.widgets import Card
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow

LEVEL_STYLE: dict[str, tuple[str, tuple[str, str]]] = {
    "critical": ("Importante", DANGER),
    "warning": ("Atención", RISK_COLORS["medio"]),
    "info": ("Información", ACCENT),
    "ok": ("Bien", RISK_COLORS["bajo"]),
}
REQ_MARK: dict[bool | None, tuple[str, tuple[str, str]]] = {
    True: ("✔", RISK_COLORS["bajo"]),
    False: ("✘", DANGER),
    None: ("?", TEXT_MUTED),
}


class DiagnosticsPage(Page):
    title = "Diagnóstico"
    subtitle = (
        "Por qué va lento el equipo: procesos, memoria, procesador, disco, actualizaciones y "
        "Windows 11. Solo mide; no cambia nada."
    )

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.report: DiagnosticReport | None = None
        self._running = False
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD, pady=(PAD, 0))
        self.run_btn = ctk.CTkButton(bar, text="Analizar ahora", width=150, command=self.analyze)
        self.run_btn.pack(side="left")
        self.status = ctk.CTkLabel(
            bar,
            text="Mide el uso durante un par de segundos. Hazlo cuando notes el equipo lento.",
            font=FONT_SMALL,
            text_color=TEXT_MUTED,
        )
        self.status.pack(side="left", padx=PAD)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)

    def on_show(self) -> None:
        if self.report is None and not self._running:
            self.analyze()

    # ------------------------------------------------------------------ análisis

    def analyze(self) -> None:
        app = self.state.app
        self._running = True
        self.run_btn.configure(state="disabled")
        self.status.configure(text="Analizando…")

        def work(_p: ProgressFn, _c: threading.Event) -> DiagnosticReport:
            return collect(app.env, app.registry, app.runner)

        def done(report: DiagnosticReport) -> None:
            self._running = False
            self.report = report
            self.run_btn.configure(state="normal")
            self.status.configure(text=f"Análisis de las {report.snapshot.taken[11:16]}.")
            self.render(report)

        def failed(exc: BaseException) -> None:
            self._running = False
            self.run_btn.configure(state="normal")
            self.status.configure(text=f"No se pudo analizar: {exc}", text_color=DANGER)

        BackgroundTask(self, work, done, failed).start()

    # ------------------------------------------------------------------ presentación

    def render(self, report: DiagnosticReport) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self._section("Veredicto")
        for finding in report.findings:
            self._finding(finding)

        self._section("Lo que más consume ahora")
        columns = ctk.CTkFrame(self.body, fg_color="transparent")
        columns.pack(fill="x")
        columns.grid_columnconfigure((0, 1), weight=1)
        self._process_list(columns, 0, "Procesador", report.top_cpu, memory=False)
        self._process_list(columns, 1, "Memoria", report.top_memory, memory=True)

        self._section("Equipo")
        self._lines(self._hardware_lines(report))

        self._section("Windows Update")
        updates = report.updates
        days = updates.last_update_days
        self._lines(
            [
                "Reinicio pendiente: "
                + ("SÍ, reinicia el equipo" if updates.reboot_pending else "no"),
                "Última actualización instalada: "
                + ("desconocida" if days is None else f"hace {days} días"),
            ]
        )

        if report.env.os_major == "10":
            self._section("¿Puede pasar a Windows 11?")
            card = Card(self.body)
            card.pack(fill="x", pady=PAD_S)
            for req in report.win11:
                mark, color = REQ_MARK[req.ok]
                row = ctk.CTkFrame(card, fg_color="transparent")
                row.pack(fill="x", padx=PAD, pady=2)
                ctk.CTkLabel(row, text=mark, font=FONT_H2, text_color=color, width=24).pack(
                    side="left"
                )
                ctk.CTkLabel(
                    row,
                    text=f"{req.name}: {req.detail}",
                    font=FONT_BODY,
                    wraplength=850,
                    justify="left",
                ).pack(side="left", padx=PAD_S)

    def _section(self, title: str) -> None:
        ctk.CTkLabel(self.body, text=title, font=FONT_H2).pack(anchor="w", pady=(PAD, PAD_S))

    def _finding(self, finding: Finding) -> None:
        label, color = LEVEL_STYLE[finding.level]
        card = Card(self.body)
        card.pack(fill="x", pady=PAD_S)
        ctk.CTkLabel(card, text=f"{label} · {finding.title}", font=FONT_H2, text_color=color).pack(
            anchor="w", padx=PAD, pady=(PAD, 0)
        )
        ctk.CTkLabel(
            card, text=finding.detail, font=FONT_BODY, wraplength=900, justify="left"
        ).pack(anchor="w", padx=PAD, pady=(PAD_S, PAD))

    def _process_list(
        self, parent: Any, column: int, title: str, procs: list[ProcessUsage], memory: bool
    ) -> None:
        card = Card(parent)
        card.grid(row=0, column=column, sticky="nsew", padx=PAD_S)
        ctk.CTkLabel(card, text=title, font=FONT_SMALL, text_color=TEXT_MUTED).pack(
            anchor="w", padx=PAD, pady=(PAD, PAD_S)
        )
        if not procs:
            ctk.CTkLabel(card, text="Sin datos", font=FONT_BODY).pack(anchor="w", padx=PAD)
        for proc in procs:
            many = f" ×{proc.count}" if proc.count > 1 else ""
            value = human_bytes(proc.memory) if memory else f"{proc.cpu_percent:.0f} %"
            ctk.CTkLabel(
                card, text=f"{proc.name}{many} — {value}", font=FONT_BODY, anchor="w"
            ).pack(anchor="w", padx=PAD)
            if proc.hint:
                ctk.CTkLabel(
                    card,
                    text=proc.hint,
                    font=FONT_SMALL,
                    text_color=TEXT_MUTED,
                    wraplength=420,
                    justify="left",
                ).pack(anchor="w", padx=PAD * 2)
        ctk.CTkFrame(card, height=PAD, fg_color="transparent").pack()

    def _lines(self, lines: list[str]) -> None:
        card = Card(self.body)
        card.pack(fill="x", pady=PAD_S)
        ctk.CTkLabel(
            card, text="\n".join(lines), font=FONT_BODY, justify="left", wraplength=900
        ).pack(anchor="w", padx=PAD, pady=PAD)

    @staticmethod
    def _hardware_lines(report: DiagnosticReport) -> list[str]:
        hw = report.hardware
        snap = report.snapshot
        disk = {"ssd": "SSD", "hdd": "disco duro (HDD)"}.get(report.env.disk_type, "desconocido")
        lines = []
        if hw and hw.cpu_name:
            speed = f" a {hw.mhz / 1000:.1f} GHz" if hw.mhz else ""
            lines.append(
                f"Procesador: {hw.cpu_name} ({hw.cores} núcleos, {hw.threads} hilos{speed})"
            )
        ram = (
            f"Memoria: {human_bytes(report.ram_installed)} instalada, "
            f"{snap.ram_percent:.0f} % en uso"
        )
        if hw and hw.slots and hw.modules:
            ram += f" · ranuras usadas: {len(hw.modules)} de {hw.slots}"
        if hw and hw.max_capacity:
            ram += f" · máximo admitido: {human_bytes(hw.max_capacity)}"
        lines.append(ram)
        lines.append(
            f"Disco del sistema: {disk}, {human_bytes(snap.disk_free)} libres de "
            f"{human_bytes(snap.disk_total)}"
        )
        if hw is None:
            lines.append("No se pudieron leer los detalles del hardware.")
        return lines
