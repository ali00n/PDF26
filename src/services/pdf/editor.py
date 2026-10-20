"""
Sessão de edição interativa usada pelo Leitor/Editor.

Todas as coordenadas recebidas e devolvidas estão no espaço VISÍVEL da página
(como renderizada, já rotacionada). A conversão para o espaço do PDF fica aqui.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pymupdf
from PIL import Image

from ...utils.exceptions import PDFError
from .common import hex_to_rgb

Point = Tuple[float, float]
_HISTORY_LIMIT = 30


class EditorSession:
    """Documento aberto em memória (sem travar o arquivo no Windows) com desfazer por instantâneos."""

    def __init__(self, path: Path, password: Optional[str] = None):
        self.path = Path(path)
        self._password = password
        self.doc = self._load(self.path.read_bytes())
        self._history: List[bytes] = []
        self.dirty = False

    def _load(self, data: bytes) -> pymupdf.Document:
        try:
            doc = pymupdf.open("pdf", data)
        except Exception as error:
            raise PDFError(f"Não foi possível abrir '{self.path.name}': {error}", file=str(self.path)) from error
        if doc.needs_pass and not (self._password and doc.authenticate(self._password)):
            doc.close()
            raise PDFError(f"'{self.path.name}' está protegido por senha.", file=str(self.path))
        return doc

    @property
    def page_count(self) -> int:
        return self.doc.page_count

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    def page_size(self, number: int) -> Tuple[float, float]:
        rect = self.doc[number].rect
        return rect.width, rect.height

    def render(self, number: int, zoom: float) -> Image.Image:
        pix = self.doc[number].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
        mode = "RGBA" if pix.alpha else "RGB"
        return Image.frombytes(mode, (pix.width, pix.height), pix.samples)

    def page_text(self, number: int) -> str:
        return self.doc[number].get_text("text", sort=True)

    def search(self, text: str) -> List[Tuple[int, pymupdf.Rect]]:
        hits = []
        for page in self.doc:
            hits.extend((page.number, rect * page.rotation_matrix) for rect in page.search_for(text))
        return hits

    # ------------------------------------------------------------------ edições
    def _snapshot(self) -> None:
        self._history.append(self.doc.tobytes())
        del self._history[:-_HISTORY_LIMIT]
        self.dirty = True

    def undo(self) -> bool:
        if not self._history:
            return False
        data = self._history.pop()
        self.doc.close()
        self.doc = self._load(data)
        self.dirty = True
        return True

    @staticmethod
    def _to_pdf(page: pymupdf.Page, rect: pymupdf.Rect) -> pymupdf.Rect:
        return (pymupdf.Rect(rect).normalize() & page.rect) * page.derotation_matrix

    def add_text(self, number: int, rect: pymupdf.Rect, text: str, font_size: float = 12, color: str = "#000000") -> None:
        self._snapshot()
        page = self.doc[number]
        annot = page.add_freetext_annot(self._to_pdf(page, rect), text, fontsize=font_size, fontname="helv", text_color=hex_to_rgb(color), rotate=page.rotation)
        annot.update()

    def add_highlight(self, number: int, rect: pymupdf.Rect, color: str = "#FFE135") -> None:
        page = self.doc[number]
        area = self._to_pdf(page, rect)
        quads = [pymupdf.Rect(word[:4]).quad for word in page.get_text("words") if pymupdf.Rect(word[:4]).intersects(area)]
        self._snapshot()
        annot = page.add_highlight_annot(quads) if quads else page.add_rect_annot(area)
        if quads:
            annot.set_colors(stroke=hex_to_rgb(color))
        else:
            annot.set_colors(stroke=None, fill=hex_to_rgb(color))
            annot.set_border(width=0)
            annot.set_opacity(0.4)
        annot.update()

    def add_shape(self, number: int, rect: pymupdf.Rect, kind: str = "rect", color: str = "#E11D48", width: float = 2) -> None:
        self._snapshot()
        page = self.doc[number]
        area = self._to_pdf(page, rect)
        annot = page.add_circle_annot(area) if kind == "ellipse" else page.add_rect_annot(area)
        annot.set_colors(stroke=hex_to_rgb(color))
        annot.set_border(width=width)
        annot.update()

    def add_ink(self, number: int, points: Sequence[Point], color: str = "#1E3A8A", width: float = 2) -> None:
        if len(points) < 2:
            return
        self._snapshot()
        page = self.doc[number]
        matrix = page.derotation_matrix
        annot = page.add_ink_annot([[tuple(pymupdf.Point(point) * matrix) for point in points]])
        annot.set_colors(stroke=hex_to_rgb(color))
        annot.set_border(width=width)
        annot.update()

    def add_note(self, number: int, point: Point, text: str) -> None:
        self._snapshot()
        page = self.doc[number]
        annot = page.add_text_annot(pymupdf.Point(point) * page.derotation_matrix, text, icon="Comment")
        annot.update()

    def add_image(self, number: int, rect: pymupdf.Rect, image: Path) -> None:
        self._snapshot()
        page = self.doc[number]
        page.insert_image(self._to_pdf(page, rect), filename=str(image), keep_proportion=True, rotate=page.rotation)

    def redact(self, number: int, rect: pymupdf.Rect) -> None:
        """Remove definitivamente o conteúdo sob a área (texto, imagem e vetores)."""
        self._snapshot()
        page = self.doc[number]
        page.add_redact_annot(self._to_pdf(page, rect), fill=(0, 0, 0))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)

    def rotate_page(self, number: int, delta: int) -> None:
        self._snapshot()
        page = self.doc[number]
        page.set_rotation((page.rotation + delta) % 360)

    def delete_page(self, number: int) -> None:
        if self.doc.page_count == 1:
            raise PDFError("O documento precisa ter ao menos uma página.")
        self._snapshot()
        self.doc.delete_page(number)

    def save(self, target: Optional[Path] = None) -> Path:
        """Salva (no próprio arquivo ou em outro) via arquivo temporário + substituição atômica."""
        target = Path(target or self.path)
        data = self.doc.tobytes(garbage=3, deflate=True)
        handle, temp = tempfile.mkstemp(suffix=".pdf", dir=target.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.replace(temp, target)
        except OSError as error:
            Path(temp).unlink(missing_ok=True)
            raise PDFError(f"Não foi possível salvar '{target.name}': {error}. O arquivo está aberto em outro programa?") from error
        self.path, self.dirty = target, False
        return target

    def close(self) -> None:
        self.doc.close()
