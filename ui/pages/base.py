"""Clase base de las páginas y utilidades comunes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from ui.theme import FONT_SMALL, FONT_TITLE, PAD, TEXT_MUTED

if TYPE_CHECKING:
    from ui.app import MainWindow


class Page(ctk.CTkFrame):
    title = ""
    subtitle = ""

    def __init__(self, master: Any, main: MainWindow) -> None:
        super().__init__(master, fg_color="transparent")
        self.main = main
        self.state = main.ui
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=PAD, pady=(PAD, 0))
        ctk.CTkLabel(head, text=self.title, font=FONT_TITLE).pack(anchor="w")
        if self.subtitle:
            ctk.CTkLabel(
                head,
                text=self.subtitle,
                font=FONT_SMALL,
                text_color=TEXT_MUTED,
                wraplength=950,
                justify="left",
            ).pack(anchor="w")

    def on_show(self) -> None:
        """Se llama cada vez que la página pasa a primer plano."""


def open_path(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606 - ruta propia de SafeTrim
    else:
        subprocess.Popen(["xdg-open", str(path)])


def show_error(title: str, error: BaseException | str, parent: Any = None) -> None:
    messagebox.showerror(title, str(error), parent=parent)
