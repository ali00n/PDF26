"""Conversões para PDF: imagens, texto/Markdown, documentos Office, EPUB/SVG/XPS e HTML."""

from __future__ import annotations

import html
import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

import pymupdf
from PIL import Image, ImageOps

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import DependencyError, PDFError, ValidationError
from ...utils.logger import get_logger
from . import externals
from .common import MM, paper_rect, register_heif, save_pdf

logger = get_logger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".heic", ".heif", ".ico"}
TEXT_EXTENSIONS = {".txt", ".log", ".csv", ".json", ".xml", ".ini", ".py", ".sql"}
MARKDOWN_EXTENSIONS = {".md", ".markdown"}
MUPDF_EXTENSIONS = {".svg", ".epub", ".xps", ".oxps", ".fb2", ".cbz", ".mobi"}
HTML_EXTENSIONS = {".html", ".htm", ".mht", ".mhtml"}
WORD_EXTENSIONS = {".doc", ".docx", ".docm", ".rtf", ".odt", ".wpd"}
EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".ods"}
POWERPOINT_EXTENSIONS = {".ppt", ".pptx", ".pptm", ".odp", ".pps", ".ppsx"}
OTHER_OFFICE_EXTENSIONS = {".pub", ".vsd", ".vsdx", ".odg"}
OFFICE_EXTENSIONS = WORD_EXTENSIONS | EXCEL_EXTENSIONS | POWERPOINT_EXTENSIONS | OTHER_OFFICE_EXTENSIONS

_TEXT_CSS = "body{{font-family:{font};font-size:{size}pt;line-height:1.35}} p{{margin:0 0 6pt 0;white-space:pre-wrap}}"
_MARKDOWN_CSS = (
    "body{{font-family:{font};font-size:{size}pt;line-height:1.4}} h1{{font-size:1.8em}} h2{{font-size:1.45em}} h3{{font-size:1.2em}}"
    " table{{border-collapse:collapse;margin:6pt 0}} td,th{{border:1px solid #999;padding:2pt 5pt}} th{{background:#eee}}"
    " pre,code{{font-family:monospace;background:#f3f3f3}} pre{{white-space:pre-wrap;padding:6pt}} blockquote{{color:#555;margin-left:12pt}}"
)
_OFFICE_TIMEOUT = 300
_EXIF_ORIENTATION = 0x0112
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def images_to_pdf(job: JobContext, files: Sequence[Path], paper: str = "A4", orientation: str = "auto", margin_mm: float = 10, fit: str = "fit", single_file: bool = True) -> ToolResult:
    """Cria PDF a partir de imagens (JPG, PNG, HEIC, WEBP, TIFF...), corrigindo a orientação EXIF."""
    outputs = []
    out = pymupdf.open()
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Adicionando {path.name}")
        add_image_pages(out, path, paper, orientation, float(margin_mm) * MM, fit)
        if not single_file:
            outputs.append(save_pdf(out, job.output_file(path)))
            out = pymupdf.open()
    if single_file:
        outputs.append(save_pdf(out, job.output_file(files[0], "imagens" if len(files) > 1 else "")))
    return ToolResult(outputs)


def add_image_pages(out: pymupdf.Document, path: Path, paper: str = "image", orientation: str = "auto", margin: float = 0, fit: str = "fit") -> None:
    """Adiciona uma página por quadro da imagem (TIFF/GIF com várias páginas geram várias)."""
    for data, (width_px, height_px), dpi in _image_frames(path):
        natural = pymupdf.Rect(0, 0, width_px * 72 / dpi, height_px * 72 / dpi)
        if paper == "image":
            sheet = natural + (0, 0, 2 * margin, 2 * margin)
        else:
            chosen = orientation if orientation != "auto" else ("landscape" if width_px > height_px else "portrait")
            sheet = paper_rect(paper, chosen)
        page = out.new_page(width=sheet.width, height=sheet.height)
        area = page.rect + (margin, margin, -margin, -margin)
        if fit == "original" and natural.width <= area.width and natural.height <= area.height:
            x0, y0 = area.x0 + (area.width - natural.width) / 2, area.y0 + (area.height - natural.height) / 2
            area = pymupdf.Rect(x0, y0, x0 + natural.width, y0 + natural.height)
        page.insert_image(area, stream=data, keep_proportion=True)


def _image_frames(path: Path) -> List[Tuple[bytes, Tuple[int, int], float]]:
    """(bytes, tamanho px, dpi) de cada quadro. JPEG sem rotação EXIF é reaproveitado sem recompressão."""
    register_heif()
    frames = []
    try:
        with Image.open(path) as image:
            dpi = float((image.info.get("dpi") or (96, 96))[0] or 96)
            dpi = dpi if dpi >= 30 else 96.0
            if image.format == "JPEG" and image.getexif().get(_EXIF_ORIENTATION, 1) <= 1:
                return [(path.read_bytes(), image.size, dpi)]
            frame_count = getattr(image, "n_frames", 1) if image.format == "TIFF" else 1  # TIFF multipágina; GIF/MPO só o 1º quadro
            for frame_index in range(frame_count):
                image.seek(frame_index)
                frame = ImageOps.exif_transpose(image.copy())
                frames.append((_encode(frame), frame.size, dpi))
    except Exception as error:
        raise PDFError(f"Imagem inválida ou não suportada: '{path.name}' ({error})") from error
    return frames


