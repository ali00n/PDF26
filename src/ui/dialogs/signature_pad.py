"""Criação da assinatura: desenhar com o mouse, digitar o nome ou importar imagem."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import List, Optional, Tuple

import customtkinter as ctk
from PIL import Image, ImageDraw

from ...domain.tool import IMAGE_TYPES
from ...services.pdf.common import register_heif
from ...services.pdf.security import render_text_signature
from ...utils.exceptions import ValidationError
from .. import theme
from ..system import temp_file
from .base import ModalDialog

INK_COLORS = {"Azul": "#1E3A8A", "Preto": "#111111"}
_PAD_SIZE = (560, 200)
_RENDER_SCALE = 3
_WHITE_THRESHOLD = 225

Stroke = List[Tuple[float, float]]


class SignatureDialog(ModalDialog):
    def __init__(self, master, mode: str = "draw"):
        super().__init__(master, "Assinatura", width=620, height=420)
        self._strokes: List[Stroke] = []
        self._ink = tk.StringVar(value="Azul")
        self._tabs = ctk.CTkTabview(self.body, fg_color=theme.SURFACE_ALT, segmented_button_selected_color=theme.ACCENT, segmented_button_selected_hover_color=theme.ACCENT_HOVER)
        self._tabs.pack(fill="both", expand=True)
        self._build_draw(self._tabs.add("Desenhar"))
        self._build_type(self._tabs.add("Digitar"))
        self._tabs.set("Digitar" if mode == "type" else "Desenhar")
        ctk.CTkLabel(self.footer, text="Cor:", font=theme.font(12), text_color=theme.TEXT).pack(side="left")
        theme.segmented(self.footer, INK_COLORS, command=lambda _v: self._refresh_ink(), variable=self._ink).pack(side="left", padx=6)
        self.add_buttons("Usar assinatura")

    def _build_draw(self, tab) -> None:
        self._canvas = tk.Canvas(tab, width=_PAD_SIZE[0], height=_PAD_SIZE[1], bg="white", highlightthickness=1, highlightbackground="#CBD5E1", cursor="pencil")
        self._canvas.pack(pady=(4, 6))
        self._canvas.create_line(30, _PAD_SIZE[1] - 40, _PAD_SIZE[0] - 30, _PAD_SIZE[1] - 40, fill="#CBD5E1", dash=(4, 4), tags="guide")
        self._canvas.bind("<ButtonPress-1>", self._start_stroke)
        self._canvas.bind("<B1-Motion>", self._extend_stroke)
        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(row, text="Assine com o mouse ou caneta sobre a linha.", font=theme.font(12), text_color=theme.TEXT_MUTED).pack(side="left")
        theme.neutral_button(row, "Limpar", self._clear, width=80).pack(side="right")

    def _build_type(self, tab) -> None:
        self._name = ctk.CTkEntry(tab, placeholder_text="Digite seu nome", font=theme.font(15), height=38)
        self._name.pack(fill="x", padx=8, pady=(12, 8))
        self._name.bind("<KeyRelease>", lambda _event: self._schedule_preview())
        self._preview = ctk.CTkLabel(tab, text="", height=120, fg_color="white", corner_radius=8)
        self._preview.pack(fill="x", padx=8)
        self._preview_job = None

    # ------------------------------------------------------------------ desenho
    def _start_stroke(self, event) -> None:
        self._strokes.append([(event.x, event.y)])

    def _extend_stroke(self, event) -> None:
        stroke = self._strokes[-1]
        x0, y0 = stroke[-1]
        stroke.append((event.x, event.y))
        self._canvas.create_line(x0, y0, event.x, event.y, fill=INK_COLORS[self._ink.get()], width=2.6, capstyle="round", smooth=True, tags="ink")

    def _clear(self) -> None:
        self._strokes.clear()
        self._canvas.delete("ink")

    def _refresh_ink(self) -> None:
        self._canvas.itemconfigure("ink", fill=INK_COLORS[self._ink.get()])
        self._schedule_preview()

    def _render_strokes(self, target: Path) -> Optional[Path]:
        strokes = [stroke for stroke in self._strokes if len(stroke) > 1]
        if not strokes:
            return None
        width, height = (_PAD_SIZE[0] * _RENDER_SCALE, _PAD_SIZE[1] * _RENDER_SCALE)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        for stroke in strokes:
            points = [(x * _RENDER_SCALE, y * _RENDER_SCALE) for x, y in stroke]
            draw.line(points, fill=INK_COLORS[self._ink.get()], width=8, joint="curve")
            for x, y in (points[0], points[-1]):
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=INK_COLORS[self._ink.get()])
        box = image.getbbox()
        margin = 12
        image.crop((max(0, box[0] - margin), max(0, box[1] - margin), min(width, box[2] + margin), min(height, box[3] + margin))).save(target)
        return target

    # ------------------------------------------------------------------ digitada
    def _schedule_preview(self) -> None:
        if self._preview_job:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(250, self._update_preview)

    def _update_preview(self) -> None:
        name = self._name.get().strip()
        if not name:
            self._preview.configure(image=None)
            return
        path = render_text_signature(name, temp_file("previa_assinatura.png"), INK_COLORS[self._ink.get()])
        with Image.open(path) as image:
            preview = image.copy()
        preview.thumbnail((540, 110))
        self._preview_image = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
        self._preview.configure(image=self._preview_image)

    # ------------------------------------------------------------------ resultado
    def accept(self) -> None:
        target = temp_file(f"assinatura_{int(time.time() * 1000)}.png")
        try:
            if self._tabs.get() == "Digitar":
                self.result = render_text_signature(self._name.get(), target, INK_COLORS[self._ink.get()])
            else:
                self.result = self._render_strokes(target)
        except ValidationError as error:
            messagebox.showwarning("Assinatura", error.message, parent=self)
            return
        if self.result is None:
            messagebox.showwarning("Assinatura", "Desenhe a assinatura antes de continuar.", parent=self)
            return
        self.destroy()


def signature_from_image(path: Path) -> Path:
    """Importa assinatura escaneada/fotografada tornando o fundo claro transparente."""
    register_heif()
    with Image.open(path) as source:
        image = source.convert("RGBA")
    gray = image.convert("L")
    alpha = gray.point(lambda value: 0 if value >= _WHITE_THRESHOLD else 255 - value // 2)
    image.putalpha(alpha)
    box = alpha.getbbox() or (0, 0, image.width, image.height)
    target = temp_file(f"assinatura_{int(time.time() * 1000)}.png")
    image.crop(box).save(target)
    return target


def ask_signature(master, mode: str = "draw") -> Optional[Path]:
    """Abre o diálogo (desenhar/digitar) ou o seletor de imagem e devolve um PNG transparente."""
    if mode == "image":
        name = filedialog.askopenfilename(parent=master, title="Imagem da assinatura", filetypes=list(IMAGE_TYPES))
        return signature_from_image(Path(name)) if name else None
    return SignatureDialog(master, mode).show()
