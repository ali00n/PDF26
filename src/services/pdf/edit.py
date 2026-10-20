"""Serviços de edição: marca d'água, numeração, sobreposição, recorte, tamanho de página, metadados e achatamento."""

from __future__ import annotations

import io
import math
from datetime import date
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pymupdf
from PIL import Image

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import ValidationError
from .common import MM, anchor_rect, rect_center, flattened_copy, hex_to_rgb, new_stamp, opened, paper_rect, parse_pages, save_pdf, stamp_page

METADATA_KEYS = ("title", "author", "subject", "keywords", "creator", "producer")
_BASE_FONT = "helv"


def watermark(
    job: JobContext,
    files: Sequence[Path],
    kind: str = "text",
    text: str = "CONFIDENCIAL",
    font_size: float = 60,
    color: str = "#E11D48",
    image: str = "",
    image_scale: float = 40,
    opacity: float = 25,
    angle: float = 45,
    position: str = "center",
    tile: bool = False,
    layer: str = "over",
    pages: str = "",
) -> ToolResult:
    """Aplica marca d'água de texto ou imagem, com opacidade, rotação e repetição em mosaico."""
    if kind == "text" and not text.strip():
        raise ValidationError("Informe o texto da marca d'água.", field="text")
    if kind == "image" and not image:
        raise ValidationError("Selecione a imagem da marca d'água.", field="image")
    image_bytes = _faded_png(Path(image), opacity / 100) if kind == "image" else b""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Marca d'água em {path.name}")
        with opened(path) as doc:
            stamps: Dict[Tuple[int, int], pymupdf.Document] = {}
            for number in parse_pages(pages, doc.page_count):
                page = doc[number]
                size = (round(page.rect.width), round(page.rect.height))
                if size not in stamps:
                    stamp, canvas = new_stamp(page)
                    if kind == "text":
                        _draw_text_mark(canvas, text, float(font_size), hex_to_rgb(color), opacity / 100, float(angle), position, tile)
                    else:
                        _draw_image_mark(canvas, image_bytes, image_scale / 100, position, tile)
                    stamps[size] = stamp
                stamp_page(page, stamps[size], overlay=layer == "over")
            outputs.append(save_pdf(doc, job.output_file(path, "marca_dagua")))
    return ToolResult(outputs)


def _draw_text_mark(canvas: pymupdf.Page, text: str, font_size: float, color, opacity: float, angle: float, position: str, tile: bool) -> None:
    font = pymupdf.Font(_BASE_FONT)
    width = font.text_length(text, fontsize=font_size)
    area = canvas.rect
    if tile:
        pivot = rect_center(area)
        centers = _tile_centers(pivot, math.hypot(area.width, area.height), width + font_size * 2, font_size * 4)
    else:
        pivot = rect_center(anchor_rect(area, (width, font_size), position, font_size / 2))
        centers = [pivot]
    writer = pymupdf.TextWriter(area, opacity=opacity, color=color)
    for center in centers:
        writer.append(center + (-width / 2, font_size * 0.35), text, font=font, fontsize=font_size)
    writer.write_text(canvas, morph=(pivot, pymupdf.Matrix(-angle)))


def _tile_centers(origin: pymupdf.Point, extent: float, step_x: float, step_y: float) -> List[pymupdf.Point]:
    """Grade em tijolo (linhas alternadas deslocadas) cobrindo um quadrado de lado `extent` — cobre a página após a rotação."""
    rows, columns = int(extent / step_y / 2) + 1, int(extent / step_x / 2) + 1
    return [origin + (step_x * column + (step_x / 2 if row % 2 else 0), step_y * row) for row in range(-rows, rows + 1) for column in range(-columns, columns + 1)]


