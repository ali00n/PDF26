"""Criação de conteúdo: escrever PDF, PDF em branco, QR Code e conversão de imagens."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pymupdf
from PIL import Image, ImageOps

from ...domain.job import JobContext, ToolResult, safe_filename
from ...utils.exceptions import DependencyError, PDFError, ValidationError
from .common import paper_rect, register_heif, save_pdf
from .convert_to_pdf import plain_text_to_pdf

IMAGE_TARGETS = {"jpg": ("JPEG", ".jpg"), "png": ("PNG", ".png"), "webp": ("WEBP", ".webp"), "tiff": ("TIFF", ".tiff"), "bmp": ("BMP", ".bmp"), "ico": ("ICO", ".ico")}


def write_pdf(job: JobContext, files: Sequence[Path], title: str = "", content: str = "", font: str = "sans-serif", font_size: float = 11, paper: str = "A4", margin_mm: float = 20) -> ToolResult:
    """Cria um PDF a partir de texto digitado (cartas, ofícios, relatórios simples)."""
    if not content.strip():
        raise ValidationError("Digite o conteúdo do documento.", field="content")
    target = job.output_file(name=safe_filename(title or "documento"))
    plain_text_to_pdf(content, target, font, float(font_size), paper, float(margin_mm), title=title)
    return ToolResult([target])


def blank_pdf(job: JobContext, files: Sequence[Path], pages: int = 1, paper: str = "A4", orientation: str = "portrait") -> ToolResult:
    """PDF com páginas em branco."""
    rect = paper_rect(paper, orientation)
    doc = pymupdf.open()
    for _ in range(int(pages)):
        doc.new_page(width=rect.width, height=rect.height)
    return ToolResult([save_pdf(doc, job.output_file(name=f"em_branco_{paper}"))])


def qr_code(
    job: JobContext,
    files: Sequence[Path],
    content: str = "",
    name: str = "qrcode",
    error_level: str = "M",
    box_size: int = 12,
    border: int = 4,
    fg: str = "#000000",
    bg: str = "#FFFFFF",
    as_pdf: bool = False,
) -> ToolResult:
    """Gera QR Code em PNG (e opcionalmente PDF) para link, texto, Pix copia-e-cola, Wi-Fi etc."""
    try:
        import qrcode
    except ImportError as error:
        raise DependencyError("Pacote 'qrcode' não instalado. Execute: pip install qrcode[pil]", dependency="qrcode") from error
    if not content.strip():
        raise ValidationError("Informe o conteúdo do QR Code.", field="content")
    qr = qrcode.QRCode(error_correction=getattr(qrcode.constants, f"ERROR_CORRECT_{error_level}"), box_size=int(box_size), border=int(border))
    qr.add_data(content.strip())
    qr.make(fit=True)
    image = qr.make_image(fill_color=fg, back_color=bg).convert("RGB")
    png = job.output_file(name=safe_filename(name or "qrcode"), ext=".png")
    image.save(png)
    outputs = [png]
    if as_pdf:
        doc = pymupdf.open()
        page = doc.new_page(width=image.width * 0.75, height=image.height * 0.75)
        page.insert_image(page.rect, filename=str(png))
        outputs.append(save_pdf(doc, png.with_suffix(".pdf")))
    return ToolResult(outputs)


def convert_images(job: JobContext, files: Sequence[Path], fmt: str = "jpg", quality: int = 90, max_side: int = 0) -> ToolResult:
    """Converte imagens entre formatos (HEIC/WEBP/PNG/JPG/TIFF/BMP/ICO), corrigindo rotação e opcionalmente reduzindo."""
    register_heif()
    pil_format, extension = IMAGE_TARGETS[fmt]
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Convertendo {path.name}")
        try:
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).copy()
        except Exception as error:
            raise PDFError(f"Imagem inválida: '{path.name}' ({error})") from error
        if int(max_side) > 0:
            image.thumbnail((int(max_side), int(max_side)), Image.LANCZOS)
        if pil_format in ("JPEG", "BMP") and image.mode not in ("RGB", "L"):
            image = _flatten_alpha(image)
        options = {"quality": int(quality)} if pil_format in ("JPEG", "WEBP") else {}
        if pil_format == "ICO":
            options = {"sizes": [(size, size) for size in (16, 32, 48, 64, 128, 256) if size <= max(image.size)]}
        target = job.output_file(path, ext=extension)
        image.save(target, pil_format, **options)
        outputs.append(target)
    return ToolResult(outputs)


def _flatten_alpha(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGB", rgba.size, "white")
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background