def _encode(image: Image.Image) -> bytes:
    """PNG para imagens com transparência/paleta/tons de cinza; JPEG para fotos."""
    buffer = io.BytesIO()
    if image.mode in ("RGBA", "LA", "P", "1", "L", "I;16"):
        image.save(buffer, format="PNG", optimize=True)
    else:
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def text_to_pdf(job: JobContext, files: Sequence[Path], font: str = "sans-serif", font_size: float = 11, paper: str = "A4", margin_mm: float = 20) -> ToolResult:
    """Converte arquivos .txt e .md (Markdown com títulos, listas e tabelas) em PDF."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Convertendo {path.name}")
        target = job.output_file(path)
        if path.suffix.lower() in MARKDOWN_EXTENSIONS:
            markdown_file_to_pdf(path, target, font, font_size, paper, margin_mm)
        else:
            text_file_to_pdf(path, target, font, font_size, paper, margin_mm)
        outputs.append(target)
    return ToolResult(outputs)


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def text_file_to_pdf(path: Path, target: Path, font: str = "sans-serif", font_size: float = 11, paper: str = "A4", margin_mm: float = 20) -> Path:
    return plain_text_to_pdf(read_text(path), target, font, font_size, paper, margin_mm)


def plain_text_to_pdf(text: str, target: Path, font: str = "sans-serif", font_size: float = 11, paper: str = "A4", margin_mm: float = 20, title: str = "") -> Path:
    paragraphs = "".join(f"<p>{html.escape(line) or '&nbsp;'}</p>" for line in text.splitlines())
    heading = f"<h1>{html.escape(title)}</h1>" if title else ""
    return html_to_pdf_story(heading + paragraphs, target, _TEXT_CSS.format(font=font, size=font_size), paper, margin_mm)


def markdown_file_to_pdf(path: Path, target: Path, font: str = "sans-serif", font_size: float = 11, paper: str = "A4", margin_mm: float = 20) -> Path:
    try:
        import markdown
    except ImportError as error:
        raise DependencyError("Pacote 'markdown' não instalado. Execute: pip install markdown", dependency="markdown") from error
    body = markdown.markdown(read_text(path), extensions=["tables", "fenced_code", "sane_lists"])
    return html_to_pdf_story(body, target, _MARKDOWN_CSS.format(font=font, size=font_size), paper, margin_mm)


def html_to_pdf_story(body: str, target: Path, css: str, paper: str = "A4", margin_mm: float = 20) -> Path:
    """Paginação automática de HTML simples com o motor Story do MuPDF."""
    mediabox = paper_rect(paper)
    margin = float(margin_mm) * MM
    where = mediabox + (margin, margin, -margin, -margin)
    story = pymupdf.Story(html=body, user_css=css)
    writer = pymupdf.DocumentWriter(str(target))
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return target


def office_to_pdf(job: JobContext, files: Sequence[Path]) -> ToolResult:
    """Word, Excel, PowerPoint, Publisher e LibreOffice para PDF (usa o Microsoft Office instalado ou o LibreOffice)."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Convertendo {path.name}")
        outputs.append(office_file_to_pdf(path, job.output_file(path)))
    return ToolResult(outputs)


def office_file_to_pdf(path: Path, target: Path) -> Path:
    errors = []
    if externals.office_available() and path.suffix.lower() in WORD_EXTENSIONS | EXCEL_EXTENSIONS | POWERPOINT_EXTENSIONS | {".pub"}:
        try:
            return _microsoft_office(path.resolve(), target.resolve())
        except Exception as error:
            logger.warning(f"Microsoft Office falhou para {path.name}: {error}")
            errors.append(f"Microsoft Office: {error}")
    soffice = externals.find_soffice()
    if soffice:
        return _libreoffice(soffice, path, target)
    if errors:
        raise PDFError(f"Falha ao converter '{path.name}'. {' '.join(errors)}")
    raise DependencyError("Para converter documentos Office instale o Microsoft Office (com pywin32) ou o LibreOffice.", dependency="office")


