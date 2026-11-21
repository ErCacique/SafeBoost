"""Espacio: qué ocupa el disco y qué programas hay instalados. Solo informa; no borra nada."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from core.constants import SYSTEM_ROOT
from core.diskusage import find_duplicates, last_used_by_exe, scan
from core.metrics import human_bytes
from core.programs import last_used, list_programs
from tweaks._common import user_profile_dir
from ui.pages.base import Page
from ui.theme import FONT_BODY, FONT_SMALL, PAD, PAD_S, SECONDARY_BUTTON, TEXT_MUTED, WRAP
from ui.widgets import Card
from ui.worker import BackgroundTask, ProgressFn

if TYPE_CHECKING:
    from ui.app import MainWindow

VIEWS = ("Carpetas", "Archivos grandes", "Duplicados", "Programas")
PROGRAMS_SHOWN = 40
UNUSED_DAYS = 180


def open_folder(path: Path) -> None:
    target = path if path.is_dir() else path.parent
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606 - carpeta local
    else:
        subprocess.Popen(["xdg-open", str(target)])


def open_apps_settings() -> None:
    if sys.platform == "win32":
        os.startfile("ms-settings:appsfeatures")  # type: ignore[attr-defined]  # noqa: S606


class SpacePage(Page):
    title = "Espacio"
    subtitle = (
        "Qué ocupa el disco y qué programas tienes instalados. SafeTrim solo te lo enseña: "
        "decides tú qué borrar o desinstalar."
    )

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, main)
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD, pady=(PAD, 0))
        self.view = ctk.StringVar(value=VIEWS[0])
        ctk.CTkSegmentedButton(
            bar, values=list(VIEWS), variable=self.view, command=self._show
        ).pack(side="left")
        self.status = ctk.CTkLabel(bar, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.status.pack(side="left", padx=PAD)
        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.data: dict[str, Any] = {}
        self._running: set[str] = set()

    def on_show(self) -> None:
        self._show(self.view.get())

    # ------------------------------------------------------------------ datos

    def _load(self, view: str) -> None:
        if view in self._running:
            return
        self._running.add(view)
        self.status.configure(text="Analizando… (puede tardar un minuto)")
        app = self.state.app
        profile = Path.home()

        def work(_p: ProgressFn, cancel: threading.Event) -> Any:
            # Carpeta del usuario con sesión (SafeTrim puede ejecutarse elevado con otra cuenta).
            try:
                home = user_profile_dir(app.engine._ctx(app.engine.catalog.tweaks[0], True))
            except Exception:  # noqa: BLE001 - sin perfil del usuario, el del proceso
                home = profile
            if view == "Carpetas":
                drive = Path(app.env.system_drive + "\\") if sys.platform == "win32" else home
                return scan(drive, cancel.is_set)
            if view == "Archivos grandes":
                return scan(home, cancel.is_set)
            if view == "Duplicados":
                return find_duplicates(home / "Downloads")
            by_exe = last_used_by_exe(SYSTEM_ROOT / "Prefetch")
            programs = list_programs(app.registry)
            return [(p, last_used(p, by_exe)) for p in programs]

        def done(result: Any) -> None:
            self._running.discard(view)
            self.data[view] = result
            self.status.configure(text="")
            if self.view.get() == view:
                self._render(view)

        def failed(exc: BaseException) -> None:
            self._running.discard(view)
            self.status.configure(text=f"No se pudo analizar: {exc}")

        BackgroundTask(self, work, done, failed).start()

    # ------------------------------------------------------------------ presentación

    def _show(self, view: str) -> None:
        if view in self.data:
            self._render(view)
        else:
            self._clear()
            self._load(view)

    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    def _row(self, card: Any, text: str, path: Path | None = None, detail: str = "") -> None:
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=PAD, pady=1)
        ctk.CTkLabel(row, text=text, font=FONT_BODY, anchor="w", wraplength=WRAP - 160).pack(
            side="left"
        )
        if path is not None:
            ctk.CTkButton(
                row, text="Abrir", width=70, **SECONDARY_BUTTON, command=lambda: open_folder(path)
            ).pack(side="right")
        if detail:
            ctk.CTkLabel(row, text=detail, font=FONT_SMALL, text_color=TEXT_MUTED).pack(
                side="right", padx=PAD_S
            )

    def _render(self, view: str) -> None:
        self._clear()
        data = self.data[view]
        card = Card(self.body)
        card.pack(fill="x")
        if view in ("Carpetas", "Archivos grandes"):
            items = data.folders if view == "Carpetas" else data.big_files
            label = f"En {data.root}" if view == "Carpetas" else f"En tu carpeta ({data.root})"
            ctk.CTkLabel(card, text=label, font=FONT_SMALL, text_color=TEXT_MUTED).pack(
                anchor="w", padx=PAD, pady=(PAD, PAD_S)
            )
            if not items:
                self._row(card, "No hay archivos de más de 200 MB.")
            for item in items:
                self._row(card, f"{human_bytes(item.size)}  ·  {item.path}", item.path)
        elif view == "Duplicados":
            if not data:
                self._row(card, "No hay archivos repetidos en Descargas.")
            total = sum(g.wasted for g in data)
            if data:
                ctk.CTkLabel(
                    card,
                    text=f"Borrando las copias sobrantes recuperarías {human_bytes(total)}.",
                    font=FONT_BODY,
                ).pack(anchor="w", padx=PAD, pady=(PAD, PAD_S))
            for group in data[:20]:
                names = ", ".join(p.name for p in group.paths)
                self._row(
                    card,
                    f"{len(group.paths)} copias de {human_bytes(group.size)}: {names}",
                    group.paths[0],
                )
        else:
            data = sorted(data, key=lambda item: item[0].size_kb, reverse=True)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=PAD, pady=(PAD, PAD_S))
            ctk.CTkLabel(
                top,
                text=f"{len(data)} programas, de mayor a menor (tamaño que declara cada "
                "instalador). Último uso según Windows.",
                font=FONT_SMALL,
                text_color=TEXT_MUTED,
            ).pack(side="left")
            ctk.CTkButton(
                top, text="Desinstalar programas…", width=190, command=open_apps_settings
            ).pack(side="right")
            now = datetime.now().timestamp()
            for program, used in data[:PROGRAMS_SHOWN]:
                size = human_bytes(program.size_kb * 1024) if program.size_kb else "?"
                if used is None:
                    when = "último uso: desconocido"
                else:
                    days = int((now - used) / 86400)
                    when = f"último uso: hace {days} días" + (
                        "  (¿lo sigues necesitando?)" if days > UNUSED_DAYS else ""
                    )
                self._row(card, f"{program.name}  ·  {size}", detail=when)
        ctk.CTkFrame(card, height=PAD_S, fg_color="transparent").pack()
