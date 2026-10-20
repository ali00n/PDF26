"""Configurações: tema, pastas padrão e programas externos (Ghostscript, LibreOffice, Tesseract)."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

import customtkinter as ctk

from ...config.app_config import AppConfig, config_dir
from ...services.pdf import externals
from ...utils.logger import LOG_DIR, get_logger
from .. import theme
from ..system import open_path
from .base import ModalDialog

logger = get_logger(__name__)

APPEARANCES = {"Sistema": "system", "Claro": "light", "Escuro": "dark"}


class SettingsDialog(ModalDialog):
    def __init__(self, master, config: AppConfig):
        super().__init__(master, "Configurações", width=640, height=560)
        self.config = config
        body = ctk.CTkScrollableFrame(self.body, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)

        self._section(body, 0, "Aparência")
        names = {value: name for name, value in APPEARANCES.items()}
        self._appearance = tk.StringVar(value=names.get(config.appearance, "Sistema"))
        theme.segmented(body, APPEARANCES, variable=self._appearance).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 12))

        self._section(body, 2, "Arquivos")
        self._default_dir = self._path_row(body, 3, "Pasta para arquivos criados do zero", config.default_dir, folder=True, status=config.default_dir)
        self._open_after = tk.BooleanVar(value=config.open_folder_after)
        ctk.CTkCheckBox(body, text="Abrir a pasta de destino ao concluir", variable=self._open_after, fg_color=theme.ACCENT).grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 12))

        self._section(body, 6, "Programas externos (opcionais)")
        ctk.CTkLabel(body, text="Deixe em branco para detectar automaticamente.", font=theme.font(11), text_color=theme.TEXT_MUTED).grid(row=7, column=0, columnspan=3, sticky="w")
        self._gs = self._path_row(body, 8, "Ghostscript (gswin64c.exe) — PDF/A e tons de cinza", config.ghostscript_path, status=externals.find_ghostscript())
        self._soffice = self._path_row(
            body, 10, "LibreOffice (soffice.exe) — Office para PDF", config.soffice_path, status=externals.find_soffice() or ("Microsoft Office" if externals.office_available() else None)
        )
        langs = ", ".join(externals.tesseract_languages())
        self._tessdata = self._path_row(
            body, 12, "Tesseract OCR (pasta tessdata)", config.tessdata_path, folder=True, status=f"{externals.find_tessdata()} [{langs}]" if externals.find_tessdata() else None
        )

        self._section(body, 14, "Diagnóstico")
        links = ctk.CTkFrame(body, fg_color="transparent")
        links.grid(row=15, column=0, columnspan=3, sticky="w")
        theme.neutral_button(links, "Abrir pasta de logs", lambda: open_path(LOG_DIR), width=150).pack(side="left")
        theme.neutral_button(links, "Abrir pasta de configuração", lambda: open_path(config_dir()), width=190).pack(side="left", padx=theme.GAP)
        self.add_buttons("Salvar")

    def _section(self, body, row: int, text: str) -> None:
        ctk.CTkLabel(body, text=text, font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w").grid(row=row, column=0, columnspan=3, sticky="w", pady=(8, 6))

    def _path_row(self, body, row: int, label: str, value: str, folder: bool = False, status=None) -> ctk.CTkEntry:
        ctk.CTkLabel(body, text=label, font=theme.font(12), text_color=theme.TEXT, anchor="w").grid(row=row, column=0, columnspan=3, sticky="w")
        entry = ctk.CTkEntry(body, placeholder_text=f"✓ detectado: {status}" if status else "✗ não encontrado", font=theme.font(12))
        if value:
            entry.insert(0, value)
        entry.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(2, 8))

        def browse():
            chosen = filedialog.askdirectory(parent=self) if folder else filedialog.askopenfilename(parent=self, filetypes=[("Programas", "*.exe"), ("Todos", "*.*")])
            if chosen:
                entry.delete(0, "end")
                entry.insert(0, chosen)

        theme.neutral_button(body, "Procurar…", browse, width=90).grid(row=row + 1, column=2, padx=(6, 0), pady=(2, 8))
        return entry

    def accept(self) -> None:
        self.config.appearance = APPEARANCES[self._appearance.get()]
        self.config.default_dir = self._default_dir.get().strip() or self.config.default_dir
        self.config.open_folder_after = bool(self._open_after.get())
        self.config.ghostscript_path = self._gs.get().strip()
        self.config.soffice_path = self._soffice.get().strip()
        self.config.tessdata_path = self._tessdata.get().strip()
        self.config.save()
        externals.configure(self.config.ghostscript_path, self.config.soffice_path, self.config.tessdata_path)
        ctk.set_appearance_mode(self.config.appearance)
        self.result = True
        self.destroy()
