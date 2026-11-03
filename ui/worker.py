"""Ejecución de tareas largas fuera del hilo de Tk.

Tk no es thread-safe: los hilos de trabajo nunca tocan widgets. Publican eventos en una cola
y el hilo principal los consume con `after()`.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import customtkinter as ctk

from core.logger import get_logger
from ui.theme import POLL_MS

log = get_logger("ui.worker")

ProgressFn = Callable[[float, str], None]


@dataclass
class _Event:
    kind: str  # "progress" | "done" | "error"
    payload: Any


class BackgroundTask:
    """Ejecuta fn(progress, cancel) en un hilo y entrega callbacks en el hilo de Tk."""

    def __init__(
        self,
        widget: ctk.CTkBaseClass | ctk.CTk,
        fn: Callable[[ProgressFn, threading.Event], Any],
        on_done: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_progress: ProgressFn | None = None,
    ) -> None:
        self.widget = widget
        self.fn = fn
        self.on_done = on_done
        self.on_error = on_error
        self.on_progress = on_progress
        self.cancel_event = threading.Event()
        self._events: queue.Queue[_Event] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> BackgroundTask:
        self._thread.start()
        self.widget.after(POLL_MS, self._poll)
        return self

    def cancel(self) -> None:
        self.cancel_event.set()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def _progress(self, fraction: float, message: str) -> None:
        self._events.put(_Event("progress", (fraction, message)))

    def _run(self) -> None:
        try:
            result = self.fn(self._progress, self.cancel_event)
        except Exception as exc:
            log.exception("background_task_failed")
            self._events.put(_Event("error", exc))
        else:
            self._events.put(_Event("done", result))

    def _poll(self) -> None:
        finished = False
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            if event.kind == "progress" and self.on_progress:
                self.on_progress(*event.payload)
            elif event.kind == "done":
                finished = True
                if self.on_done:
                    self.on_done(event.payload)
            elif event.kind == "error":
                finished = True
                if self.on_error:
                    self.on_error(event.payload)
        if not finished:
            try:
                self.widget.after(POLL_MS, self._poll)
            except tk.TclError:
                # La ventana se cerró mientras la tarea seguía en marcha.
                self.cancel_event.set()
