"""Lista de arquivos de entrada: adicionar, arrastar e soltar, reordenar e remover."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional, Sequence

import customtkinter as ctk
import pymupdf

from ...domain.tool import FileInput
from ...services.pdf.common import human_size
from .. import icons, theme
from .dnd import enable_drop


class FileList(ctk.CTkFrame):
    """Painel com a lista ordenada de arquivos de uma ferramenta."""

    def __init__(self, master, spec: FileInput, on_change: Optional[Callable[[List[Path]], None]] = None):
        super().__init__(master, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        self.spec = spec
        self._files: List[Path] = []
        self._on_change = on_change
        self._info_cache: Dict[Path, str] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD - 4, theme.GAP))
        header.grid_columnconfigure(0, weight=1)
        self._title = ctk.CTkLabel(header, text=spec.label, font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w")
        self._title.grid(row=0, column=0, sticky="w")
        theme.neutral_button(header, "Limpar", self.clear, width=70, image=icons.icon("trash", 14)).grid(row=0, column=1, padx=(theme.GAP, 0))
        theme.neutral_button(header, "Pasta", self._add_folder, width=70, image=icons.icon("folder", 14)).grid(row=0, column=2, padx=(theme.GAP, 0))
        theme.primary_button(header, "Adicionar", self._browse, width=110, image=icons.icon("plus", 14, ("#FFFFFF", "#FFFFFF"))).grid(row=0, column=3, padx=(theme.GAP, 0))

        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self._body.grid_columnconfigure(0, weight=1)
        self._render()

    @property
    def files(self) -> List[Path]:
        return list(self._files)

    def add(self, paths: Sequence[Path]) -> None:
        accepted = [Path(path) for path in paths if Path(path).is_file() and self._accepts(Path(path))]
        rejected = len(paths) - len(accepted)
        if self.spec.max_files == 1 and accepted:
            self._files = [accepted[0]]
        else:
            self._files += [path for path in accepted if path not in self._files]
            if self.spec.max_files and len(self._files) > self.spec.max_files:
                self._files = self._files[: self.spec.max_files]
                messagebox.showinfo("PDF26", f"Esta ferramenta aceita no máximo {self.spec.max_files} arquivos.")
        if rejected:
            messagebox.showwarning("PDF26", f"{rejected} arquivo(s) ignorado(s): formato não suportado por esta ferramenta.")
        self._changed()

    def clear(self) -> None:
        self._files.clear()
        self._changed()

    def _accepts(self, path: Path) -> bool:
        return not self.spec.extensions or path.suffix.lower() in self.spec.extensions

    def _browse(self) -> None:
        names = filedialog.askopenfilenames(parent=self, title="Selecionar arquivos", filetypes=list(self.spec.filetypes) + [("Todos os arquivos", "*.*")])
        if names:
            self.add([Path(name) for name in names])

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Adicionar todos os arquivos de uma pasta")
        if folder:
            self.add(sorted(path for path in Path(folder).iterdir() if path.is_file() and self._accepts(path)))

    def _move(self, index: int, delta: int) -> None:
        target = index + delta
        if 0 <= target < len(self._files):
            self._files[index], self._files[target] = self._files[target], self._files[index]
            self._changed()

    def _remove(self, index: int) -> None:
        del self._files[index]
        self._changed()

    def _changed(self) -> None:
        self._render()
        if self._on_change:
            self._on_change(self.files)

    def _info(self, path: Path) -> str:
        if path not in self._info_cache:
            size = human_size(path.stat().st_size) if path.exists() else "?"
            pages = ""
            if path.suffix.lower() == ".pdf":
                try:
                    with pymupdf.open(path) as doc:
                        pages = "protegido · " if doc.needs_pass else f"{doc.page_count} pág. · "
                except Exception:
                    pages = "inválido · "
            self._info_cache[path] = f"{pages}{size}"
        return self._info_cache[path]

    def _render(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()
        count = len(self._files)
        self._title.configure(text=f"{self.spec.label} ({count})" if count else self.spec.label)
        if not count:
            self._empty_state()
        for index, path in enumerate(self._files):
            self._row(index, path, count)
        enable_drop(self, self.add)

    def _empty_state(self) -> None:
        box = ctk.CTkFrame(self._body, fg_color=theme.SURFACE_ALT, corner_radius=theme.RADIUS, border_width=2, border_color=theme.BORDER)
        box.grid(row=0, column=0, sticky="ew", padx=8, pady=8, ipady=36)
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text="", image=icons.icon("file", 40, theme.TEXT_MUTED)).grid(row=0, column=0, pady=(18, 6))
        ctk.CTkLabel(box, text="Arraste arquivos para cá", font=theme.font(15, "bold"), text_color=theme.TEXT).grid(row=1, column=0)
        types = ", ".join(ext.lstrip(".").upper() for ext in self.spec.extensions[:8]) + ("…" if len(self.spec.extensions) > 8 else "")
        ctk.CTkLabel(box, text=f"ou clique em Adicionar  ·  {types}", font=theme.font(12), text_color=theme.TEXT_MUTED).grid(row=2, column=0, pady=(2, 12))
        theme.primary_button(box, "Escolher arquivos", self._browse, width=170).grid(row=3, column=0, pady=(0, 12))

    def _row(self, index: int, path: Path, count: int) -> None:
        row = ctk.CTkFrame(self._body, fg_color=theme.SURFACE_ALT, corner_radius=8)
        row.grid(row=index, column=0, sticky="ew", padx=4, pady=3)
        row.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(row, text=f"{index + 1}", width=28, font=theme.font(12, "bold"), text_color=theme.TEXT_MUTED).grid(row=0, column=0, rowspan=2, padx=(8, 0))
        ctk.CTkLabel(row, text="", image=icons.icon("file", 20, theme.TEXT_MUTED)).grid(row=0, column=1, rowspan=2, padx=(4, 8), pady=8)
        name = path.name if len(path.name) <= 70 else path.name[:67] + "…"
        ctk.CTkLabel(row, text=name, font=theme.font(13), text_color=theme.TEXT, anchor="w").grid(row=0, column=2, sticky="sw", pady=(6, 0))
        ctk.CTkLabel(row, text=f"{self._info(path)}  ·  {path.parent}", font=theme.font(11), text_color=theme.TEXT_MUTED, anchor="w").grid(row=1, column=2, sticky="nw", pady=(0, 6))
        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=3, rowspan=2, padx=6)
        if count > 1:
            theme.icon_button(actions, icons.icon("up", 16), lambda i=index: self._move(i, -1), "Mover para cima", state="normal" if index else "disabled").pack(side="left")
            theme.icon_button(actions, icons.icon("down", 16), lambda i=index: self._move(i, 1), "Mover para baixo", state="normal" if index < count - 1 else "disabled").pack(side="left")
        theme.icon_button(actions, icons.icon("close", 16, theme.DANGER), lambda i=index: self._remove(i), "Remover da lista").pack(side="left")
