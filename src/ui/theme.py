"""Paleta (claro, escuro), fontes e medidas da interface."""

from __future__ import annotations

from functools import lru_cache

import customtkinter as ctk

# Cada cor é (modo claro, modo escuro), formato aceito pelo CustomTkinter.
ACCENT = ("#2563EB", "#3B82F6")
ACCENT_HOVER = ("#1D4ED8", "#2563EB")
ACCENT_SOFT = ("#E8EEFE", "#1E2A44")
BACKGROUND = ("#F3F4F6", "#15171B")
SURFACE = ("#FFFFFF", "#1E2127")
SURFACE_ALT = ("#F8FAFC", "#252932")
HOVER = ("#F1F5FF", "#2A2F39")
BORDER = ("#E2E5EA", "#323844")
TEXT = ("#111827", "#E6E8EC")
TEXT_MUTED = ("#6B7280", "#9AA3AF")
SUCCESS = ("#15803D", "#4ADE80")
DANGER = ("#DC2626", "#F87171")
DANGER_HOVER = ("#B91C1C", "#EF4444")
WARNING = ("#B45309", "#FBBF24")
CANVAS = ("#E5E7EB", "#0F1114")
SEGMENT = ("#8E97A4", "#363C47")
SEGMENT_HOVER = ("#7D8693", "#424957")
NEUTRAL_BUTTON = ("#EEF0F3", "#2B3039")
NEUTRAL_BUTTON_HOVER = ("#E2E5EA", "#363C47")

PAD = 16
GAP = 8
RADIUS = 10
SIDEBAR_WIDTH = 236
CARD_WIDTH = 268
CARD_HEIGHT = 78


@lru_cache(maxsize=None)
def font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    """Fonte do tema (criada sob demanda: exige a janela principal já instanciada)."""
    return ctk.CTkFont(size=size, weight=weight)


def color(pair) -> str:
    """Resolve um par (claro, escuro) para o modo atual — útil para widgets Tk puros (Canvas)."""
    if isinstance(pair, str):
        return pair
    return pair[1] if ctk.get_appearance_mode() == "Dark" else pair[0]


def set_entry_text(entry: ctk.CTkEntry, value: str = "") -> None:
    """
    Troca o texto de um CTkEntry preservando o placeholder.

    O CTkEntry nasce marcado como "focado" e só restaura o placeholder ao perder o foco;
    reaplicar `placeholder_text` (API pública) o reexibe quando o campo fica vazio.
    """
    if entry.get():
        entry.delete(0, "end")
    if value:
        entry.insert(0, str(value))
        return
    focused = entry.focus_get()
    if focused is None or not str(focused).startswith(str(entry)):
        entry.configure(placeholder_text=entry.cget("placeholder_text"))


def primary_button(master, text: str, command, width: int = 140, height: int = 36, **kwargs) -> ctk.CTkButton:
    return ctk.CTkButton(master, text=text, command=command, width=width, height=height, fg_color=ACCENT, hover_color=ACCENT_HOVER, font=font(13, "bold"), corner_radius=8, **kwargs)


def neutral_button(master, text: str, command, width: int = 110, height: int = 32, **kwargs) -> ctk.CTkButton:
    return ctk.CTkButton(
        master, text=text, command=command, width=width, height=height, fg_color=NEUTRAL_BUTTON, hover_color=NEUTRAL_BUTTON_HOVER, text_color=TEXT, font=font(12), corner_radius=8, **kwargs
    )


def segmented(master, values, command=None, font_size: int = 12, **kwargs) -> ctk.CTkSegmentedButton:
    """Botões segmentados com contraste adequado nos dois temas (texto branco sobre cinza médio/destaque)."""
    return ctk.CTkSegmentedButton(
        master,
        values=list(values),
        command=command,
        font=font(font_size),
        selected_color=ACCENT,
        selected_hover_color=ACCENT_HOVER,
        unselected_color=SEGMENT,
        unselected_hover_color=SEGMENT_HOVER,
        fg_color=SEGMENT,
        text_color="#FFFFFF",
        **kwargs,
    )


def icon_button(master, image, command, tooltip: str = "", size: int = 30, **kwargs) -> ctk.CTkButton:
    button = ctk.CTkButton(master, text="", image=image, command=command, width=size, height=size, fg_color="transparent", hover_color=NEUTRAL_BUTTON_HOVER, corner_radius=6, **kwargs)
    if tooltip:
        Tooltip(button, tooltip)
    return button


class Tooltip:
    """Dica exibida ao parar o mouse sobre um widget."""

    _DELAY_MS = 550

    def __init__(self, widget, text: str):
        self.widget, self.text = widget, text
        self._window = None
        self._job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._job = self.widget.after(self._DELAY_MS, self._show)

    def _show(self):
        import tkinter as tk

        if self._window or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{x}+{y}")
        tk.Label(self._window, text=self.text, bg="#111827", fg="#F9FAFB", padx=8, pady=4, font=("Segoe UI", 9)).pack()

    def _hide(self, _event=None):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None
        if self._window:
            self._window.destroy()
            self._window = None
