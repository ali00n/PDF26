"""Janela principal do PDF26: barra lateral, navegação entre telas e atalhos de teclado."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Optional, Sequence

import customtkinter as ctk

from .. import __version__
from ..config.app_config import AppConfig, config_dir
from ..config.catalog import all_tools, tools_by_id
from ..domain.tool import CATEGORIES
from ..services.pdf import externals
from ..utils.logger import get_logger
from . import icons, theme
from .widgets import dnd

logger = get_logger(__name__)

APP_ID = "PDF26.Desktop"


class SidebarItem(ctk.CTkFrame):
    """Item de navegação: ícone, rótulo e contador alinhado à direita."""

    def __init__(self, master, text: str, image, command, trailing: str = ""):
        super().__init__(master, height=36, corner_radius=8, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        self._active = False
        self._command = command
        ctk.CTkLabel(self, text="", image=image, width=20).grid(row=0, column=0, padx=(10, 8), pady=7)
        self._label = ctk.CTkLabel(self, text=text, font=theme.font(13), text_color=theme.TEXT, anchor="w")
        self._label.grid(row=0, column=1, sticky="w")
        self._count = ctk.CTkLabel(self, text=trailing, font=theme.font(11), text_color=theme.TEXT_MUTED, width=24)
        self._count.grid(row=0, column=2, padx=(4, 10))
        for widget in (self, *self.winfo_children()):
            widget.bind("<Button-1>", lambda _event: self._command(), add="+")
            widget.bind("<Enter>", lambda _event: self._paint(hover=True), add="+")
            widget.bind("<Leave>", lambda _event: self._paint(hover=False), add="+")
            widget.configure(cursor="hand2")

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint(hover=False)

    def _paint(self, hover: bool) -> None:
        background = theme.ACCENT_SOFT if self._active else (theme.HOVER if hover else "transparent")
        self.configure(fg_color=background)
        self._label.configure(text_color=theme.ACCENT if self._active else theme.TEXT, font=theme.font(13, "bold" if self._active else "normal"))


class Sidebar(ctk.CTkFrame):
    def __init__(self, master, app: "PDF26App"):
        super().__init__(master, width=theme.SIDEBAR_WIDTH, corner_radius=0, fg_color=theme.SURFACE, border_width=0)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.app = app
        self.buttons = {}

        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD + 4, theme.PAD))
        ctk.CTkLabel(brand, text="", image=icons.tool_icon("26", theme.ACCENT[0], 40)).pack(side="left")
        names = ctk.CTkFrame(brand, fg_color="transparent")
        names.pack(side="left", padx=10)
        ctk.CTkLabel(names, text="PDF26", font=theme.font(20, "bold"), text_color=theme.TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(names, text="Caixa de ferramentas PDF", font=theme.font(11), text_color=theme.TEXT_MUTED, anchor="w").pack(anchor="w")

        row = 1
        for view, label, icon_name in (("all", "Todas as ferramentas", "grid"), ("favorites", "Favoritas", "star_outline"), ("recent", "Recentes", "clock")):
            self._add(row, view, label, icons.icon(icon_name, 16))
            row += 1
        ctk.CTkLabel(self, text="CATEGORIAS", font=theme.font(11, "bold"), text_color=theme.TEXT_MUTED, anchor="w").grid(row=row, column=0, sticky="ew", padx=theme.PAD + 6, pady=(theme.PAD, 4))
        row += 1
        counts = {category.id: sum(1 for tool in all_tools() if tool.category == category.id) for category in CATEGORIES}
        for category in CATEGORIES:
            self._add(row, f"cat:{category.id}", category.label, icons.dot(category.color, 10), str(counts[category.id]))
            row += 1

        self.grid_rowconfigure(row, weight=1)
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=row + 1, column=0, sticky="ew", padx=theme.PAD, pady=theme.PAD)
        bottom.grid_columnconfigure(0, weight=1)
        self._theme = theme.segmented(bottom, ["Claro", "Escuro", "Sistema"], command=app.set_appearance, font_size=11)
        self._theme.set({"light": "Claro", "dark": "Escuro"}.get(app.prefs.appearance, "Sistema"))
        self._theme.grid(row=0, column=0, columnspan=2, sticky="ew")
        theme.neutral_button(bottom, "Configurações", app.open_settings, image=icons.icon("gear", 15), width=150).grid(row=1, column=0, sticky="w", pady=(theme.GAP, 0))
        ctk.CTkLabel(bottom, text=f"v{__version__}", font=theme.font(11), text_color=theme.TEXT_MUTED).grid(row=1, column=1, sticky="e", pady=(theme.GAP, 0))

    def _add(self, row: int, view: str, label: str, image, trailing: str = "") -> None:
        button = SidebarItem(self, label, image, lambda v=view: self.app.show_home(v), trailing)
        button.grid(row=row, column=0, sticky="ew", padx=10, pady=1)
        self.buttons[view] = button

    def highlight(self, view: Optional[str]) -> None:
        for key, button in self.buttons.items():
            button.set_active(key == view)


class PDF26App(ctk.CTk):
    def __init__(self, initial_files: Sequence[Path] = ()):
        _set_windows_app_id()
        self.prefs = AppConfig.load()
        ctk.set_appearance_mode(self.prefs.appearance)
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=theme.BACKGROUND)
        externals.configure(self.prefs.ghostscript_path, self.prefs.soffice_path, self.prefs.tessdata_path)
        dnd.install(self)

        self.title("PDF26 — Ferramentas PDF")
        self.geometry(self._initial_geometry())
        self.minsize(1080, 700)
        self._set_icon()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = Sidebar(self, self)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=theme.BORDER).grid(row=0, column=0, sticky="nse")
        self.content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        from .pages.home import HomePage

        self.home = HomePage(self.content, self)
        self.page: Optional[ctk.CTkFrame] = None
        self.show_home("all")

        self.bind("<Control-f>", self._focus_search)
        self.bind("<Escape>", self._escape)
        self.bind("<Control-Return>", self._run_current)
        self.bind("<Delete>", lambda _event: self._dispatch("on_key_delete"))
        self.bind("<Control-z>", lambda _event: self._dispatch("on_key_undo"))
        self.bind("<Control-o>", self._open_shortcut)
        self.protocol("WM_DELETE_WINDOW", self.close)
        if initial_files:
            self.after(300, lambda: self.open_tool("reader", initial_files[:1]))

    # ------------------------------------------------------------------ navegação
    def show_home(self, view: str = "all") -> None:
        if not self._leave_page():
            return
        self.home.grid(row=0, column=0, sticky="nsew")
        self.home.sync_favorites()
        self.home.show(view)
        self.sidebar.highlight(view)

    def open_tool(self, tool_id: str, files: Sequence[Path] = ()) -> None:
        tool = tools_by_id()[tool_id]
        if not self._leave_page():
            return
        self.prefs.register_use(tool_id)
        page_class = self._page_class(tool.page)
        self.home.grid_remove()
        self.sidebar.highlight(None)
        self.page = page_class(self.content, self, tool, list(files))
        self.page.grid(row=0, column=0, sticky="nsew")

    @staticmethod
    def _page_class(kind: str):
        if kind in ("reader", "editor"):
            from .pages.reader import ReaderPage

            return ReaderPage
        if kind == "organizer":
            from .pages.organizer import OrganizerPage

            return OrganizerPage
        if kind == "form":
            from .pages.form_fill import FormFillPage

            return FormFillPage
        from .pages.tool_page import ToolPage

        return ToolPage

    def _leave_page(self) -> bool:
        if self.page is None:
            return True
        if hasattr(self.page, "can_leave") and not self.page.can_leave():
            return False
        self.page.destroy()
        self.page = None
        return True

    def toggle_favorite(self, tool_id: str) -> bool:
        return self.prefs.toggle_favorite(tool_id)

    # ------------------------------------------------------------------ ações globais
    def set_appearance(self, label: str) -> None:
        self.prefs.appearance = {"Claro": "light", "Escuro": "dark"}.get(label, "system")
        self.prefs.save()
        ctk.set_appearance_mode(self.prefs.appearance)
        if self.page is not None and hasattr(self.page, "on_appearance_change"):
            self.page.on_appearance_change()

    def open_settings(self) -> None:
        from .dialogs.settings_dialog import SettingsDialog

        if SettingsDialog(self, self.prefs).show():
            self.sidebar._theme.set({"light": "Claro", "dark": "Escuro"}.get(self.prefs.appearance, "Sistema"))
            if self.page is not None and hasattr(self.page, "on_appearance_change"):
                self.page.on_appearance_change()

    def _focus_search(self, _event=None) -> None:
        if self.page is None:
            self.home.focus_search()

    def _escape(self, _event=None) -> None:
        focused = self.focus_get()
        if self.page is not None and not isinstance(focused, (tk.Entry, tk.Text)):
            self.show_home(self.home.view)

    def _open_shortcut(self, _event=None) -> None:
        """Ctrl+O: no Leitor abre outro arquivo; nas demais telas abre o Leitor."""
        if hasattr(self.page, "choose_file"):
            self.page.choose_file()
        else:
            self.open_tool("reader")

    def _run_current(self, _event=None) -> None:
        self._dispatch("run", inside_text=True)

    def _dispatch(self, method: str, inside_text: bool = False) -> None:
        """Encaminha atalhos globais para a tela atual, se ela os implementar (Delete/Ctrl+Z não agem em campos de texto)."""
        handler = getattr(self.page, method, None) if self.page is not None else None
        if handler and (inside_text or not isinstance(self.focus_get(), (tk.Entry, tk.Text))):
            handler()

    def close(self) -> None:
        if self._leave_page():
            self.destroy()

    # ------------------------------------------------------------------ janela
    def _initial_geometry(self) -> str:
        width = min(1440, max(1100, int(self.winfo_screenwidth() * 0.8)))
        height = min(920, max(720, int(self.winfo_screenheight() * 0.82)))
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 3)
        return f"{width}x{height}+{x}+{y}"

    def _set_icon(self) -> None:
        image = icons.app_icon_image(256)
        try:
            if sys.platform == "win32":
                ico = config_dir() / "pdf26.ico"
                ico.parent.mkdir(parents=True, exist_ok=True)
                image.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
                self.iconbitmap(str(ico))
            else:
                from PIL import ImageTk

                self._icon_photo = ImageTk.PhotoImage(image.resize((64, 64)))
                self.iconphoto(True, self._icon_photo)
        except (OSError, tk.TclError) as error:
            logger.warning(f"Ícone da janela não aplicado: {error}")


def _set_windows_app_id() -> None:
    """Faz a barra de tarefas do Windows mostrar o ícone do PDF26 (e não o do Python)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass
