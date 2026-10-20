"""Janela modal base e diálogo simples de texto."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Optional

import customtkinter as ctk

from .. import theme


class ModalDialog(ctk.CTkToplevel):
    """Toplevel modal centralizado sobre a janela principal. `show()` bloqueia e devolve `self.result`."""

    def __init__(self, master, title: str, width: int = 520, height: int = 360):
        super().__init__(master)
        self.result: Any = None
        self.title(title)
        self.configure(fg_color=theme.SURFACE)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _event: self.cancel())
        master.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - width) // 2
        y = master.winfo_rooty() + (master.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=theme.PAD, pady=(theme.PAD, 0))
        self.footer = ctk.CTkFrame(self, fg_color="transparent")
        self.footer.pack(fill="x", padx=theme.PAD, pady=theme.PAD)

    def add_buttons(self, ok_text: str = "OK") -> None:
        theme.primary_button(self.footer, ok_text, self.accept, width=120).pack(side="right")
        theme.neutral_button(self.footer, "Cancelar", self.cancel, width=100, height=36).pack(side="right", padx=(0, theme.GAP))

    def show(self) -> Any:
        self.after(120, self._activate)
        self.wait_window()
        return self.result

    def _activate(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            self.after(120, self._activate)

    def accept(self) -> None:
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()


class TextDialog(ModalDialog):
    def __init__(self, master, title: str, label: str, initial: str = "", multiline: bool = False, secret: bool = False):
        super().__init__(master, title, width=460, height=300 if multiline else 190)
        ctk.CTkLabel(self.body, text=label, font=theme.font(13), text_color=theme.TEXT, anchor="w").pack(fill="x", pady=(0, 6))
        self._multiline = multiline
        if multiline:
            self._input = ctk.CTkTextbox(self.body, height=140, font=theme.font(13), border_width=1, border_color=theme.BORDER, wrap="word")
            self._input.insert("1.0", initial)
        else:
            self._input = ctk.CTkEntry(self.body, font=theme.font(13), show="•" if secret else "")
            self._input.insert(0, initial)
            self._input.bind("<Return>", lambda _event: self.accept())
        self._input.pack(fill="both", expand=True)
        self.add_buttons()
        self.after(200, self._input.focus_set)

    def accept(self) -> None:
        text = self._input.get("1.0", "end-1c") if self._multiline else self._input.get()
        self.result = text if text.strip() else None
        self.destroy()


def ask_text(master, title: str, label: str, initial: str = "", multiline: bool = False, secret: bool = False) -> Optional[str]:
    return TextDialog(master, title, label, initial, multiline, secret).show()