def _microsoft_office(path: Path, target: Path) -> Path:
    import pythoncom
    import win32com.client

    suffix = path.suffix.lower()
    pythoncom.CoInitialize()
    app = None
    try:
        if suffix in WORD_EXTENSIONS:
            app = win32com.client.DispatchEx("Word.Application")
            app.Visible, app.DisplayAlerts = False, 0
            document = app.Documents.Open(str(path), ReadOnly=True, AddToRecentFiles=False, ConfirmConversions=False)
            document.ExportAsFixedFormat(str(target), 17)  # wdExportFormatPDF
            document.Close(False)
        elif suffix in EXCEL_EXTENSIONS:
            app = win32com.client.DispatchEx("Excel.Application")
            app.Visible, app.DisplayAlerts = False, False
            workbook = app.Workbooks.Open(str(path), ReadOnly=True)
            workbook.ExportAsFixedFormat(0, str(target))  # xlTypePDF
            workbook.Close(False)
        elif suffix in POWERPOINT_EXTENSIONS:
            app = win32com.client.DispatchEx("PowerPoint.Application")
            presentation = app.Presentations.Open(str(path), ReadOnly=True, WithWindow=False)
            presentation.SaveAs(str(target), 32)  # ppSaveAsPDF
            presentation.Close()
        else:
            app = win32com.client.DispatchEx("Publisher.Application")
            publication = app.Open(str(path), True, False)
            publication.ExportAsFixedFormat(2, str(target))  # pbFixedFormatTypePDF
            publication.Close()
    finally:
        if app is not None:
            app.Quit()
        pythoncom.CoUninitialize()
    if not target.exists():
        raise PDFError(f"O Office não gerou o PDF de '{path.name}'.")
    return target


def _libreoffice(soffice: str, path: Path, target: Path) -> Path:
    with tempfile.TemporaryDirectory() as temp:
        profile = (Path(temp) / "profile").as_uri()
        command = [soffice, "--headless", "--norestore", "--nolockcheck", f"-env:UserInstallation={profile}", "--convert-to", "pdf", "--outdir", temp, str(path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=_OFFICE_TIMEOUT, creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired as error:
            raise PDFError(f"LibreOffice excedeu {_OFFICE_TIMEOUT}s ao converter '{path.name}'.") from error
        produced = Path(temp) / f"{path.stem}.pdf"
        if not produced.exists():
            raise PDFError(f"LibreOffice não converteu '{path.name}': {(result.stderr or result.stdout).strip()[:400]}")
        shutil.move(str(produced), target)
    return target


def mupdf_file_to_pdf(path: Path, target: Path) -> Path:
    """SVG, EPUB, XPS, FB2, CBZ e MOBI via conversão nativa do MuPDF."""
    try:
        with pymupdf.open(path) as source:
            data = source.convert_to_pdf()
    except Exception as error:
        raise PDFError(f"Não foi possível converter '{path.name}': {error}") from error
    with pymupdf.open("pdf", data) as pdf:
        return save_pdf(pdf, target)


def convert_any(job: JobContext, files: Sequence[Path], merge: bool = False) -> ToolResult:
    """Converte qualquer formato suportado em PDF; opcionalmente junta tudo em um único arquivo."""
    converted: List[Path] = []
    temp_dir = Path(tempfile.mkdtemp(prefix="pdf26_")) if merge else None
    try:
        for index, path in enumerate(files):
            job.progress(index, len(files), f"Convertendo {path.name}")
            target = (temp_dir / f"{index:04d}.pdf") if temp_dir else job.output_file(path)
            converted.append(convert_file(path, target))
        if not merge:
            return ToolResult(converted)
        out = pymupdf.open()
        for path in converted:
            with pymupdf.open(path) as part:
                out.insert_pdf(part)
        return ToolResult([save_pdf(out, job.output_file(files[0], "convertido"))])
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def convert_file(path: Path, target: Path) -> Path:
    suffix = path.suffix.lower()
    for extensions, converter in _CONVERTERS:
        if suffix in extensions:
            return converter(path, target)
    raise ValidationError(f"Formato não suportado: '{path.name}'.", field="files")


def _copy_pdf(path: Path, target: Path) -> Path:
    shutil.copyfile(path, target)
    return target


def _image_file_to_pdf(path: Path, target: Path) -> Path:
    out = pymupdf.open()
    add_image_pages(out, path)
    return save_pdf(out, target)


def _html_file_to_pdf(path: Path, target: Path) -> Path:
    from .web import html_file_to_pdf

    return html_file_to_pdf(path, target)


_CONVERTERS: Tuple[Tuple[set, Callable[[Path, Path], Path]], ...] = (
    ({".pdf"}, _copy_pdf),
    (IMAGE_EXTENSIONS, _image_file_to_pdf),
    (MARKDOWN_EXTENSIONS, markdown_file_to_pdf),
    (TEXT_EXTENSIONS, text_file_to_pdf),
    (MUPDF_EXTENSIONS, mupdf_file_to_pdf),
    (HTML_EXTENSIONS, _html_file_to_pdf),
    (OFFICE_EXTENSIONS, office_file_to_pdf),
)
SUPPORTED_EXTENSIONS = sorted(set().union(*(extensions for extensions, _ in _CONVERTERS)))