def _draw_image_mark(canvas: pymupdf.Page, image: bytes, scale: float, position: str, tile: bool) -> None:
    with Image.open(io.BytesIO(image)) as img:
        ratio = img.height / img.width
    width = canvas.rect.width * scale
    height = width * ratio
    if tile:
        rects = [
            pymupdf.Rect(x, y, x + width, y + height)
            for y in [height * 0.25 + i * height * 1.5 for i in range(int(canvas.rect.height / (height * 1.5)) + 1)]
            for x in [width * 0.25 + j * width * 1.5 for j in range(int(canvas.rect.width / (width * 1.5)) + 1)]
        ]
    else:
        rects = [anchor_rect(canvas.rect, (width, height), position, 20)]
    for rect in rects:
        canvas.insert_image(rect, stream=image, keep_proportion=True)


def _faded_png(path: Path, opacity: float) -> bytes:
    """Converte a imagem para PNG com o canal alfa multiplicado pela opacidade."""
    with Image.open(path) as img:
        rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda value: round(value * opacity))
    rgba.putalpha(alpha)
    buffer = io.BytesIO()
    rgba.save(buffer, format="PNG")
    return buffer.getvalue()


def page_numbers(
    job: JobContext,
    files: Sequence[Path],
    template: str = "{n}",
    position: str = "bottom-center",
    start: int = 1,
    skip_first: int = 0,
    font_size: float = 10,
    color: str = "#000000",
    margin_mm: float = 10,
) -> ToolResult:
    """
    Numera páginas (ou adiciona cabeçalho/rodapé).

    Campos do modelo: {n} página, {total} total, {arquivo} nome do arquivo, {data} data atual.
    """
    rgb, margin, today = hex_to_rgb(color), float(margin_mm) * MM, date.today().strftime("%d/%m/%Y")
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Numerando {path.name}")
        with opened(path) as doc:
            numbered = range(int(skip_first), doc.page_count)
            total = len(numbered) + int(start) - 1
            for offset, number in enumerate(numbered):
                page = doc[number]
                label = _format_label(template, n=int(start) + offset, total=total, arquivo=path.stem, data=today)
                stamp, canvas = new_stamp(page)
                width = pymupdf.get_text_length(label, fontname=_BASE_FONT, fontsize=font_size)
                box = anchor_rect(canvas.rect, (width, font_size), position, margin)
                canvas.insert_text((box.x0, box.y1 - font_size * 0.2), label, fontname=_BASE_FONT, fontsize=font_size, color=rgb)
                stamp_page(page, stamp)
            outputs.append(save_pdf(doc, job.output_file(path, "numerado")))
    return ToolResult(outputs)


def _format_label(template: str, **values) -> str:
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError) as error:
        raise ValidationError(f"Modelo inválido: {error}. Campos disponíveis: {{n}}, {{total}}, {{arquivo}}, {{data}}", field="template") from error


def overlay(job: JobContext, files: Sequence[Path], overlay_file: str = "", mode: str = "foreground", repeat: str = "first") -> ToolResult:
    """Sobrepõe (ou coloca ao fundo) as páginas de outro PDF — ex.: papel timbrado."""
    if not overlay_file:
        raise ValidationError("Selecione o PDF de sobreposição.", field="overlay_file")
    outputs = []
    with opened(overlay_file) as original:
        layer = flattened_copy(original)
        for index, path in enumerate(files):
            job.progress(index, len(files), f"Sobrepondo em {path.name}")
            with opened(path) as doc:
                for page in doc:
                    if repeat == "first":
                        source = 0
                    elif repeat == "cycle":
                        source = page.number % layer.page_count
                    elif page.number < layer.page_count:
                        source = page.number
                    else:
                        continue
                    stamp_page(page, layer, source, overlay=mode == "foreground")
                outputs.append(save_pdf(doc, job.output_file(path, "sobreposto")))
    return ToolResult(outputs)


