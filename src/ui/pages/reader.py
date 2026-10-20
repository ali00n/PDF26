"""Leitor e editor de PDF: navegação, zoom, pesquisa e ferramentas de anotação/edição."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional, Sequence, Tuple

import customtkinter as ctk
import pymupdf
from PIL import Image, ImageTk

from ...domain.tool import IMAGE_TYPES, PDF_TYPES, ToolSpec
from ...services.pdf.common import needs_password
from ...services.pdf.editor import EditorSession
from ...utils.exceptions import PDF26Error
from .. import icons, theme
from ..dialogs.base import ask_text
from ..dialogs.signature_pad import ask_signature
from ..system import describe_error
from ..widgets.dnd import enable_drop
from ..widgets.header import PageHeader

EDIT_TOOLS: Tuple[Tuple[str, str], ...] = (
    ("pan", "Mover"),
    ("text", "Texto"),
    ("highlight", "Destacar"),
    ("rect", "Retângulo"),
    ("ellipse", "Elipse"),
    ("ink", "Desenhar"),
    ("note", "Nota"),
    ("image", "Imagem"),
    ("signature", "Assinatura"),
    ("redact", "Tarja"),
)
HINTS = {
    "pan": "Arraste para mover a página. Roda do mouse rola; Ctrl + roda aplica zoom.",
    "text": "Clique onde o texto deve começar (ou arraste para definir a caixa).",
    "highlight": "Arraste sobre o texto a destacar.",
    "rect": "Arraste para desenhar um retângulo.",
    "ellipse": "Arraste para desenhar uma elipse.",
    "ink": "Desenhe à mão livre com o mouse.",
    "note": "Clique para adicionar um comentário (nota).",
    "image": "Arraste a área da imagem (ou clique para tamanho padrão).",
    "signature": "Arraste a área da assinatura (ou clique para tamanho padrão).",
    "redact": "Arraste sobre o conteúdo a remover. A tarja apaga o conteúdo de verdade.",
}
COLORS = {"Vermelho": "#E11D48", "Azul": "#1D4ED8", "Preto": "#111111", "Verde": "#15803D", "Laranja": "#EA580C"}
FONT_SIZES = ("8", "10", "12", "14", "18", "24", "32", "48")
ZOOM_STEPS = (0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0)
_PAGE_MARGIN = 24
_DRAG_THRESHOLD = 4
_POINT_TO_PIXEL = 96 / 72  # 100% = tamanho real em tela de 96 dpi


class ReaderPage(ctk.CTkFrame):
    def __init__(self, master, app, tool: ToolSpec, files: Sequence[Path] = ()):
        super().__init__(master, fg_color="transparent")
        self.app, self.tool = app, tool
        self.edit_mode = tool.page == "editor"
        self.session: Optional[EditorSession] = None
        self.page_number = 0
        self.zoom = 1.0
        self.fit = "width"  # width | page | None
        self.mode = "pan"
        self.hits: List[Tuple[int, pymupdf.Rect]] = []
        self.hit_index = -1
        self._photo = None
        self._origin = (0.0, 0.0)
        self._drag_start: Optional[Tuple[float, float]] = None
        self._ink_points: List[Tuple[float, float]] = []
        self._signature: Optional[Path] = None
        self._redact_confirmed = False
        self._resize_job = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.header = PageHeader(self, tool, app.show_home, app.prefs.is_favorite(tool.id), lambda: app.toggle_favorite(tool.id))
        self.header.grid(row=0, column=0, sticky="ew", padx=theme.PAD * 2, pady=(theme.PAD * 1.5, theme.GAP))
        self._build_search(self.header.extra)
        self._build_toolbar()
        self._build_edit_bar()
        self._build_canvas()
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=theme.PAD * 2, pady=(4, theme.GAP))
        bottom.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(bottom, text="", font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="w")
        self.status.grid(row=0, column=0, sticky="ew")
        self._file_label = ctk.CTkLabel(bottom, text="", font=theme.font(12), text_color=theme.TEXT_MUTED, anchor="e")
        self._file_label.grid(row=0, column=1, sticky="e")
        self._set_edit_visible(self.edit_mode)
        if files:
            self.after(50, lambda: self.open(Path(files[0])))
        else:
            self._render()

    # ------------------------------------------------------------------ construção
    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        bar.grid(row=1, column=0, sticky="ew", padx=theme.PAD * 2, pady=(0, theme.GAP))
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=8, pady=6)
        theme.icon_button(left, icons.icon("folder", 18), self.choose_file, "Abrir PDF (Ctrl+O)", size=34).pack(side="left")
        theme.icon_button(left, icons.icon("save", 18), self.save, "Salvar (Ctrl+S)", size=34).pack(side="left")
        theme.neutral_button(left, "Salvar como…", self.save_as, width=104).pack(side="left", padx=(4, 0))
        self._separator(left)
        theme.icon_button(left, icons.icon("prev", 18), lambda: self.go_to(self.page_number - 1), "Página anterior (PgUp)", size=34).pack(side="left")
        self._page_entry = ctk.CTkEntry(left, width=48, justify="center", font=theme.font(12))
        self._page_entry.pack(side="left", padx=2)
        self._page_entry.bind("<Return>", self._jump)
        self._page_total = ctk.CTkLabel(left, text="/ 0", font=theme.font(12), text_color=theme.TEXT_MUTED)
        self._page_total.pack(side="left", padx=(2, 4))
        theme.icon_button(left, icons.icon("next", 18), lambda: self.go_to(self.page_number + 1), "Próxima página (PgDn)", size=34).pack(side="left")
        self._separator(left)
        theme.icon_button(left, icons.icon("minus", 18), lambda: self.step_zoom(-1), "Diminuir zoom (Ctrl −)", size=34).pack(side="left")
        self._zoom_label = ctk.CTkLabel(left, text="100%", width=52, font=theme.font(12))
        self._zoom_label.pack(side="left")
        theme.icon_button(left, icons.icon("plus", 18), lambda: self.step_zoom(1), "Aumentar zoom (Ctrl +)", size=34).pack(side="left")
        theme.icon_button(left, icons.icon("fit_width", 18), lambda: self.set_fit("width"), "Ajustar à largura", size=34).pack(side="left")
        theme.icon_button(left, icons.icon("fit_page", 18), lambda: self.set_fit("page"), "Página inteira", size=34).pack(side="left")
        self._separator(left)
        theme.icon_button(left, icons.icon("rotate_ccw", 18), lambda: self._edit(lambda s: s.rotate_page(self.page_number, -90)), "Girar página à esquerda", size=34).pack(side="left")
        theme.icon_button(left, icons.icon("rotate_cw", 18), lambda: self._edit(lambda s: s.rotate_page(self.page_number, 90)), "Girar página à direita", size=34).pack(side="left")
        theme.icon_button(left, icons.icon("trash", 18, theme.DANGER), self._delete_page, "Excluir página", size=34).pack(side="left")

        self._edit_switch = ctk.CTkSwitch(bar, text="Editar", command=self._toggle_edit, font=theme.font(12), progress_color=theme.ACCENT)
        self._edit_switch.pack(side="right", padx=12)
        if self.edit_mode:
            self._edit_switch.select()

    def _build_search(self, parent) -> None:
        box = ctk.CTkFrame(parent, fg_color=theme.SURFACE, corner_radius=18, border_width=1, border_color=theme.BORDER)
        box.pack(side="right")
        ctk.CTkLabel(box, text="", image=icons.icon("search", 15, theme.TEXT_MUTED)).pack(side="left", padx=(10, 2))
        self._search = ctk.CTkEntry(box, width=220, height=32, border_width=0, fg_color="transparent", placeholder_text="Pesquisar no documento", font=theme.font(12))
        self._search.pack(side="left")
        self._search.bind("<Return>", lambda _event: self._run_search())
        theme.icon_button(box, icons.icon("prev", 15), lambda: self._next_hit(-1), "Resultado anterior", size=28).pack(side="left")
        theme.icon_button(box, icons.icon("next", 15), lambda: self._next_hit(1), "Próximo resultado", size=28).pack(side="left")
        self._hits_label = ctk.CTkLabel(box, text="", width=48, font=theme.font(11), text_color=theme.TEXT_MUTED)
        self._hits_label.pack(side="left", padx=(0, 8))

    def _separator(self, parent) -> None:
        ctk.CTkFrame(parent, width=1, height=24, fg_color=theme.BORDER).pack(side="left", padx=8)

    def _build_edit_bar(self) -> None:
        self._edit_bar = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=theme.RADIUS, border_width=1, border_color=theme.BORDER)
        labels = [label for _, label in EDIT_TOOLS]
        self._mode_labels = {label: key for key, label in EDIT_TOOLS}
        self._modes = theme.segmented(self._edit_bar, labels, command=self._set_mode)
        self._modes.set("Mover")
        self._modes.pack(side="left", padx=8, pady=6)
        ctk.CTkLabel(self._edit_bar, text="Cor", font=theme.font(12), text_color=theme.TEXT_MUTED).pack(side="left", padx=(8, 4))
        self._color = ctk.CTkOptionMenu(self._edit_bar, values=list(COLORS), width=104, font=theme.font(12), fg_color=theme.SURFACE_ALT, button_color=theme.NEUTRAL_BUTTON_HOVER, text_color=theme.TEXT)
        self._color.pack(side="left")
        ctk.CTkLabel(self._edit_bar, text="Fonte", font=theme.font(12), text_color=theme.TEXT_MUTED).pack(side="left", padx=(10, 4))
        self._font_size = ctk.CTkOptionMenu(
            self._edit_bar, values=list(FONT_SIZES), width=64, font=theme.font(12), fg_color=theme.SURFACE_ALT, button_color=theme.NEUTRAL_BUTTON_HOVER, text_color=theme.TEXT
        )
        self._font_size.set("14")
        self._font_size.pack(side="left")
        theme.neutral_button(self._edit_bar, "Desfazer", self.undo, width=96, image=icons.icon("undo", 14)).pack(side="right", padx=8)

    def _build_canvas(self) -> None:
        holder = ctk.CTkFrame(self, fg_color=theme.CANVAS, corner_radius=theme.RADIUS)
        holder.grid(row=3, column=0, sticky="nsew", padx=theme.PAD * 2)
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(holder, highlightthickness=0, bd=0, bg=theme.color(theme.CANVAS))
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=(6, 0))
        vbar = ctk.CTkScrollbar(holder, command=self.canvas.yview)
        vbar.grid(row=0, column=1, sticky="ns", pady=6)
        hbar = ctk.CTkScrollbar(holder, orientation="horizontal", command=self.canvas.xview)
        hbar.grid(row=1, column=0, sticky="ew", padx=6)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Enter>", lambda _event: self.canvas.focus_set())
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(sequence, self._wheel)
        for sequence, action in (
            ("<Prior>", lambda: self.go_to(self.page_number - 1)),
            ("<Next>", lambda: self.go_to(self.page_number + 1)),
            ("<Home>", lambda: self.go_to(0)),
            ("<End>", lambda: self.go_to(self.session.page_count - 1 if self.session else 0)),
            ("<Control-s>", self.save),
            ("<Control-z>", self.undo),
            ("<Control-plus>", lambda: self.step_zoom(1)),
            ("<Control-equal>", lambda: self.step_zoom(1)),
            ("<Control-minus>", lambda: self.step_zoom(-1)),
        ):
            self.canvas.bind(sequence, lambda _event, fn=action: fn())
        enable_drop(holder, lambda paths: self.open(paths[0]) if paths else None)

    # ------------------------------------------------------------------ arquivo
    def choose_file(self) -> None:
        name = filedialog.askopenfilename(parent=self, title="Abrir PDF", filetypes=list(PDF_TYPES))
        if name:
            self.open(Path(name))

    def open(self, path: Path) -> None:
        if path.suffix.lower() != ".pdf":
            messagebox.showwarning("PDF26", "Selecione um arquivo PDF.", parent=self)
            return
        if not self._confirm_discard():
            return
        password = None
        if needs_password(path):
            password = ask_text(self, "PDF protegido", f"Senha para abrir '{path.name}':", secret=True)
            if password is None:
                return
        try:
            session = EditorSession(path, password)
        except PDF26Error as error:
            messagebox.showerror("PDF26", error.message, parent=self)
            return
        if self.session:
            self.session.close()
        self.session = session
        self.page_number = 0
        self.hits, self.hit_index = [], -1
        self.fit = "width"
        self._file_label.configure(text=str(path))
        self._render()

    def save(self) -> None:
        if not self.session:
            return
        try:
            target = self.session.save()
        except PDF26Error as error:
            messagebox.showerror("PDF26", error.message, parent=self)
            return
        self._status(f"Salvo em {target}")

    def save_as(self) -> None:
        if not self.session:
            return
        name = filedialog.asksaveasfilename(
            parent=self, title="Salvar como", defaultextension=".pdf", filetypes=list(PDF_TYPES), initialdir=str(self.session.path.parent), initialfile=f"{self.session.path.stem}_editado.pdf"
        )
        if not name:
            return
        try:
            target = self.session.save(Path(name))
        except PDF26Error as error:
            messagebox.showerror("PDF26", error.message, parent=self)
            return
        self._file_label.configure(text=str(target))
        self._status(f"Salvo em {target}")

    def _confirm_discard(self) -> bool:
        if not (self.session and self.session.dirty):
            return True
        answer = messagebox.askyesnocancel("PDF26", f"Salvar as alterações em '{self.session.path.name}'?", parent=self)
        if answer is None:
            return False
        if answer:
            self.save()
            return not self.session.dirty
        return True

    def can_leave(self) -> bool:
        if not self._confirm_discard():
            return False
        if self.session:
            self.session.close()
            self.session = None
        return True

    # ------------------------------------------------------------------ renderização
    def _pixels_per_point(self) -> float:
        return self.zoom * _POINT_TO_PIXEL * ctk.ScalingTracker.get_widget_scaling(self)

    def _fit_zoom(self) -> None:
        if not (self.session and self.fit):
            return
        width, height = self.session.page_size(self.page_number)
        scale = _POINT_TO_PIXEL * ctk.ScalingTracker.get_widget_scaling(self)
        available_w = max(100, self.canvas.winfo_width() - 2 * _PAGE_MARGIN)
        available_h = max(100, self.canvas.winfo_height() - 2 * _PAGE_MARGIN)
        zoom_w = available_w / (width * scale)
        self.zoom = zoom_w if self.fit == "width" else min(zoom_w, available_h / (height * scale))
        self.zoom = max(0.1, min(self.zoom, 5.0))

    def _render(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(bg=theme.color(theme.CANVAS))
        if not self.session:
            self._render_empty()
            return
        self._fit_zoom()
        ppp = self._pixels_per_point()
        image = self.session.render(self.page_number, ppp)
        self._photo = ImageTk.PhotoImage(image)
        view_w = max(canvas.winfo_width(), image.width + 2 * _PAGE_MARGIN)
        x0 = (view_w - image.width) / 2
        self._origin = (x0, _PAGE_MARGIN)
        shadow = "#05060A" if ctk.get_appearance_mode() == "Dark" else "#C4C9D1"
        canvas.create_rectangle(x0 + 3, _PAGE_MARGIN + 3, x0 + image.width + 3, _PAGE_MARGIN + image.height + 3, fill=shadow, outline="")
        canvas.create_image(x0, _PAGE_MARGIN, image=self._photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, view_w, image.height + 2 * _PAGE_MARGIN))
        self._draw_hits()
        self._page_entry.delete(0, "end")
        self._page_entry.insert(0, str(self.page_number + 1))
        self._page_total.configure(text=f"/ {self.session.page_count}")
        self._zoom_label.configure(text=f"{round(self.zoom * 100)}%")
        if not self.status.cget("text"):
            self._status(HINTS[self.mode] if self.edit_mode else "Ctrl + roda do mouse para zoom · PgUp/PgDn para trocar de página")

    def _render_empty(self) -> None:
        width, height = max(self.canvas.winfo_width(), 400), max(self.canvas.winfo_height(), 300)
        self.canvas.create_text(width / 2, height / 2 - 16, text="Abra um PDF para começar", fill=theme.color(theme.TEXT), font=("Segoe UI", 16, "bold"))
        self.canvas.create_text(width / 2, height / 2 + 14, text="Clique no ícone de pasta, use Ctrl+O ou arraste um arquivo para cá", fill=theme.color(theme.TEXT_MUTED), font=("Segoe UI", 11))
        self.canvas.configure(scrollregion=(0, 0, width, height))
        self._page_total.configure(text="/ 0")

    def _draw_hits(self) -> None:
        ppp = self._pixels_per_point()
        x0, y0 = self._origin
        for index, (number, rect) in enumerate(self.hits):
            if number != self.page_number:
                continue
            current = index == self.hit_index
            self.canvas.create_rectangle(
                x0 + rect.x0 * ppp - 2, y0 + rect.y0 * ppp - 2, x0 + rect.x1 * ppp + 2, y0 + rect.y1 * ppp + 2, outline="#F97316" if current else "#FACC15", width=3 if current else 2
            )

    def on_appearance_change(self) -> None:
        self._render()

    def _on_resize(self, _event=None) -> None:
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self._render)

    # ------------------------------------------------------------------ navegação e zoom
    def go_to(self, number: int, keep_scroll: bool = False) -> None:
        if not self.session:
            return
        number = max(0, min(number, self.session.page_count - 1))
        if number == self.page_number:
            return
        self.page_number = number
        self._render()
        if not keep_scroll:
            self.canvas.yview_moveto(0)

    def _jump(self, _event=None) -> None:
        try:
            self.go_to(int(self._page_entry.get()) - 1)
        except ValueError:
            self._render()

    def step_zoom(self, direction: int) -> None:
        if not self.session:
            return
        current = self.zoom
        candidates = [step for step in ZOOM_STEPS if (step > current + 0.01 if direction > 0 else step < current - 0.01)]
        if candidates:
            self.zoom = candidates[0] if direction > 0 else candidates[-1]
            self.fit = None
            self._render()

    def set_fit(self, mode: str) -> None:
        self.fit = mode
        self._render()

    def _wheel(self, event) -> None:
        delta = 1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else -1
        if event.state & 0x0004:  # Ctrl
            self.step_zoom(delta)
            return
        top, bottom = self.canvas.yview()
        if delta < 0 and bottom >= 0.999 and self.session and self.page_number < self.session.page_count - 1:
            self.go_to(self.page_number + 1)
            return
        if delta > 0 and top <= 0.001 and self.page_number > 0:
            self.go_to(self.page_number - 1, keep_scroll=True)
            self.canvas.yview_moveto(1.0)
            return
        step = -3 if delta > 0 else 3
        if sys.platform == "darwin":
            step = -event.delta
        self.canvas.yview_scroll(step, "units")

    # ------------------------------------------------------------------ pesquisa
    def _run_search(self) -> None:
        query = self._search.get().strip()
        if not (self.session and query):
            return
        self.hits = self.session.search(query)
        self.hit_index = -1
        if not self.hits:
            self._hits_label.configure(text="0/0")
            self._status(f"“{query}” não encontrado.")
            self._render()
            return
        self._next_hit(1)

    def _next_hit(self, step: int) -> None:
        if not self.hits:
            return
        self.hit_index = (self.hit_index + step) % len(self.hits)
        number, rect = self.hits[self.hit_index]
        self._hits_label.configure(text=f"{self.hit_index + 1}/{len(self.hits)}")
        if number != self.page_number:
            self.page_number = number
        self._render()
        image_height = float(self.canvas.cget("scrollregion").split()[3])
        target = (self._origin[1] + rect.y0 * self._pixels_per_point() - self.canvas.winfo_height() / 3) / image_height
        self.canvas.yview_moveto(max(0.0, target))

    # ------------------------------------------------------------------ edição
    def _toggle_edit(self) -> None:
        self._set_edit_visible(bool(self._edit_switch.get()))

    def _set_edit_visible(self, visible: bool) -> None:
        self.edit_mode = visible
        if visible:
            self._edit_bar.grid(row=2, column=0, sticky="ew", padx=theme.PAD * 2, pady=(0, theme.GAP))
        else:
            self._edit_bar.grid_remove()
            self._set_mode("Mover")
            self._modes.set("Mover")
        self._status(HINTS[self.mode] if visible else "")

    def _set_mode(self, label: str) -> None:
        self.mode = self._mode_labels[label]
        self.canvas.configure(cursor="fleur" if self.mode == "pan" else "pencil" if self.mode == "ink" else "crosshair")
        self._status(HINTS[self.mode])

    def _to_page(self, x: float, y: float) -> Tuple[float, float]:
        ppp = self._pixels_per_point()
        return (x - self._origin[0]) / ppp, (y - self._origin[1]) / ppp

    def _press(self, event) -> None:
        self.canvas.focus_set()
        if not self.session:
            self.choose_file()
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self._drag_start = (x, y)
        if self.mode == "pan":
            self.canvas.scan_mark(event.x, event.y)
        elif self.mode == "ink":
            self._ink_points = [self._to_page(x, y)]

    def _drag(self, event) -> None:
        if not (self.session and self._drag_start):
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.mode == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
        elif self.mode == "ink":
            last = self._ink_points[-1]
            ppp = self._pixels_per_point()
            lx, ly = self._origin[0] + last[0] * ppp, self._origin[1] + last[1] * ppp
            self.canvas.create_line(lx, ly, x, y, fill=COLORS[self._color.get()], width=2, capstyle="round", tags="preview")
            self._ink_points.append(self._to_page(x, y))
        else:
            self.canvas.delete("preview")
            x0, y0 = self._drag_start
            self.canvas.create_rectangle(x0, y0, x, y, outline=theme.color(theme.ACCENT), dash=(4, 3), width=2, tags="preview")

    def _release(self, event) -> None:
        if not (self.session and self._drag_start) or self.mode == "pan":
            self._drag_start = None
            return
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        x0, y0 = self._drag_start
        self._drag_start = None
        self.canvas.delete("preview")
        dragged = abs(x - x0) > _DRAG_THRESHOLD or abs(y - y0) > _DRAG_THRESHOLD
        start, end = self._to_page(x0, y0), self._to_page(x, y)
        rect = pymupdf.Rect(start, end).normalize()
        handler = getattr(self, f"_apply_{self.mode}")
        handler(rect, dragged)

    def _edit(self, action) -> None:
        if not self.session:
            return
        try:
            action(self.session)
        except Exception as error:
            messagebox.showerror("PDF26", describe_error(error), parent=self)
        self._render()

    def _apply_text(self, rect: pymupdf.Rect, dragged: bool) -> None:
        text = ask_text(self, "Adicionar texto", "Texto:", multiline=True)
        if not text:
            return
        size = float(self._font_size.get())
        if not dragged or rect.width < size:
            lines = text.splitlines() or [text]
            width = max(pymupdf.get_text_length(line, fontname="helv", fontsize=size) for line in lines) + size
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + width, rect.y0 + len(lines) * size * 1.3 + size * 0.6)
        self._edit(lambda s: s.add_text(self.page_number, rect, text, size, COLORS[self._color.get()]))

    def _apply_highlight(self, rect: pymupdf.Rect, dragged: bool) -> None:
        if dragged:
            self._edit(lambda s: s.add_highlight(self.page_number, rect))

    def _apply_rect(self, rect: pymupdf.Rect, dragged: bool) -> None:
        if dragged:
            self._edit(lambda s: s.add_shape(self.page_number, rect, "rect", COLORS[self._color.get()]))

    def _apply_ellipse(self, rect: pymupdf.Rect, dragged: bool) -> None:
        if dragged:
            self._edit(lambda s: s.add_shape(self.page_number, rect, "ellipse", COLORS[self._color.get()]))

    def _apply_ink(self, _rect: pymupdf.Rect, _dragged: bool) -> None:
        points, self._ink_points = self._ink_points, []
        self._edit(lambda s: s.add_ink(self.page_number, points, COLORS[self._color.get()]))

    def _apply_note(self, rect: pymupdf.Rect, _dragged: bool) -> None:
        text = ask_text(self, "Nota", "Comentário:", multiline=True)
        if text:
            self._edit(lambda s: s.add_note(self.page_number, (rect.x0, rect.y0), text))

    def _apply_image(self, rect: pymupdf.Rect, dragged: bool) -> None:
        name = filedialog.askopenfilename(parent=self, title="Inserir imagem", filetypes=list(IMAGE_TYPES))
        if name:
            self._place_image(Path(name), rect, dragged, default_width=200)

    def _apply_signature(self, rect: pymupdf.Rect, dragged: bool) -> None:
        if self._signature is None or not self._signature.exists():
            self._signature = ask_signature(self.winfo_toplevel(), "draw")
            if self._signature is None:
                return
        self._place_image(self._signature, rect, dragged, default_width=150)

    def _place_image(self, image_path: Path, rect: pymupdf.Rect, dragged: bool, default_width: float) -> None:
        if not dragged:
            with Image.open(image_path) as image:
                ratio = image.height / image.width
            rect = pymupdf.Rect(rect.x0, rect.y0, rect.x0 + default_width, rect.y0 + default_width * ratio)
        self._edit(lambda s: s.add_image(self.page_number, rect, image_path))

    def _apply_redact(self, rect: pymupdf.Rect, dragged: bool) -> None:
        if not dragged:
            return
        if not self._redact_confirmed:
            self._redact_confirmed = messagebox.askyesno("Tarja", "A tarja remove definitivamente o texto e as imagens sob a área (não apenas cobre). Continuar?", parent=self)
            if not self._redact_confirmed:
                return
        self._edit(lambda s: s.redact(self.page_number, rect))

    def _delete_page(self) -> None:
        if self.session and messagebox.askyesno("PDF26", f"Excluir a página {self.page_number + 1}?", parent=self):
            self._edit(lambda s: s.delete_page(self.page_number))
            self.page_number = min(self.page_number, self.session.page_count - 1)
            self._render()

    def undo(self) -> None:
        if self.session and self.session.undo():
            self.page_number = min(self.page_number, self.session.page_count - 1)
            self._render()
            self._status("Alteração desfeita.")

    def _status(self, text: str) -> None:
        dirty = " · alterações não salvas" if self.session and self.session.dirty else ""
        self.status.configure(text=(text + dirty) if text else dirty.lstrip(" ·"))
