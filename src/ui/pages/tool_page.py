"""Tela genérica de ferramenta: arquivos de entrada, opções do catálogo, destino, execução e resultado."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional, Sequence

import customtkinter as ctk

from ...domain.job import ToolResult
from ...domain.tool import ToolSpec
from ...utils.exceptions import PDF26Error, OperationCancelledError, ValidationError
from .. import icons, theme
from ..runner import JobRunner
from ..system import describe_error, open_path, reveal
from ..widgets.file_list import FileList
from ..widgets.header import PageHeader
from ..widgets.option_form import OptionForm

_MAX_LISTED_FILES = 6


class OutputSelector(ctk.CTkFrame):
    """Destino dos arquivos: mesma pasta da entrada ou pasta escolhida (lembrado entre usos)."""

    def __init__(self, master, prefs, has_inputs: bool):
        super().__init__(master, fg_color="transparent")
        self.prefs, self.has_inputs = prefs, has_inputs
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text="Salvar resultado em", font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self._mode = ctk.StringVar(value="same" if has_inputs and prefs.output_mode == "same" else "folder")
        if has_inputs:
            switch = theme.segmented(self, ["Mesma pasta", "Outra pasta"], command=self._mode_changed)
            switch.grid(row=1, column=0, columnspan=2, sticky="w")
            switch.set("Mesma pasta" if self._mode.get() == "same" else "Outra pasta")
        self._entry = ctk.CTkEntry(self, font=theme.font(12))
        self._entry.insert(0, (prefs.output_dir if has_inputs else prefs.default_dir) or prefs.default_dir)
        self._browse = theme.neutral_button(self, "Escolher…", self._choose, width=90)
        self._refresh()

    def _mode_changed(self, label: str) -> None:
        self._mode.set("same" if label == "Mesma pasta" else "folder")
        self.prefs.output_mode = self._mode.get()
        self.prefs.save()
        self._refresh()

    def _refresh(self) -> None:
        if self._mode.get() == "folder":
            self._entry.grid(row=2, column=0, sticky="ew", pady=(6, 0))
            self._browse.grid(row=2, column=1, padx=(6, 0), pady=(6, 0))
        else:
            self._entry.grid_remove()
            self._browse.grid_remove()

    def _choose(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=self._entry.get() or None)
        if folder:
            self._entry.delete(0, "end")
            self._entry.insert(0, folder)

    def output_dir(self) -> Optional[Path]:
        """None = ao lado do arquivo de entrada."""
        if self._mode.get() == "same":
            return None
        folder = self._entry.get().strip()
        if not folder:
            raise ValidationError("Escolha a pasta de destino.", field="output_dir")
        if self.has_inputs:
            self.prefs.output_dir = folder
        else:
            self.prefs.default_dir = folder
        self.prefs.save()
        return Path(folder)


class ToolPage(ctk.CTkFrame):
    def __init__(self, master, app, tool: ToolSpec, files: Sequence[Path] = ()):
        super().__init__(master, fg_color="transparent")
        self.app, self.tool = app, tool
        self.runner = JobRunner(self)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        PageHeader(self, tool, app.show_home, app.prefs.is_favorite(tool.id), lambda: app.toggle_favorite(tool.id)).grid(
            row=0, column=0, sticky="ew", padx=theme.PAD * 2, pady=(theme.PAD * 1.5, theme.PAD)
        )
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=theme.PAD * 2)
        body.grid_rowconfigure(0, weight=1)

        self.file_list: Optional[FileList] = None
        if tool.inputs:
            body.grid_columnconfigure(0, weight=3)
            body.grid_columnconfigure(1, weight=2, minsize=380)
            self.file_list = FileList(body, tool.inputs, on_change=self._files_changed)
            self.file_list.grid(row=0, column=0, sticky="nsew", padx=(0, theme.PAD))
            panel_column = 1
        else:
            body.grid_columnconfigure((0, 2), weight=1)
            body.grid_columnconfigure(1, weight=4, minsize=560)
            panel_column = 1
        panel = ctk.CTkFrame(body, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        panel.grid(row=0, column=panel_column, sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(panel, text="Opções", font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w").grid(row=0, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD - 4, 4))
        scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew", padx=6)
        scroll.grid_columnconfigure(0, weight=1)
        self.form = OptionForm(scroll, tool.options)
        self.form.grid(row=0, column=0, sticky="ew", padx=theme.GAP)
        if not tool.options:
            ctk.CTkLabel(scroll, text="Esta ferramenta não precisa de ajustes.", font=theme.font(12), text_color=theme.TEXT_MUTED).grid(row=1, column=0, sticky="w", padx=theme.GAP)
        ctk.CTkFrame(panel, height=1, fg_color=theme.BORDER).grid(row=2, column=0, sticky="ew")
        self.output = OutputSelector(panel, app.prefs, has_inputs=tool.inputs is not None)
        self.output.grid(row=3, column=0, sticky="ew", padx=theme.PAD, pady=theme.PAD - 4)

        self._build_footer()
        self.result_frame = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        if files and self.file_list:
            self.file_list.add(list(files))

    # ------------------------------------------------------------------ rodapé e execução
    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", padx=theme.PAD * 2, pady=theme.PAD)
        footer.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(footer, text=self._idle_hint(), font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self.progress = ctk.CTkProgressBar(footer, height=8, progress_color=theme.ACCENT)
        self.progress.set(0)
        self.cancel_button = theme.neutral_button(footer, "Cancelar", self.runner.cancel, width=100, height=40)
        self.run_button = theme.primary_button(footer, self.tool.run_label, self.run, width=170, height=40, image=icons.icon("check", 16, ("#FFFFFF", "#FFFFFF")))
        self.run_button.grid(row=0, column=2, rowspan=2, padx=(theme.GAP, 0))

    def _idle_hint(self) -> str:
        if self.tool.inputs:
            return "Adicione os arquivos, ajuste as opções e clique em " + self.tool.run_label + "  (Ctrl+Enter)."
        return "Preencha as opções e clique em " + self.tool.run_label + "  (Ctrl+Enter)."

    def _files_changed(self, files: List[Path]) -> None:
        self.result_frame.grid_forget()
        if self.tool.prefill and files:
            try:
                self.form.set_values(self.tool.prefill(files[0]))
            except PDF26Error as error:
                self._set_status(error.message, theme.WARNING)

    def run(self) -> None:
        if self.runner.running:
            return
        files = self.file_list.files if self.file_list else []
        spec = self.tool.inputs
        try:
            if spec and len(files) < spec.min_files:
                raise ValidationError(f"Adicione {'pelo menos ' if spec.min_files > 1 else ''}{spec.min_files} arquivo(s).", field="files")
            values = self.form.values()
            output_dir = self.output.output_dir()
        except ValidationError as error:
            self._set_status(error.message, theme.DANGER)
            return
        self.result_frame.grid_forget()
        self._set_running(True)
        self.runner.start(
            lambda job: self.tool.run(job, files, **values),
            on_success=self._succeeded,
            on_error=self._failed,
            on_progress=self._progress,
            output_dir=output_dir,
            fallback_dir=Path(self.app.prefs.default_dir),
        )

    def _set_running(self, running: bool) -> None:
        if running:
            self.progress.set(0)
            self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 0))
            self.cancel_button.grid(row=0, column=1, rowspan=2, padx=(theme.GAP, 0))
            self.run_button.configure(state="disabled")
            self._set_status("Processando…", theme.TEXT_MUTED)
        else:
            self.progress.grid_remove()
            self.cancel_button.grid_remove()
            self.run_button.configure(state="normal")

    def _progress(self, fraction: float, message: str) -> None:
        self.progress.set(fraction)
        if message:
            self._set_status(message, theme.TEXT_MUTED)

    def _set_status(self, text: str, color=theme.TEXT_MUTED) -> None:
        self.status.configure(text=text, text_color=color)

    def _succeeded(self, result: ToolResult) -> None:
        self._set_running(False)
        count = len(result.files)
        summary = result.message or (f"{count} arquivo(s) gerado(s)." if count else "Concluído.")
        self._set_status("Concluído." if summary == "Concluído." else f"Concluído — {summary}", theme.SUCCESS)
        self._show_result(result, summary)
        if count and self.app.prefs.open_folder_after:
            reveal(result.files[0])

    def _failed(self, error: BaseException) -> None:
        self._set_running(False)
        message = describe_error(error)
        self._set_status(message.splitlines()[0], theme.WARNING if isinstance(error, OperationCancelledError) else theme.DANGER)
        if not isinstance(error, OperationCancelledError):
            messagebox.showerror(self.tool.name, message, parent=self)

    # ------------------------------------------------------------------ resultado
    def _show_result(self, result: ToolResult, summary: str) -> None:
        frame = self.result_frame
        for child in frame.winfo_children():
            child.destroy()
        frame.grid(row=2, column=0, sticky="ew", padx=theme.PAD * 2, pady=(theme.PAD, 0))
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text="", image=icons.icon("check", 22, theme.SUCCESS)).grid(row=0, column=0, padx=(theme.PAD, 8), pady=(12, 4))
        ctk.CTkLabel(frame, text=summary, font=theme.font(14, "bold"), text_color=theme.TEXT, anchor="w").grid(row=0, column=1, sticky="w", pady=(12, 4))
        if result.files:
            actions = ctk.CTkFrame(frame, fg_color="transparent", width=1, height=1)
            actions.grid(row=0, column=2, padx=theme.PAD, pady=(12, 4))
            theme.neutral_button(actions, "Abrir pasta", lambda: reveal(result.files[0]), width=110, image=icons.icon("folder", 14)).pack(side="left")
            if len(result.files) == 1:
                theme.primary_button(actions, "Abrir arquivo", lambda: open_path(result.files[0]), width=130).pack(side="left", padx=(theme.GAP, 0))
        row = 1
        for path in result.files[:_MAX_LISTED_FILES]:
            link = ctk.CTkButton(
                frame, text=str(path), anchor="w", fg_color="transparent", hover_color=theme.HOVER, text_color=theme.ACCENT, font=theme.font(12), height=24, command=lambda p=path: open_path(p)
            )
            link.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(0, theme.PAD))
            row += 1
        if len(result.files) > _MAX_LISTED_FILES:
            ctk.CTkLabel(frame, text=f"… e mais {len(result.files) - _MAX_LISTED_FILES} arquivo(s).", font=theme.font(12), text_color=theme.TEXT_MUTED).grid(row=row, column=1, sticky="w")
            row += 1
        if result.text:
            self._result_text(frame, row, result.text, tall=not result.files)
        else:
            ctk.CTkFrame(frame, width=1, height=8, fg_color="transparent").grid(row=row, column=0)

    def _result_text(self, frame, row: int, text: str, tall: bool) -> None:
        box = ctk.CTkTextbox(frame, height=240 if tall else 110, font=ctk.CTkFont(family="Consolas", size=12), fg_color=theme.SURFACE_ALT, wrap="word")
        box.grid(row=row, column=0, columnspan=3, sticky="ew", padx=theme.PAD, pady=(6, theme.PAD - 4))
        box.insert("1.0", text)
        box.configure(state="disabled")

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)
            self._set_status("Texto copiado para a área de transferência.", theme.SUCCESS)

        theme.neutral_button(frame, "Copiar", copy, width=90, image=icons.icon("copy", 14)).grid(row=row + 1, column=2, sticky="e", padx=theme.PAD, pady=(0, theme.PAD - 4))

    # ------------------------------------------------------------------ navegação
    def can_leave(self) -> bool:
        if not self.runner.running:
            return True
        if messagebox.askyesno(self.tool.name, "Há uma operação em andamento. Cancelar e sair?", parent=self):
            self.runner.cancel()
            return True
        return False
