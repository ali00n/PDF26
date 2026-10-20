"""Serviços de otimização: compressão, tons de cinza, web, OCR, reparo, rasterização e PDF/A."""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pikepdf
import pymupdf

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import PDFError
from . import externals
from .common import human_size, opened, save_pdf

# nível -> (dpi acima do qual reamostrar, dpi alvo, qualidade JPEG)
COMPRESSION_LEVELS: Dict[str, Tuple[int, int, int]] = {
    "low": (220, 200, 85),
    "medium": (160, 144, 70),
    "high": (110, 96, 55),
    "extreme": (80, 72, 40),
}
_SAVE_COMPACT = {"garbage": 4, "deflate": True, "deflate_images": True, "deflate_fonts": True, "clean": True, "use_objstms": 1}
_GS_TIMEOUT = 600


def compress(job: JobContext, files: Sequence[Path], level: str = "medium", grayscale: bool = False, strip_metadata: bool = False) -> ToolResult:
    """Reduz o tamanho reamostrando imagens, subconjuntando fontes e limpando objetos."""
    threshold, target_dpi, quality = COMPRESSION_LEVELS[level]
    outputs, lines = [], []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Comprimindo {path.name}")
        with opened(path) as doc:
            doc.rewrite_images(dpi_threshold=threshold, dpi_target=target_dpi, quality=quality, set_to_gray=grayscale)
            doc.subset_fonts()
            if strip_metadata:
                doc.scrub(
                    metadata=True,
                    xml_metadata=True,
                    attached_files=False,
                    clean_pages=False,
                    embedded_files=False,
                    hidden_text=False,
                    javascript=False,
                    redactions=False,
                    remove_links=False,
                    reset_fields=False,
                    reset_responses=False,
                    thumbnails=True,
                )
            target = save_pdf(doc, job.output_file(path, "comprimido"), **_SAVE_COMPACT)
        before, after = path.stat().st_size, target.stat().st_size
        if after >= before:
            shutil.copyfile(path, target)
            lines.append(f"{path.name}: já estava otimizado ({human_size(before)}).")
        else:
            lines.append(f"{path.name}: {human_size(before)} → {human_size(after)} (−{(1 - after / before) * 100:.0f}%)")
        outputs.append(target)
    return ToolResult(outputs, text="\n".join(lines))


