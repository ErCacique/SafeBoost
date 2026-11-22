"""Componentes reutilizables de la interfaz."""

from __future__ import annotations

import queue
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from core.catalog import Applicability, Tweak
from core.context import DETECT_LABELS, DetectResult
from core.environment import EnvironmentInfo
from core.i18n import _, tweak_name, tweak_text
from core.sources import source_for
from ui.theme import (
    BG_CARD,
    FONT_BODY,
    FONT_H2,
    FONT_METRIC,
    FONT_MONO,
    FONT_SMALL,
    LOG_MAX_LINES,
    LOG_POLL_MS,
    PAD,
    PAD_S,
    RADIUS,
    RISK_COLORS,
    STATE_COLORS,
    TEXT_MUTED,
    WRAP,
)


class Card(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs: Any) -> None:
        super().__init__(master, fg_color=BG_CARD, corner_radius=RADIUS, **kwargs)


class MetricCard(Card):
    """Tarjeta con título, valor grande y subtítulo."""

    def __init__(self, master: Any, title: str) -> None:
        super().__init__(master)
        ctk.CTkLabel(self, text=title, font=FONT_SMALL, text_color=TEXT_MUTED).pack(
            anchor="w", padx=PAD, pady=(PAD, 0)
        )
        self.value = ctk.CTkLabel(self, text="—", font=FONT_METRIC)
        self.value.pack(anchor="w", padx=PAD)
        self.sub = ctk.CTkLabel(self, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.sub.pack(anchor="w", padx=PAD, pady=(0, PAD))

    def set(self, value: str, sub: str = "") -> None:
        self.value.configure(text=value)
        self.sub.configure(text=sub)


class Badge(ctk.CTkLabel):
    def __init__(self, master: Any, text: str, color: tuple[str, str]) -> None:
        super().__init__(
            master,
            text=f" {text} ",
            font=FONT_SMALL,
            text_color="white",
            fg_color=color,
            corner_radius=6,
        )


def risk_badge(master: Any, risk: str) -> Badge:
    return Badge(master, f"riesgo {risk}", RISK_COLORS.get(risk, RISK_COLORS["medio"]))


class TweakRow(ctk.CTkFrame):
    """Fila de un tweak: casilla, nombre, riesgo, estado detectado y detalle desplegable."""

    def __init__(
        self,
        master: Any,
        tweak: Tweak,
        applicability: Applicability,
        selected: bool,
        on_toggle: Callable[[str, bool], None],
        on_param: Callable[[str, str, Any], None] | None = None,
        env: EnvironmentInfo | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.tweak = tweak
        self.env = env
        self._expanded = False
        self.var = ctk.BooleanVar(value=selected)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x")
        self.check = ctk.CTkCheckBox(
            top,
            text=tweak_name(tweak.id, tweak.name),
            variable=self.var,
            font=FONT_BODY,
            command=lambda: on_toggle(tweak.id, self.var.get()),
        )
        self.check.pack(side="left", padx=(0, PAD_S))
        if not applicability.applicable:
            self.check.configure(state="disabled")
        risk_badge(top, tweak.risk).pack(side="left", padx=2)
        if tweak.is_action or tweak.is_irreversible:
            Badge(top, "irreversible", RISK_COLORS["alto"]).pack(side="left", padx=2)
        if tweak.reboot_required:
            Badge(top, "reinicio", RISK_COLORS["medio"]).pack(side="left", padx=2)
        if not tweak.auto_profile:
            Badge(top, "solo manual", STATE_COLORS["not_applied"]).pack(side="left", padx=2)
        self.state_label = ctk.CTkLabel(top, text="…", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.state_label.pack(side="right", padx=PAD_S)
        ctk.CTkButton(
            top,
            text="ⓘ",
            width=28,
            height=24,
            fg_color="transparent",
            text_color=TEXT_MUTED,
            hover_color=BG_CARD,
            command=self._toggle_detail,
        ).pack(side="right")

        self.detail = ctk.CTkFrame(self, fg_color="transparent")
        tid = tweak.id
        lines = [
            tweak_text(tid, "description", tweak.description),
            f"{_('Por qué')}: {tweak_text(tid, 'rationale', tweak.rationale)}",
        ]
        if tweak.revert_note:
            lines.append(f"{_('Reversión')}: {tweak_text(tid, 'revert_note', tweak.revert_note)}")
        source = source_for(tweak.id)
        if source:
            lines.append(f"{_('Documentación oficial')}: {source}")
        if not applicability.applicable:
            lines.append(_("No aplicable") + ": " + "; ".join(applicability.reasons))
        elif applicability.preselect_reasons:
            lines.append(
                _("No se preselecciona") + ": " + "; ".join(applicability.preselect_reasons)
            )
        ctk.CTkLabel(
            self.detail,
            text="\n".join(lines),
            font=FONT_SMALL,
            text_color=TEXT_MUTED,
            justify="left",
            wraplength=WRAP,
            anchor="w",
        ).pack(anchor="w", padx=(28, 0))
        if tweak.params and on_param:
            self._build_params(on_param)

    def _build_params(self, on_param: Callable[[str, str, Any], None]) -> None:
        box = ctk.CTkFrame(self.detail, fg_color="transparent")
        box.pack(anchor="w", padx=(28, 0), pady=PAD_S)
        for name, spec in self.tweak.params.items():
            ctk.CTkLabel(box, text=f"{spec.get('label', name)}:", font=FONT_SMALL).pack(side="left")
            if spec["type"] == "drives" and self.env is not None and self.env.fixed_drives:
                self._build_drives(box, name, on_param)
            elif spec["type"] == "choice":
                values = [str(c) for c in spec.get("choices", [])]
                menu = ctk.CTkOptionMenu(
                    box,
                    values=["(elige)", *values],
                    command=lambda v, n=name: on_param(
                        self.tweak.id, n, None if v == "(elige)" else v
                    ),
                )
                menu.pack(side="left", padx=PAD_S)
            else:
                entry = ctk.CTkEntry(box, width=160, placeholder_text=str(spec.get("default")))
                entry.pack(side="left", padx=PAD_S)
                entry.bind(
                    "<FocusOut>",
                    lambda _e, n=name, w=entry, t=spec["type"]: on_param(
                        self.tweak.id, n, _parse_param(w.get(), t)
                    ),
                )

    def _build_drives(self, box: Any, name: str, on_param: Callable[[str, str, Any], None]) -> None:
        """Una casilla por unidad fija. Por defecto, todas menos la del sistema."""
        if self.env is None:
            return
        system = self.env.system_drive.upper()
        variables: dict[str, ctk.BooleanVar] = {}

        def changed() -> None:
            on_param(self.tweak.id, name, [d for d, v in variables.items() if v.get()])

        for drive in self.env.fixed_drives:
            is_system = drive.upper() == system
            variables[drive] = ctk.BooleanVar(value=not is_system)
            ctk.CTkCheckBox(
                box,
                text=f"{drive} (sistema)" if is_system else drive,
                variable=variables[drive],
                font=FONT_SMALL,
                width=24,
                command=changed,
            ).pack(side="left", padx=PAD_S)

    def _toggle_detail(self) -> None:
        self._expanded = not self._expanded
        if self._expanded:
            self.detail.pack(fill="x", pady=(0, PAD_S))
        else:
            self.detail.pack_forget()

    def set_selected(self, value: bool) -> None:
        if self.var.get() != value:
            self.var.set(value)

    def set_detection(self, result: DetectResult) -> None:
        text = DETECT_LABELS[result.state]
        if result.detail:
            text += f" · {result.detail}"
        self.state_label.configure(
            text=text[:70], text_color=STATE_COLORS.get(result.state.value, TEXT_MUTED)
        )


def _parse_param(raw: str, kind: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    if kind == "int":
        try:
            return int(raw)
        except ValueError:
            return None
    if kind == "drives":
        return [d.strip().upper() for d in raw.replace(";", ",").split(",") if d.strip()]
    return raw


class SectionHeader(ctk.CTkFrame):
    def __init__(self, master: Any, title: str, subtitle: str = "") -> None:
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=title, font=FONT_H2).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(
                self,
                text=subtitle,
                font=FONT_SMALL,
                text_color=TEXT_MUTED,
                wraplength=WRAP,
                justify="left",
            ).pack(anchor="w")


class LogPanel(ctk.CTkFrame):
    """Log en vivo alimentado por la cola del logger (core.logger.ui_log_queue)."""

    def __init__(self, master: Any, source: queue.Queue[str]) -> None:
        super().__init__(master, fg_color="transparent")
        self.source = source
        self.text = ctk.CTkTextbox(self, height=140, font=FONT_MONO, wrap="none")
        self.text.pack(fill="both", expand=True)
        self.text.configure(state="disabled")
        self._lines = 0
        self.after(LOG_POLL_MS, self._drain)

    def _drain(self) -> None:
        batch: list[str] = []
        while len(batch) < 500:
            try:
                batch.append(self.source.get_nowait())
            except queue.Empty:
                break
        if batch:
            self.text.configure(state="normal")
            self.text.insert("end", "\n".join(batch) + "\n")
            self._lines += len(batch)
            if self._lines > LOG_MAX_LINES:
                excess = self._lines - LOG_MAX_LINES
                self.text.delete("1.0", f"{excess + 1}.0")
                self._lines = LOG_MAX_LINES
            self.text.see("end")
            self.text.configure(state="disabled")
        self.after(LOG_POLL_MS, self._drain)


class ProgressBar(ctk.CTkFrame):
    def __init__(self, master: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.bar = ctk.CTkProgressBar(self)
        self.bar.set(0)
        self.bar.pack(side="left", fill="x", expand=True, padx=(0, PAD_S))
        self.label = ctk.CTkLabel(
            self, text="Listo", font=FONT_SMALL, text_color=TEXT_MUTED, width=320, anchor="w"
        )
        self.label.pack(side="left")

    def update_progress(self, fraction: float, message: str) -> None:
        self.bar.set(max(0.0, min(1.0, fraction)))
        self.label.configure(text=message[:60])

    def reset(self, message: str = "Listo") -> None:
        self.update_progress(0.0, message)