def crop(job: JobContext, files: Sequence[Path], mode: str = "auto", top: float = 10, bottom: float = 10, left: float = 10, right: float = 10, padding: float = 5, pages: str = "") -> ToolResult:
    """Recorta margens fixas (mm) ou automaticamente até o conteúdo visível."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Recortando {path.name}")
        with opened(path) as doc:
            for number in parse_pages(pages, doc.page_count):
                page = doc[number]
                if mode == "auto":
                    visible = _content_bbox(page)
                    if visible is None:
                        continue
                    visible = visible + (-padding * MM, -padding * MM, padding * MM, padding * MM)
                else:
                    visible = page.rect + (left * MM, top * MM, -right * MM, -bottom * MM)
                set_visible_cropbox(page, visible)
            outputs.append(save_pdf(doc, job.output_file(path, "recortado")))
    return ToolResult(outputs)


def _content_bbox(page: pymupdf.Page, dpi: int = 50):
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, annots=True)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    bbox = image.point(lambda value: 255 if value < 235 else 0).getbbox()
    if not bbox:
        return None
    scale = 72 / dpi
    return pymupdf.Rect(*(value * scale for value in bbox))


def set_visible_cropbox(page: pymupdf.Page, visible: pymupdf.Rect) -> None:
    """Define a área visível usando coordenadas da página como exibida (já rotacionada)."""
    visible = visible & page.rect
    if visible.is_empty or visible.width < 10 or visible.height < 10:
        raise ValidationError(f"O recorte da página {page.number + 1} ficaria vazio. Reduza as margens.", field="margins")
    unrotated = (visible * page.derotation_matrix).normalize()
    origin = page.cropbox.tl
    page.set_cropbox((unrotated + (origin.x, origin.y, origin.x, origin.y)) & page.mediabox)


def resize(job: JobContext, files: Sequence[Path], paper: str = "A4", orientation: str = "auto", width_mm: float = 210, height_mm: float = 297, margin_mm: float = 0) -> ToolResult:
    """Altera o tamanho das páginas ajustando o conteúdo proporcionalmente."""
    outputs = []
    margin = float(margin_mm) * MM
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Redimensionando {path.name}")
        with opened(path) as original:
            src = flattened_copy(original)
            out = pymupdf.open()
            for page in src:
                size = _target_size(paper, orientation, page.rect, width_mm, height_mm)
                target = out.new_page(width=size.width, height=size.height)
                target.show_pdf_page(target.rect + (margin, margin, -margin, -margin), src, page.number)
            outputs.append(save_pdf(out, job.output_file(path, paper.lower() if paper != "custom" else "redimensionado")))
    return ToolResult(outputs)


def _target_size(paper: str, orientation: str, page: pymupdf.Rect, width_mm: float, height_mm: float) -> pymupdf.Rect:
    if paper == "custom":
        return pymupdf.Rect(0, 0, float(width_mm) * MM, float(height_mm) * MM)
    if orientation == "auto":
        orientation = "landscape" if page.width > page.height else "portrait"
    return paper_rect(paper, orientation)


def document_info(job: JobContext, files: Sequence[Path], **metadata: str) -> ToolResult:
    """Altera título, autor, assunto, palavras-chave, criador e produtor."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Atualizando {path.name}")
        with opened(path) as doc:
            current = {key: doc.metadata.get(key) or "" for key in METADATA_KEYS + ("creationDate", "modDate")}
            current.update({key: value for key, value in metadata.items() if key in METADATA_KEYS})
            current["modDate"] = pymupdf.get_pdf_now()
            doc.set_metadata(current)
            outputs.append(save_pdf(doc, job.output_file(path, "info")))
    return ToolResult(outputs)


def document_info_prefill(path: Path) -> dict:
    with opened(path) as doc:
        return {key: doc.metadata.get(key) or "" for key in METADATA_KEYS}


def flatten(job: JobContext, files: Sequence[Path], annots: bool = True, widgets: bool = True) -> ToolResult:
    """Incorpora anotações e campos de formulário ao conteúdo (deixam de ser editáveis)."""
    if not (annots or widgets):
        raise ValidationError("Marque ao menos uma opção.", field="annots")
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Achatando {path.name}")
        with opened(path) as doc:
            doc.bake(annots=annots, widgets=widgets)
            outputs.append(save_pdf(doc, job.output_file(path, "achatado")))
    return ToolResult(outputs)
