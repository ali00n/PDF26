"""Tela inicial: grade de ferramentas com busca, favoritas, recentes e categorias."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import customtkinter as ctk

from ...config.catalog import all_tools, tools_by_id
from ...domain.tool import CATEGORIES, CATEGORY_BY_ID, ToolSpec
from .. import icons, theme

_CARD_GAP = 12
_TEXT_WIDTH = theme.CARD_WIDTH - 100  # ícone (64) + estrela (36): todos os cartões pedem a mesma largura


class ToolCard(ctk.CTkFrame):
    """Cartão clicável de uma ferramenta, com estrela de favorito."""

    def __init__(self, master, tool: ToolSpec, on_open, on_favorite, favorite: bool):
        super().__init__(master, width=theme.CARD_WIDTH, height=theme.CARD_HEIGHT, fg_color=theme.SURFACE, corner_radius=12, border_width=1, border_color=theme.BORDER)
        self.tool = tool
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure((0, 1), weight=1)
        self._on_open, self._on_favorite = on_open, on_favorite
        ctk.CTkLabel(self, text="", image=icons.tool_icon(tool.icon, tool.color, 42)).grid(row=0, column=0, rowspan=2, padx=(12, 10))
        ctk.CTkLabel(self, text=tool.name, width=_TEXT_WIDTH, font=theme.font(13, "bold"), text_color=theme.TEXT, anchor="w").grid(row=0, column=1, sticky="sw", pady=(10, 0))
        ctk.CTkLabel(self, text=tool.description, width=_TEXT_WIDTH, font=theme.font(11), text_color=theme.TEXT_MUTED, anchor="nw", justify="left", wraplength=_TEXT_WIDTH).grid(
            row=1, column=1, sticky="nw", pady=(0, 8)
        )
        self._star = ctk.CTkButton(self, text="", width=24, height=24, fg_color="transparent", hover_color=theme.NEUTRAL_BUTTON_HOVER, command=self._toggle_favorite)
        self._star.grid(row=0, column=2, sticky="ne", padx=6, pady=6)
        self.set_favorite(favorite)
        for widget in [self] + [child for child in self.winfo_children() if child is not self._star]:
            widget.bind("<Button-1>", lambda _event: self._on_open(self.tool), add="+")
            widget.bind("<Enter>", lambda _event: self._hover(True), add="+")
            widget.bind("<Leave>", self._leave, add="+")
            widget.configure(cursor="hand2")

    def set_favorite(self, favorite: bool) -> None:
        image = icons.icon("star", 16, ("#F59E0B", "#FBBF24")) if favorite else icons.icon("star_outline", 16, theme.BORDER)
        self._star.configure(image=image)

    def _toggle_favorite(self) -> None:
        self.set_favorite(self._on_favorite(self.tool))

    def _hover(self, active: bool) -> None:
        self.configure(fg_color=theme.HOVER if active else theme.SURFACE, border_color=theme.ACCENT if active else theme.BORDER)

    def _leave(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self:
            widget = widget.master
        if widget is None:
            self._hover(False)


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
        row = 0
        for title, tools in self._groups:
            if title:
                header = ctk.CTkLabel(self._scroll, text=title.upper(), font=theme.font(12, "bold"), text_color=theme.TEXT_MUTED, anchor="w")
                header.grid(row=row, column=0, columnspan=columns, sticky="w", padx=6, pady=(14 if row else 0, 6))
                self._extras.append(header)
                row += 1
            for index, tool in enumerate(tools):
                self._cards[tool.id].grid(row=row + index // columns, column=index % columns, padx=_CARD_GAP // 2, pady=_CARD_GAP // 2, sticky="nw")
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