def grayscale(job: JobContext, files: Sequence[Path], method: str = "auto", dpi: int = 200) -> ToolResult:
    """Converte para tons de cinza: Ghostscript preserva texto; rasterização funciona sempre."""
    use_gs = method == "ghostscript" or (method == "auto" and externals.find_ghostscript())
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Convertendo {path.name}")
        target = job.output_file(path, "cinza")
        if use_gs:
            _ghostscript(path, target, ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray", "-dOverrideICC"])
        else:
            _rasterize_file(path, target, int(dpi), gray=True, quality=85)
        outputs.append(target)
    return ToolResult(outputs)


def web_optimize(job: JobContext, files: Sequence[Path]) -> ToolResult:
    """Lineariza o PDF (Fast Web View): a primeira página abre antes do download terminar."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Otimizando {path.name}")
        target = job.output_file(path, "web")
        try:
            with pikepdf.open(path) as pdf:
                pdf.save(target, linearize=True, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate)
        except pikepdf.PasswordError as error:
            raise PDFError(f"'{path.name}' está protegido por senha. Desbloqueie antes.") from error
        outputs.append(target)
    return ToolResult(outputs)


def ocr(job: JobContext, files: Sequence[Path], language: str = "por", dpi: int = 300, skip_text_pages: bool = True) -> ToolResult:
    """Reconhece texto em páginas escaneadas e gera PDF pesquisável (imagem + camada de texto invisível)."""
    tessdata = externals.require_tessdata(language)
    outputs, lines = [], []
    for index, path in enumerate(files):
        with opened(path) as src:
            out = pymupdf.open()
            recognized = 0
            for page in src:
                job.progress(index + page.number / src.page_count, len(files), f"OCR {path.name}: página {page.number + 1}/{src.page_count}")
                if skip_text_pages and page.get_text("text").strip():
                    out.insert_pdf(src, from_page=page.number, to_page=page.number)
                    continue
                pix = page.get_pixmap(dpi=int(dpi))
                with pymupdf.open("pdf", pix.pdfocr_tobytes(language=language, tessdata=tessdata)) as ocr_page:
                    out.insert_pdf(ocr_page)
                recognized += 1
            outputs.append(save_pdf(out, job.output_file(path, "ocr"), garbage=3, deflate=True))
            lines.append(f"{path.name}: {recognized} página(s) reconhecida(s)")
    return ToolResult(outputs, text="\n".join(lines))


def repair(job: JobContext, files: Sequence[Path]) -> ToolResult:
    """Reconstrói a estrutura do PDF (tabela xref, streams e objetos corrompidos)."""
    outputs, lines = [], []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Reparando {path.name}")
        target = job.output_file(path, "reparado")
        try:
            with pymupdf.open(path) as doc:
                data = doc.tobytes(garbage=3, clean=True, deflate=True)
            with pikepdf.open(io.BytesIO(data)) as pdf:
                pdf.save(target)
            lines.append(f"{path.name}: reparado.")
        except Exception:
            try:
                with pikepdf.open(path) as pdf:
                    pdf.save(target)
                lines.append(f"{path.name}: reparado (modo alternativo).")
            except Exception as error:
                raise PDFError(f"Não foi possível reparar '{path.name}': {error}") from error
        outputs.append(target)
    return ToolResult(outputs, text="\n".join(lines))


def rasterize(job: JobContext, files: Sequence[Path], dpi: int = 150, gray: bool = False, quality: int = 85) -> ToolResult:
    """Transforma cada página em imagem (remove texto selecionável, camadas e scripts)."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Rasterizando {path.name}")
        target = job.output_file(path, "rasterizado")
        _rasterize_file(path, target, int(dpi), gray, int(quality), job)
        outputs.append(target)
    return ToolResult(outputs)


def _rasterize_file(path: Path, target: Path, dpi: int, gray: bool, quality: int, job: Optional[JobContext] = None) -> None:
    colorspace = pymupdf.csGRAY if gray else pymupdf.csRGB
    with opened(path) as src:
        out = pymupdf.open()
        for page in src:
            if job:
                job.check_cancelled()
            pix = page.get_pixmap(dpi=dpi, colorspace=colorspace, annots=True)
            target_page = out.new_page(width=page.rect.width, height=page.rect.height)
            target_page.insert_image(target_page.rect, stream=pix.tobytes("jpg", jpg_quality=quality))
        save_pdf(out, target)


def pdfa(job: JobContext, files: Sequence[Path], level: str = "2") -> ToolResult:
    """Converte para PDF/A (arquivamento de longo prazo) usando Ghostscript."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Convertendo {path.name} para PDF/A-{level}b")
        target = job.output_file(path, f"pdfa{level}")
        _ghostscript(path, target, [f"-dPDFA={level}", "-dPDFACompatibilityPolicy=1", "-sColorConversionStrategy=RGB", "-dNOOUTERSAVE"])
        outputs.append(target)
    return ToolResult(outputs)


def _ghostscript(source: Path, target: Path, extra: List[str]) -> None:
    command = [externals.require_ghostscript(), "-dBATCH", "-dNOPAUSE", "-dQUIET", "-dSAFER", "-sDEVICE=pdfwrite", *extra, f"-sOutputFile={target}", str(source)]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=_GS_TIMEOUT, creationflags=creationflags)
    except subprocess.TimeoutExpired as error:
        raise PDFError(f"Ghostscript excedeu {_GS_TIMEOUT}s em '{source.name}'.") from error
    if result.returncode != 0 or not target.exists():
        raise PDFError(f"Ghostscript falhou em '{source.name}': {(result.stderr or result.stdout).strip()[:500]}")
