"""Componentes reutilizables de la interfaz."""

from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from core.catalog import Applicability, Tweak
from core.context import DETECT_LABELS, DetectResult
from core.environment import EnvironmentInfo
from core.i18n import _, tweak_name, tweak_text
from core.sources import source_for
from ui.icons import icon
from ui.theme import (
    BG_CARD,
    BG_CARD_HI,
    BORDER,
    FONT_BIG,
    FONT_BODY,
    FONT_CHIP,
    FONT_H2,
    FONT_METRIC,
    FONT_MONO,
    FONT_SCORE,
    FONT_SMALL,
    LOG_MAX_LINES,
    LOG_POLL_MS,
    NAV_HOVER,
    PAD,
    PAD_S,
    RADIUS,
    RISK_COLORS,
    STATE_COLORS,
    TEXT_MUTED,
    TONES,
    WRAP,
)


class Card(ctk.CTkFrame):
    def __init__(self, master: Any, **kwargs: Any) -> None:
        kwargs.setdefault("fg_color", BG_CARD)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", BORDER)
        super().__init__(master, corner_radius=RADIUS, **kwargs)


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


# ------------------------------------------------------------------ v0.12: componentes visuales


def mode_color(pair: tuple[str, str] | str) -> str:
    """Color concreto del par (claro, oscuro) según el modo de apariencia actual."""
    if isinstance(pair, str):
        return pair
    return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]


def tone_colors(tone: str) -> tuple[tuple[str, str], tuple[str, str]]:
    return TONES.get(tone, TONES["neutral"])


class Chip(ctk.CTkLabel):
    """Etiqueta en mayúsculas con fondo del color de su estado (BIEN, ATENCIÓN…)."""

    def __init__(self, master: Any, text: str, tone: str = "neutral") -> None:
        fg, bg = tone_colors(tone)
        super().__init__(
            master,
            text=text,
            font=FONT_CHIP,
            text_color=fg,
            fg_color=bg,
            corner_radius=999,
            height=24,
            padx=10,
        )

    def set(self, text: str, tone: str) -> None:
        fg, bg = tone_colors(tone)
        self.configure(text=text, text_color=fg, fg_color=bg)


class IconBadge(ctk.CTkLabel):
    """Icono dentro de un cuadrado redondeado del color de su estado."""

    def __init__(self, master: Any, name: str, tone: str = "info", size: int = 40) -> None:
        fg, bg = tone_colors(tone)
        super().__init__(
            master,
            text="",
            image=icon(name, fg, size // 2),
            fg_color=bg,
            corner_radius=size // 4,
            width=size,
            height=size,
        )

    def set(self, name: str, tone: str) -> None:
        fg, bg = tone_colors(tone)
        self.configure(image=icon(name, fg, self.cget("width") // 2), fg_color=bg)


class Gauge(ctk.CTkFrame):
    """Anillo de 0 a 100 con la cifra en el centro (la nota de salud del Inicio)."""

    def __init__(self, master: Any, size: int = 176, thickness: int = 14) -> None:
        super().__init__(master, fg_color="transparent", width=size, height=size)
        self.size = size
        self.thickness = thickness
        self.value: int | None = None
        self.tone = "neutral"
        self.canvas = tk.Canvas(self, width=size, height=size, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0)
        self.number = ctk.CTkLabel(self, text="—", font=FONT_SCORE, fg_color="transparent")
        self.number.place(relx=0.5, rely=0.46, anchor="center")
        self.caption = ctk.CTkLabel(
            self, text=_("de 100"), font=FONT_SMALL, text_color=TEXT_MUTED, fg_color="transparent"
        )
        self.caption.place(relx=0.5, rely=0.66, anchor="center")
        self._paint()

    def set(self, value: int | None, tone: str) -> None:
        self.value, self.tone = value, tone
        self.number.configure(text="—" if value is None else str(value))
        self._paint()

    def _paint(self) -> None:
        c, s, t = self.canvas, self.size, self.thickness
        c.delete("all")
        c.configure(bg=mode_color(BG_CARD_HI))
        box = (t, t, s - t, s - t)
        c.create_oval(*box, outline=mode_color(BORDER), width=t)
        if self.value:
            extent = -359.9 * max(0, min(100, self.value)) / 100
            color = mode_color(tone_colors(self.tone)[0])
            c.create_arc(*box, start=90, extent=extent, style="arc", outline=color, width=t)

    def _set_appearance_mode(self, mode_string: str) -> None:
        super()._set_appearance_mode(mode_string)
        self._paint()


class StatusTile(Card):
    """Tarjeta de estado del Inicio: icono, chip, nombre, cifra grande y explicación."""

    def __init__(self, master: Any, icon_name: str, title: str) -> None:
        super().__init__(master)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=PAD + 4, pady=(PAD + 4, PAD_S))
        self.badge = IconBadge(top, icon_name, "neutral")
        self.badge.pack(side="left")
        self.icon_name = icon_name
        self.chip = Chip(top, "…", "neutral")
        self.chip.pack(side="right")
        ctk.CTkLabel(self, text=title, font=FONT_BODY, text_color=TEXT_MUTED).pack(
            anchor="w", padx=PAD + 4
        )
        self.value = ctk.CTkLabel(self, text="—", font=FONT_BIG)
        self.value.pack(anchor="w", padx=PAD + 4)
        self.sub = ctk.CTkLabel(self, text="", font=FONT_SMALL, text_color=TEXT_MUTED)
        self.sub.pack(anchor="w", padx=PAD + 4, pady=(0, PAD + 4))

    def set(self, value: str, sub: str, tone: str, chip: str) -> None:
        self.value.configure(text=value)
        self.sub.configure(text=sub)
        self.chip.set(chip, tone)
        self.badge.set(self.icon_name, tone)


class ShortcutTile(Card):
    """Atajo grande: icono en su recuadro de color, título y subtítulo. Toda la tarjeta es
    clicable (y con el teclado: Tab para llegar, Intro o Espacio para pulsar)."""

    def __init__(
        self,
        master: Any,
        icon_name: str,
        title: str,
        subtitle: str,
        tone: str,
        command: Callable[[], None],
    ) -> None:
        super().__init__(master, cursor="hand2")
        self.command = command
        inner = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        inner.pack(fill="x", padx=PAD + 4, pady=PAD)
        badge = IconBadge(inner, icon_name, tone, 44)
        badge.pack(side="left")
        texts = ctk.CTkFrame(inner, fg_color="transparent", cursor="hand2")
        texts.pack(side="left", padx=PAD)
        self.title = ctk.CTkLabel(texts, text=title, font=FONT_H2, anchor="w", cursor="hand2")
        self.title.pack(anchor="w")
        self.subtitle = ctk.CTkLabel(
            texts, text=subtitle, font=FONT_SMALL, text_color=TEXT_MUTED, anchor="w", cursor="hand2"
        )
        self.subtitle.pack(anchor="w")
        for widget in (self, inner, badge, texts, self.title, self.subtitle):
            widget.bind("<Button-1>", lambda _e: self.command())
            widget.bind("<Enter>", lambda _e: self.configure(fg_color=NAV_HOVER))
            widget.bind("<Leave>", lambda _e: self.configure(fg_color=BG_CARD))
        tk.Frame.configure(self, takefocus=1)  # CTkFrame no acepta takefocus
        self.bind("<Return>", lambda _e: self.command())
        self.bind("<space>", lambda _e: self.command())

    def set_subtitle(self, text: str) -> None:
        self.subtitle.configure(text=text)
