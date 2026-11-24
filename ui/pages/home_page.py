"""Inicio del modo Fácil: cómo está el equipo en una nota de 0 a 100, qué le pasa en una frase y
un botón para arreglarlo. Todo lo demás (perfiles, selección de tweaks) está en el modo Avanzado.

No duplica lógica: el diagnóstico es core.diagnostics.collect, la nota core.health y los botones
reutilizan los del Panel avanzado (Arreglar mi PC, modo juego y modo ahorro).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.health import Health, from_report
from core.i18n import _
from core.metrics import human_bytes, last_boot
from core.update_check import ReleaseInfo
from ui.icons import icon
from ui.pages.base import Page, show_error
from ui.theme import (
    BG_CARD_HI,
    BORDER,
    FONT_BODY,
    FONT_H2,
    FONT_HERO,
    FONT_SMALL,
    PAD,
    PAD_S,
    PRIMARY_BUTTON,
    RADIUS,
    SECONDARY_BUTTON,
    TEXT_MUTED,
    WRAP,
)
from ui.widgets import Card, Chip, Gauge, ShortcutTile, StatusTile
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from core.diagnostics import DiagnosticReport
    from ui.app import MainWindow
    from ui.pages.dashboard import DashboardPage

GIB = 1024**3


@dataclass
class HomeData:
    report: DiagnosticReport
    boot_ms: int | None
    health: Health
    game_on: bool
    battery_on: bool


def boot_tile(boot_ms: int | None) -> tuple[str, str, str, str]:
    """(valor, explicación, tono, chip) de la tarjeta de arranque."""
    if not boot_ms:
        return "n/d", _("Sin datos del arranque todavía"), "neutral", "—"
    secs = boot_ms / 1000
    sub = _("Lo normal: menos de 40 s")
    if secs > 90:
        return f"{secs:.0f} s", sub, "critical", _("LENTO")
    if secs > 40:
        return f"{secs:.0f} s", sub, "warning", _("MEJORABLE")
    return f"{secs:.0f} s", sub, "ok", _("RÁPIDO")


def memory_tile(total: int, percent: float, used: int) -> tuple[str, str, str, str]:
    sub = _("{used} de {total} en uso", used=human_bytes(used), total=human_bytes(total))
    if percent >= 85:
        return f"{percent:.0f} %", sub, "critical", _("LLENA")
    if percent >= 75 or total < 5 * GIB:
        return f"{percent:.0f} %", sub, "warning", _("JUSTA")
    return f"{percent:.0f} %", sub, "ok", _("BIEN")


def disk_tile(free: int, total: int) -> tuple[str, str, str, str]:
    pct = free / total * 100 if total else 100
    sub = _("libres de {total}", total=human_bytes(total))
    if pct < 10:
        return human_bytes(free), sub, "critical", _("LLENO")
    if pct < 20:
        return human_bytes(free), sub, "warning", _("POCO ESPACIO")
    return human_bytes(free), sub, "ok", _("BIEN")


def security_tile(report: DiagnosticReport) -> tuple[str, str, str, str]:
    problems = report.security.problems
    critical = [c for c in problems if c.critical]
    if critical:
        return _("Revisar"), _(critical[0].name), "critical", _("EN RIESGO")
    if problems:
        return _("{n} avisos", n=len(problems)), _(problems[0].name), "warning", _("ATENCIÓN")
    if not report.security.checks:
        return "n/d", _("No se pudo comprobar"), "neutral", "—"
    return _("Todo OK"), _("Antivirus y firewall activos"), "ok", _("PROTEGIDO")


class HomePage(Page):
    title = "Así está tu equipo"
    subtitle = ""

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        self.data: HomeData | None = None
        self._running = False
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD, pady=(0, PAD))
        self.body = body

        head = ctk.CTkFrame(body, fg_color="transparent")
        head.pack(fill="x", pady=(PAD_S, PAD))
        self.where = ctk.CTkLabel(head, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.where.pack(side="left")
        self.refresh_btn = ctk.CTkButton(
            head,
            text=_("Volver a revisar"),
            image=icon("refresh", ("#1b1f24", "#c9d0db"), 16),
            compound="left",
            width=150,
            **SECONDARY_BUTTON,
            command=self.load,
        )
        self.refresh_btn.pack(side="right")

        self.update_card = Card(body, fg_color=BG_CARD_HI)
        self.update_label = ctk.CTkLabel(self.update_card, text="", font=FONT_BODY, justify="left")
        self.update_label.pack(side="left", padx=PAD, pady=PAD)
        self.update_btn = ctk.CTkButton(
            self.update_card, text=_("Actualizar ahora"), width=150, command=self._install_update
        )
        self.update_btn.pack(side="right", padx=PAD, pady=PAD)
        self.update_info: ReleaseInfo | None = None

        self._build_hero(body)
        self._build_tiles(body)
        self._build_shortcuts(body)

    # ------------------------------------------------------------------ construcción

    def _build_hero(self, parent: Any) -> None:
        hero = ctk.CTkFrame(
            parent,
            fg_color=BG_CARD_HI,
            corner_radius=RADIUS + 6,
            border_width=1,
            border_color=BORDER,
        )
        hero.pack(fill="x", pady=(0, PAD))
        self.gauge = Gauge(hero)
        self.gauge.pack(side="left", padx=PAD * 2, pady=PAD * 2)
        text = ctk.CTkFrame(hero, fg_color="transparent")
        text.pack(side="left", fill="both", expand=True, padx=(0, PAD * 2), pady=PAD * 2)
        self.chip = Chip(text, _("REVISANDO…"), "neutral")
        self.chip.pack(anchor="w")
        self.headline = ctk.CTkLabel(
            text,
            text=_("Revisando tu equipo…"),
            font=FONT_HERO,
            wraplength=WRAP - 240,
            justify="left",
            anchor="w",
        )
        self.headline.pack(anchor="w", fill="x", pady=(PAD_S, PAD_S))
        self.detail = ctk.CTkLabel(
            text,
            text=_("Tarda unos segundos. No se cambia nada."),
            font=FONT_BODY,
            text_color=TEXT_MUTED,
            wraplength=WRAP - 240,
            justify="left",
            anchor="w",
        )
        self.detail.pack(anchor="w", fill="x")
        buttons = ctk.CTkFrame(text, fg_color="transparent")
        buttons.pack(anchor="w", pady=(PAD + 2, 0))
        self.fix_btn = ctk.CTkButton(
            buttons,
            text=_("Arreglar mi PC"),
            image=icon("bolt", ("#ffffff", "#ffffff"), 18),
            compound="left",
            font=(FONT_H2[0], 15, "bold"),
            height=46,
            width=190,
            **PRIMARY_BUTTON,
            command=self.fix,
        )
        self.fix_btn.pack(side="left")
        ctk.CTkButton(
            buttons,
            text=_("Ver qué le pasa"),
            height=46,
            width=150,
            corner_radius=12,
            **{k: v for k, v in SECONDARY_BUTTON.items()},
            command=lambda: self.main.show("diagnostics"),
        ).pack(side="left", padx=PAD_S)

    def _build_tiles(self, parent: Any) -> None:
        grid = ctk.CTkFrame(parent, fg_color="transparent")
        grid.pack(fill="x", pady=(0, PAD))
        specs = (
            ("boot", "clock", _("Arranque")),
            ("memory", "memory", _("Memoria")),
            ("disk", "drive", _("Disco")),
            ("security", "shield", _("Seguridad")),
        )
        self.tiles: dict[str, StatusTile] = {}
        for col, (key, icon_name, title) in enumerate(specs):
            grid.grid_columnconfigure(col, weight=1, uniform="tiles")
            tile = StatusTile(grid, icon_name, title)
            tile.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else PAD_S, 0))
            self.tiles[key] = tile

    def _build_shortcuts(self, parent: Any) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x")
        shortcuts = [
            (
                "trash",
                _("Liberar espacio"),
                _("Temporales, miniaturas y caché"),
                "info",
                self.free_space,
            ),
            (
                "gamepad",
                _("Modo juego"),
                _("Todo a favor del juego"),
                "purple",
                lambda: self._dashboard().toggle_game_mode(),
            ),
        ]
        if self.state.app.env.has_battery:
            shortcuts.append(
                (
                    "battery",
                    _("Modo ahorro"),
                    _("Más batería fuera de casa"),
                    "ok",
                    lambda: self._dashboard().toggle_battery_mode(),
                )
            )
        self.shortcuts: dict[str, ShortcutTile] = {}
        for col, (icon_name, title, sub, tone, command) in enumerate(shortcuts):
            row.grid_columnconfigure(col, weight=1, uniform="shortcuts")
            tile = ShortcutTile(row, icon_name, title, sub, tone, command)
            tile.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else PAD_S, 0))
            self.shortcuts[icon_name] = tile

    # ------------------------------------------------------------------ datos

    def on_show(self) -> None:
        if self.data is None:
            self.load()

    def load(self) -> None:
        if self._running:
            return
        self._running = True
        app = self.state.app
        self.refresh_btn.configure(state="disabled")
        self.chip.set(_("REVISANDO…"), "neutral")

        def work(_p: ProgressFn, _c: threading.Event) -> HomeData:
            from core.diagnostics import collect
            from core.gamemode import BatteryMode, GameMode

            report = collect(app.env, app.registry, app.runner)
            try:
                boot = last_boot(app.runner)
            except Exception:  # noqa: BLE001 - sin el dato de arranque la nota se calcula igual
                boot = None
            boot_ms = boot.boot_ms if boot else None
            return HomeData(
                report=report,
                boot_ms=boot_ms,
                health=from_report(report, boot_ms),
                game_on=GameMode(app.engine).active,
                battery_on=BatteryMode(app.engine).active,
            )

        def done(data: HomeData) -> None:
            self._running = False
            self.refresh_btn.configure(state="normal")
            self.data = data
            self.render(data)

        def failed(exc: BaseException) -> None:
            self._running = False
            self.refresh_btn.configure(state="normal")
            self.chip.set(_("SIN DATOS"), "neutral")
            self.headline.configure(text=_("No se pudo revisar el equipo"))
            self.detail.configure(text=str(exc))

        BackgroundTask(self, work, done, failed).start()

    def render(self, data: HomeData) -> None:
        health, report = data.health, data.report
        env, snap = report.env, report.snapshot
        self.where.configure(text=f"{env.os_label} · " + _("revisado ahora mismo"))
        self.gauge.set(health.score, health.tone)
        self.chip.set(health.label, health.tone)
        self.headline.configure(text=health.headline)
        self.detail.configure(text=health.detail)
        self.tiles["boot"].set(*boot_tile(data.boot_ms))
        self.tiles["memory"].set(
            *memory_tile(report.ram_installed or snap.ram_total, snap.ram_percent, snap.ram_used)
        )
        disk_title = {"ssd": " (SSD)", "hdd": " (HDD)"}.get(env.disk_type, "")
        value, sub, tone, chip = disk_tile(snap.disk_free, snap.disk_total)
        self.tiles["disk"].set(value, sub + disk_title, tone, chip)
        self.tiles["security"].set(*security_tile(report))
        active = _("Activado: pulsa para desactivar")
        game = self.shortcuts.get("gamepad")
        if game is not None:
            game.set_subtitle(active if data.game_on else _("Todo a favor del juego"))
        battery = self.shortcuts.get("battery")
        if battery is not None:
            battery.set_subtitle(active if data.battery_on else _("Más batería fuera de casa"))

    # ------------------------------------------------------------------ acciones

    def _dashboard(self) -> DashboardPage:
        from ui.pages.dashboard import DashboardPage

        page = self.main.page("dashboard")
        assert isinstance(page, DashboardPage)  # noqa: S101 - la clave "dashboard" es siempre esta
        return page

    def fix(self) -> None:
        self._dashboard().fix_my_pc()

    def free_space(self) -> None:
        from core.fixplan import FIX_CLEANUPS

        engine = self.state.app.engine
        ids = {
            tid
            for tid in (*FIX_CLEANUPS, "cleanup.browser_cache")
            if tid in engine.catalog and engine.evaluate(engine.catalog.get(tid)).applicable
        }
        if not ids:
            show_error(_("Liberar espacio"), _("No hay nada que limpiar ahora mismo."), self)
            return
        self.state.selected |= ids
        self.state.notify()
        self.main.simulate()

    def show_update(self, info: ReleaseInfo) -> None:
        self.update_info = info
        self.update_label.configure(
            text=_("Hay una versión nueva de SafeBoost: {v}", v=info.version)
        )
        self.update_card.pack(fill="x", pady=(0, PAD), before=self.body.winfo_children()[1])

    def _install_update(self) -> None:
        if self.update_info is None:
            return
        dashboard = self._dashboard()
        dashboard.show_update(self.update_info)
        dashboard._install_update()
