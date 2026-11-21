"""Diagnóstico: por qué va lento el equipo, en lenguaje claro. Solo lee, nunca cambia nada."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.client_report import html_to_pdf, render_client_html
from core.constants import LOW_RAM_GIB
from core.defender import ScanResult, quick_scan
from core.diagnostics import DiagnosticReport, Finding, ProcessUsage, collect
from core.hardware import GIB, ram_purchase_advice
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
    SECONDARY_BUTTON,
    TEXT_MUTED,
    WRAP,
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


HEALTH_LABELS = {"healthy": "en buen estado", "warning": "con avisos", "unhealthy": "FALLANDO"}


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
        self.scan_btn = ctk.CTkButton(
            bar,
            text="Análisis rápido con Defender",
            width=220,
            **SECONDARY_BUTTON,
            command=self.defender_scan,
        )
        self.scan_btn.pack(side="right")
        self.report_btn = ctk.CTkButton(
            bar,
            text="Informe para el cliente",
            width=190,
            **SECONDARY_BUTTON,
            command=self.client_report,
        )
        self.report_btn.pack(side="right", padx=PAD_S)
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

    def client_report(self) -> None:
        if self.report is None:
            messagebox.showinfo("Informe", "Espera a que termine el análisis.", parent=self)
            return
        target = filedialog.asksaveasfilename(
            parent=self,
            title="Guardar informe para el cliente",
            defaultextension=".pdf",
            initialfile=f"Informe-equipo-{self.report.snapshot.taken[:10]}.pdf",
            filetypes=[("PDF", "*.pdf"), ("HTML", "*.html")],
        )
        if not target:
            return
        app = self.state.app
        report = self.report

        def work(_p: ProgressFn, _c: threading.Event) -> Path:
            html = render_client_html(report, app.store.list(), app.engine.catalog)
            out = Path(target)
            page = out.with_suffix(".html")
            page.write_text(html, encoding="utf-8")
            if out.suffix.lower() == ".pdf" and html_to_pdf(page, out, app.runner):
                page.unlink(missing_ok=True)
                return out
            return page

        def done(path: Path) -> None:
            note = "" if path.suffix == ".pdf" else " (en HTML: ábrelo e imprímelo a PDF)"
            messagebox.showinfo("Informe", f"Informe guardado{note}:\n{path}", parent=self)

        self.main.run_long(work, done, "Informe para el cliente")

    def defender_scan(self) -> None:
        if not messagebox.askyesno(
            "Análisis rápido con Windows Defender",
            "Windows Defender revisará las zonas donde suele esconderse el malware. Tarda entre 2 "
            "y 15 minutos y puedes seguir usando el equipo. ¿Empezar?",
            parent=self,
        ):
            return
        runner = self.state.app.runner
        self.scan_btn.configure(state="disabled", text="Analizando con Defender…")

        def work(_p: ProgressFn, _c: threading.Event) -> ScanResult:
            return quick_scan(runner)

        def done(result: ScanResult) -> None:
            self.scan_btn.configure(state="normal", text="Análisis rápido con Defender")
            show = messagebox.showwarning if result.threats else messagebox.showinfo
            show("Windows Defender", result.message, parent=self)

        def failed(exc: BaseException) -> None:
            self.scan_btn.configure(state="normal", text="Análisis rápido con Defender")
            messagebox.showerror("Windows Defender", str(exc), parent=self)

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

        self._section("Qué retrasa el arranque")
        self._boot_list(report)

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
                    wraplength=WRAP,
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
            card, text=finding.detail, font=FONT_BODY, wraplength=WRAP, justify="left"
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

    def _boot_list(self, report: DiagnosticReport) -> None:
        boot = report.boot
        if not boot.available:
            self._lines(["No se pudo leer el registro de diagnóstico de arranque de Windows."])
            return
        if not boot.culprits:
            period = f" en los últimos {boot.boots} arranques" if boot.boots else ""
            self._lines([f"Windows no ha registrado nada que retrase el arranque{period}."])
            return
        card = Card(self.body)
        card.pack(fill="x", pady=PAD_S)
        ctk.CTkLabel(
            card,
            text=f"Datos de Windows de los últimos {boot.boots} arranques (60 días).",
            font=FONT_SMALL,
            text_color=TEXT_MUTED,
        ).pack(anchor="w", padx=PAD, pady=(PAD, PAD_S))
        for culprit in boot.culprits:
            seen = f"{culprit.count} vez" if culprit.count == 1 else f"{culprit.count} veces"
            ctk.CTkLabel(
                card,
                text=f"{culprit.name} ({culprit.kind}) — unos {culprit.avg_ms / 1000:.1f} s "
                f"de retraso, {seen}",
                font=FONT_BODY,
                anchor="w",
            ).pack(anchor="w", padx=PAD)
            if culprit.advice:
                ctk.CTkLabel(
                    card, text=culprit.advice, font=FONT_SMALL, text_color=TEXT_MUTED
                ).pack(anchor="w", padx=PAD * 2)
        ctk.CTkFrame(card, height=PAD, fg_color="transparent").pack()

    def _lines(self, lines: list[str]) -> None:
        card = Card(self.body)
        card.pack(fill="x", pady=PAD_S)
        ctk.CTkLabel(
            card, text="\n".join(lines), font=FONT_BODY, justify="left", wraplength=WRAP
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
        details = hw.details
        for i, mod in enumerate(details.memory, start=1):
            kind = " ".join(p for p in (mod.type_name, mod.form_name) if p)
            speed = f" a {mod.speed} MHz" if mod.speed else ""
            maker = f" ({mod.maker} {mod.part})".rstrip() if mod.maker or mod.part else ""
            lines.append(f"  Módulo {i}: {human_bytes(mod.capacity)} {kind}{speed}{maker}")
        advice = ram_purchase_advice(
            details.memory, hw.slots, hw.max_capacity, report.ram_installed
        )
        if advice:
            label = "Ampliar" if report.ram_installed < LOW_RAM_GIB * GIB else "Si amplías"
            lines.append(f"  {label}: {advice}")
        for disk in details.disks:
            parts = [disk.media or "disco", human_bytes(disk.size)]
            if disk.health:
                parts.append(HEALTH_LABELS.get(disk.health.lower(), disk.health))
            if disk.wear is not None:
                parts.append(f"{disk.wear} % de vida usada")
            if disk.temp is not None:
                parts.append(f"{disk.temp} °C")
            if disk.hours is not None:
                parts.append(f"{disk.hours} h encendido")
            lines.append(f"Disco {disk.name}: " + ", ".join(parts))
        if details.battery and details.battery.percent:
            cycles = f", {details.battery.cycles} ciclos" if details.battery.cycles else ""
            lines.append(f"Batería: {details.battery.percent} % de su capacidad original{cycles}")
        if details.cpu_perf:
            lines.append(
                f"Procesador ahora: {details.cpu_perf.utility} % de uso, "
                f"{details.cpu_perf.performance} % de su velocidad normal"
            )
        for gpu in details.gpus:
            when = f" del {gpu.date}" if gpu.date else ""
            lines.append(f"Gráfica: {gpu.name} (driver {gpu.version}{when})")
        if not details.devices:
            lines.append("Dispositivos: todos funcionan correctamente")
        return lines
