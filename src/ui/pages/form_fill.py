"""Preenchimento de formulários PDF: lista os campos do arquivo e salva uma cópia preenchida."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional, Sequence

import customtkinter as ctk

from ...domain.tool import PDF_TYPES, ToolSpec
from ...services.pdf.forms import FieldValue, FormField, fill_form, read_fields
from ...utils.exceptions import PDF26Error
from .. import icons, theme
from ..runner import JobRunner
from ..system import describe_error, open_path
from ..widgets.dnd import enable_drop
from ..widgets.header import PageHeader

_KIND_LABELS = {"text": "Texto", "checkbox": "Caixa de seleção", "radio": "Opção", "choice": "Lista"}
_NONE = "(nenhuma)"


class FormFillPage(ctk.CTkFrame):
    def __init__(self, master, app, tool: ToolSpec, files: Sequence[Path] = ()):
        super().__init__(master, fg_color="transparent")
        self.app, self.tool = app, tool
        self.runner = JobRunner(self)
        self.path: Optional[Path] = None
        self._getters: Dict[str, Callable[[], FieldValue]] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        PageHeader(self, tool, app.show_home, app.prefs.is_favorite(tool.id), lambda: app.toggle_favorite(tool.id)).grid(
            row=0, column=0, sticky="ew", padx=theme.PAD * 2, pady=(theme.PAD * 1.5, theme.GAP)
        )

        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        bar.grid(row=1, column=0, sticky="ew", padx=theme.PAD * 2, pady=(0, theme.GAP))
        bar.grid_columnconfigure(1, weight=1)
        theme.neutral_button(bar, "Abrir PDF", self._browse, width=110, image=icons.icon("folder", 14)).grid(row=0, column=0, padx=8, pady=8)
        self._file_label = ctk.CTkLabel(bar, text="Nenhum arquivo", font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="w")
        self._file_label.grid(row=0, column=1, sticky="ew")

        self._fields = ctk.CTkScrollableFrame(self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        self._fields.grid(row=2, column=0, sticky="nsew", padx=theme.PAD * 2)
        self._fields.grid_columnconfigure(1, weight=1)
        enable_drop(self._fields, lambda paths: self.open(paths[0]) if paths else None)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=theme.PAD * 2, pady=theme.PAD)
        footer.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(footer, text="", font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self._flatten = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(footer, text="Achatar (impedir alterações depois)", variable=self._flatten, font=theme.font(12), fg_color=theme.ACCENT).grid(row=0, column=1, padx=theme.PAD)
        self.save_button = theme.primary_button(footer, "Salvar preenchido…", self.run, width=180, height=40)
        self.save_button.grid(row=0, column=2)
        self._message("Abra um PDF com campos de formulário (ou arraste para cá).")
        if files:
            self.after(50, lambda: self.open(Path(files[0])))

    def _browse(self) -> None:
        name = filedialog.askopenfilename(parent=self, title="Abrir formulário PDF", filetypes=list(PDF_TYPES))
        if name:
            self.open(Path(name))

    def open(self, path: Path) -> None:
        try:
            fields = read_fields(path)
        except PDF26Error as error:
            messagebox.showerror("PDF26", error.message, parent=self)
            return
        self.path = path
        self._file_label.configure(text=str(path), text_color=theme.TEXT)
        self._build_fields(fields)

    def _message(self, text: str) -> None:
        for child in self._fields.winfo_children():
            child.destroy()
        ctk.CTkLabel(self._fields, text=text, font=theme.font(14), text_color=theme.TEXT_MUTED).grid(row=0, column=0, columnspan=3, padx=24, pady=48)

    def _build_fields(self, fields: List[FormField]) -> None:
        self._getters.clear()
        if not fields:
            self._message("Este PDF não possui campos de formulário editáveis.")
            self.status.configure(text="")
            return
        for child in self._fields.winfo_children():
            child.destroy()
        for row, field in enumerate(fields):
            ctk.CTkLabel(self._fields, text=field.name, font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w").grid(row=row, column=0, sticky="nw", padx=(16, 12), pady=8)
            self._getters[field.name] = self._field_widget(field, row)
            ctk.CTkLabel(self._fields, text=f"{_KIND_LABELS[field.kind]} · pág. {field.page + 1}", font=theme.font(11), text_color=theme.TEXT_MUTED).grid(
                row=row, column=2, sticky="ne", padx=16, pady=10
            )
        self.status.configure(text=f"{len(fields)} campo(s) encontrado(s).")

    def _field_widget(self, field: FormField, row: int) -> Callable[[], FieldValue]:
        if field.kind == "checkbox":
            var = tk.BooleanVar(value=bool(field.value))
            ctk.CTkCheckBox(self._fields, text="", variable=var, fg_color=theme.ACCENT).grid(row=row, column=1, sticky="w", pady=8)
            return var.get
        if field.kind in ("choice", "radio"):
            values = ([_NONE] if field.kind == "radio" else []) + (field.choices or [""])
            menu = ctk.CTkOptionMenu(self._fields, values=values, width=280, fg_color=theme.SURFACE_ALT, button_color=theme.NEUTRAL_BUTTON_HOVER, text_color=theme.TEXT, font=theme.font(12))
            menu.set(str(field.value) if field.value in values else values[0])
            menu.grid(row=row, column=1, sticky="w", pady=8)
            return lambda: "" if menu.get() == _NONE else menu.get()
        if field.multiline:
            box = ctk.CTkTextbox(self._fields, height=70, font=theme.font(12), border_width=1, border_color=theme.BORDER)
            box.insert("1.0", str(field.value))
            box.grid(row=row, column=1, sticky="ew", pady=8)
            return lambda: box.get("1.0", "end-1c")
        entry = ctk.CTkEntry(self._fields, font=theme.font(12))
        theme.set_entry_text(entry, str(field.value))
        entry.grid(row=row, column=1, sticky="ew", pady=8)
        return entry.get

    def run(self) -> None:
        if not self.path or not self._getters or self.runner.running:
            return
        name = filedialog.asksaveasfilename(
            parent=self, title="Salvar formulário preenchido", defaultextension=".pdf", filetypes=list(PDF_TYPES), initialdir=str(self.path.parent), initialfile=f"{self.path.stem}_preenchido.pdf"
        )
        if not name:
            return
        values = {key: getter() for key, getter in self._getters.items()}
        self.save_button.configure(state="disabled")
        self.status.configure(text="Salvando…", text_color=theme.TEXT_MUTED)
        self.runner.start(lambda job: fill_form(job, self.path, values, flatten=self._flatten.get(), output=Path(name)), on_success=self._saved, on_error=self._failed)

    def _saved(self, result) -> None:
        self.save_button.configure(state="normal")
        target = result.files[0]
        self.status.configure(text=f"{result.message} Salvo em {target}", text_color=theme.SUCCESS)
        if messagebox.askyesno("PDF26", "Formulário salvo. Abrir o arquivo?", parent=self):
            open_path(target)

    def _failed(self, error: BaseException) -> None:
        self.save_button.configure(state="normal")
        self.status.configure(text="Falha ao salvar.", text_color=theme.DANGER)
        messagebox.showerror("PDF26", describe_error(error), parent=self)

    def can_leave(self) -> bool:
        return not self.runner.running
