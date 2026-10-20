"""Tela inicial: grade de ferramentas com busca, favoritas, recentes e categorias."""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Sequence, Tuple

import customtkinter as ctk

from ...config.catalog import all_tools, tools_by_id
from ...domain.tool import CATEGORIES, CATEGORY_BY_ID, ToolSpec
from .. import icons, theme

_CARD_GAP = 18  # horizontal; na vertical os cartões ficam mais próximos (_CARD_GAP_Y)
_CARD_GAP_Y = 12
_TEXT_WIDTH = theme.CARD_WIDTH - 100  # ícone (64) + estrela (36): todos os cartões pedem a mesma largura


class ToolCard(tk.Canvas):
    """
    Cartão clicável de uma ferramenta, com estrela de favorito.

    Desenhado num único Canvas: com dezenas de cartões, montar cada um com moldura, rótulos
    e botão do CustomTkinter deixava a abertura da tela inicial vários segundos mais lenta.
    """

    _STAR_BOX = 24
    _STAR_MARGIN = 6

    def __init__(self, master, tool: ToolSpec, on_open, on_favorite, favorite: bool):
        super().__init__(master, highlightthickness=0, bd=0, cursor="hand2")
        self.tool = tool
        self._on_open, self._on_favorite = on_open, on_favorite
        self._favorite = favorite
        self._hover = self._star_hover = False
        self._scaling = ctk.ScalingTracker.get_widget_scaling(master)
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", lambda event: self._set_hover(True, self._in_star(event.x, event.y)))
        self.bind("<Leave>", lambda _event: self._set_hover(False, False))
        ctk.AppearanceModeTracker.add(self._on_appearance, self)
        ctk.ScalingTracker.add_widget(self._on_scaling, self)
        self._draw()

    def set_favorite(self, favorite: bool) -> None:
        self._favorite = favorite
        self._draw()

    def destroy(self) -> None:
        ctk.AppearanceModeTracker.remove(self._on_appearance)
        ctk.ScalingTracker.remove_widget(self._on_scaling, self)
        super().destroy()

    def _on_appearance(self, _mode: str) -> None:
        self._draw()

    def _on_scaling(self, widget_scaling: float, _window_scaling: float) -> None:
        self._scaling = widget_scaling
        self._draw()

    def _px(self, value: float) -> int:
        return round(value * self._scaling)

    def _draw(self) -> None:
        color = theme.color
        width, height = self._px(theme.CARD_WIDTH), self._px(theme.CARD_HEIGHT)
        self.configure(width=width, height=height, bg=color(theme.BACKGROUND))
        self.delete("all")
        fill, border = (theme.HOVER, theme.ACCENT) if self._hover else (theme.SURFACE, theme.BORDER)
        self.create_image(0, 0, anchor="nw", image=icons.rounded_photo(width, height, self._px(12), color(fill), color(border), max(1, self._px(1))))
        self.create_image(self._px(12), height // 2, anchor="w", image=icons.tile_photo(self.tool.icon, self.tool.color, self._px(42)))
        text_x, text_width = self._px(64), self._px(_TEXT_WIDTH)
        self.create_text(text_x, self._px(24), anchor="w", text=self.tool.name, width=text_width, fill=color(theme.TEXT), font=theme.font(13, "bold").create_scaled_tuple(self._scaling))
        self.create_text(text_x, self._px(37), anchor="nw", text=self.tool.description, width=text_width, fill=color(theme.TEXT_MUTED), font=theme.font(11).create_scaled_tuple(self._scaling))
        box, x0, y0 = self._px(self._STAR_BOX), width - self._px(self._STAR_MARGIN + self._STAR_BOX), self._px(self._STAR_MARGIN)
        if self._star_hover:
            self.create_image(x0, y0, anchor="nw", image=icons.rounded_photo(box, box, self._px(6), color(theme.NEUTRAL_BUTTON_HOVER)))
        star = icons.icon_photo("star", color(("#F59E0B", "#FBBF24")), self._px(16)) if self._favorite else icons.icon_photo("star_outline", color(theme.BORDER), self._px(16))
        self.create_image(x0 + box // 2, y0 + box // 2, image=star)

    def _in_star(self, x: int, y: int) -> bool:
        x0, y0 = int(self.cget("width")) - self._px(self._STAR_MARGIN + self._STAR_BOX), self._px(self._STAR_MARGIN)
        return x0 <= x <= x0 + self._px(self._STAR_BOX) and y0 <= y <= y0 + self._px(self._STAR_BOX)

    def _set_hover(self, hover: bool, star_hover: bool) -> None:
        if (hover, star_hover) != (self._hover, self._star_hover):
            self._hover, self._star_hover = hover, star_hover
            self._draw()

    def _click(self, event) -> None:
        if self._in_star(event.x, event.y):
            self.set_favorite(self._on_favorite(self.tool))
        else:
            self._on_open(self.tool)


class HomePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.view = "all"
        self._groups: List[Tuple[str, Sequence[ToolSpec]]] = []
        self._layout_key: Tuple = ()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=theme.PAD * 2, pady=(theme.PAD * 1.5, theme.PAD))
        top.grid_columnconfigure(0, weight=1)
        self._title = ctk.CTkLabel(top, text="", font=theme.font(26, "bold"), text_color=theme.TEXT, anchor="w")
        self._title.grid(row=0, column=0, sticky="w")
        self._subtitle = ctk.CTkLabel(top, text="", font=theme.font(13), text_color=theme.TEXT_MUTED, anchor="w")
        self._subtitle.grid(row=1, column=0, sticky="w")
        search = ctk.CTkFrame(top, fg_color=theme.SURFACE, corner_radius=20, border_width=1, border_color=theme.BORDER)
        search.grid(row=0, column=1, rowspan=2, sticky="e")
        ctk.CTkLabel(search, text="", image=icons.icon("search", 16, theme.TEXT_MUTED)).pack(side="left", padx=(12, 4))
        self.search = ctk.CTkEntry(search, placeholder_text="Pesquisar ferramenta  (Ctrl+F)", width=300, height=36, border_width=0, fg_color="transparent", font=theme.font(13))
        self.search.pack(side="left", padx=(0, 12))
        self.search.bind("<KeyRelease>", lambda _event: self.refresh())
        self.search.bind("<Return>", self._open_first)
        self.search.bind("<Escape>", lambda _event: self.clear_search())

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=1, column=0, sticky="nsew", padx=(theme.PAD * 2 - 6, theme.PAD))
        self._cards: Dict[str, ToolCard] = {tool.id: ToolCard(self._scroll, tool, self._open, self._toggle_favorite, app.prefs.is_favorite(tool.id)) for tool in all_tools()}
        self._extras: List[ctk.CTkBaseClass] = []
        self.bind("<Configure>", lambda _event: self._relayout(), add="+")

    # ------------------------------------------------------------------ navegação
    def show(self, view: str) -> None:
        self.view = view
        self.clear_search(refresh=False)
        self.refresh()

    def clear_search(self, refresh: bool = True) -> None:
        theme.set_entry_text(self.search, "")
        if refresh:
            self.refresh()

    def focus_search(self) -> None:
        self.search.focus_set()

    def refresh(self) -> None:
        title, subtitle, groups = self._content()
        self._title.configure(text=title)
        self._subtitle.configure(text=subtitle)
        self._groups = groups
        self._layout_key = ()
        self._relayout()

    def _content(self) -> Tuple[str, str, List[Tuple[str, Sequence[ToolSpec]]]]:
        query = self.search.get().strip()
        tools = all_tools()
        if query:
            found = [tool for tool in tools if tool.matches(query)]
            return f"Resultados para “{query}”", f"{len(found)} ferramenta(s)", [("", found)]
        if self.view == "favorites":
            favorites = [tools_by_id()[tool_id] for tool_id in self.app.prefs.favorites if tool_id in tools_by_id()]
            return "Favoritas", "Clique na estrela de qualquer ferramenta para fixá-la aqui.", [("", favorites)]
        if self.view == "recent":
            recent = [tools_by_id()[tool_id] for tool_id in self.app.prefs.recent if tool_id in tools_by_id()]
            return "Usadas recentemente", "As últimas ferramentas abertas.", [("", recent)]
        if self.view.startswith("cat:"):
            category = CATEGORY_BY_ID[self.view[4:]]
            items = [tool for tool in tools if tool.category == category.id]
            return category.label, f"{len(items)} ferramentas", [("", items)]
        groups = [(category.label, [tool for tool in tools if tool.category == category.id]) for category in CATEGORIES]
        return "Todas as ferramentas", f"{len(tools)} ferramentas offline — seus arquivos não saem do computador.", groups

    def _relayout(self) -> None:
        scaling = ctk.ScalingTracker.get_widget_scaling(self)
        available = self.winfo_width() - (theme.PAD * 3 + 24) * scaling
        columns = max(1, int(available // ((theme.CARD_WIDTH + _CARD_GAP) * scaling)))
        key = (columns, id(self._groups))
        if key == self._layout_key:
            return
        self._layout_key = key
        for card in self._cards.values():
            card.grid_forget()
        for widget in self._extras:
            widget.destroy()
        self._extras.clear()
        # o Canvas do Tk, ao contrário dos widgets CTk, não escala o espaçamento sozinho
        padx, pady = round(_CARD_GAP / 2 * scaling), round(_CARD_GAP_Y / 2 * scaling)
        row = 0
        for title, tools in self._groups:
            if title:
                header = ctk.CTkLabel(self._scroll, text=title.upper(), font=theme.font(12, "bold"), text_color=theme.TEXT_MUTED, anchor="w")
                header.grid(row=row, column=0, columnspan=columns, sticky="w", padx=6, pady=(14 if row else 0, 6))
                self._extras.append(header)
                row += 1
            for index, tool in enumerate(tools):
                self._cards[tool.id].grid(row=row + index // columns, column=index % columns, padx=padx, pady=pady, sticky="nw")
            row += -(-len(tools) // columns)
        if not any(tools for _, tools in self._groups):
            empty = ctk.CTkLabel(self._scroll, text="Nada por aqui ainda.", font=theme.font(14), text_color=theme.TEXT_MUTED)
            empty.grid(row=0, column=0, padx=8, pady=24, sticky="w")
            self._extras.append(empty)
        self._scroll._parent_canvas.yview_moveto(0)

    # ------------------------------------------------------------------ ações
    def _open(self, tool: ToolSpec) -> None:
        self.app.open_tool(tool.id)

    def _open_first(self, _event=None) -> None:
        for _, tools in self._groups:
            if tools:
                self._open(tools[0])
                return

    def _toggle_favorite(self, tool: ToolSpec) -> bool:
        favorite = self.app.prefs.toggle_favorite(tool.id)
        if self.view == "favorites" and not self.search.get().strip():
            self.after(10, self.refresh)
        return favorite

    def sync_favorites(self) -> None:
        for tool_id, card in self._cards.items():
            card.set_favorite(self.app.prefs.is_favorite(tool_id))
