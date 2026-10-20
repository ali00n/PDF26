"""Cabeçalho das telas de ferramenta: voltar, ícone, título, descrição e favorito."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from ...domain.tool import ToolSpec
from .. import icons, theme


class PageHeader(ctk.CTkFrame):
    def __init__(self, master, tool: ToolSpec, on_back: Callable[[], None], is_favorite: bool, on_favorite: Callable[[], bool]):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(2, weight=1)
        self._on_favorite = on_favorite
        theme.icon_button(self, icons.icon("back", 20), on_back, "Voltar (Esc)", size=36).grid(row=0, column=0, rowspan=2, padx=(0, 10))
        ctk.CTkLabel(self, text="", image=icons.tool_icon(tool.icon, tool.color, 44)).grid(row=0, column=1, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(self, text=tool.name, font=theme.font(22, "bold"), text_color=theme.TEXT, anchor="w").grid(row=0, column=2, sticky="sw")
        ctk.CTkLabel(self, text=tool.description, font=theme.font(13), text_color=theme.TEXT_MUTED, anchor="w").grid(row=1, column=2, sticky="nw")
        self.extra = ctk.CTkFrame(self, fg_color="transparent", width=1, height=1)
        self.extra.grid(row=0, column=3, rowspan=2, padx=(theme.GAP, 0))
        self._star = theme.icon_button(self, self._star_image(is_favorite), self._toggle, "Favoritar", size=36)
        self._star.grid(row=0, column=4, rowspan=2, padx=(theme.GAP, 0))

    @staticmethod
    def _star_image(active: bool):
        return icons.icon("star", 20, ("#F59E0B", "#FBBF24")) if active else icons.icon("star_outline", 20, theme.TEXT_MUTED)

    def _toggle(self) -> None:
        self._star.configure(image=self._star_image(self._on_favorite()))
