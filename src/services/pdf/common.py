"""Funções compartilhadas pelos serviços de PDF."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Iterator, List, Optional, Sequence, Tuple

import pymupdf

from ...domain.job import PathLike
from ...utils.exceptions import PDFError, ValidationError

MM = 72 / 25.4  # pontos por milímetro

PAPER_SIZES = {
    "A3": pymupdf.paper_size("a3"),
    "A4": pymupdf.paper_size("a4"),
    "A5": pymupdf.paper_size("a5"),
    "Carta": pymupdf.paper_size("letter"),
    "Ofício": pymupdf.paper_size("legal"),
}
PAPER_CHOICES = tuple((name, name) for name in PAPER_SIZES)

POSITIONS = (
    ("top-left", "Superior esquerda"),
    ("top-center", "Superior centro"),
    ("top-right", "Superior direita"),
    ("middle-left", "Centro esquerda"),
    ("center", "Centro"),
    ("middle-right", "Centro direita"),
    ("bottom-left", "Inferior esquerda"),
    ("bottom-center", "Inferior centro"),
    ("bottom-right", "Inferior direita"),
)

_RANGE_TOKEN = re.compile(r"^(\d*)\s*-\s*(\d*)$")


def open_pdf(path: PathLike, password: Optional[str] = None) -> pymupdf.Document:
    """Abre um PDF validando formato e senha."""
    path = Path(path)
    try:
        doc = pymupdf.open(path)
    except Exception as error:
        raise PDFError(f"Não foi possível abrir '{path.name}': {error}", file=str(path)) from error
    if not doc.is_pdf:
        doc.close()
        raise PDFError(f"'{path.name}' não é um PDF.", file=str(path))
    if doc.needs_pass and not (password and doc.authenticate(password)):
        doc.close()
        hint = "Senha incorreta." if password else "Use a ferramenta 'Desbloquear PDF' ou informe a senha."
        raise PDFError(f"'{path.name}' está protegido por senha. {hint}", file=str(path))
    return doc


def needs_password(path: PathLike) -> bool:
    """True se o PDF exige senha para abrir."""
    try:
        with pymupdf.open(path) as doc:
            return bool(doc.needs_pass)
    except Exception:
        return False


@contextlib.contextmanager
def opened(path: PathLike, password: Optional[str] = None) -> Iterator[pymupdf.Document]:
    doc = open_pdf(path, password)
    try:
        yield doc
    finally:
        doc.close()


def save_pdf(doc: pymupdf.Document, path: Path, **options) -> Path:
    """Salva com limpeza de objetos órfãos e compressão de streams."""
    params = {"garbage": 3, "deflate": True}
    params.update(options)
    try:
        doc.save(path, **params)
    except Exception as error:
        raise PDFError(f"Falha ao salvar '{path.name}': {error}", file=str(path)) from error
    return path


def parse_pages(spec: str, page_count: int, unique: bool = True) -> List[int]:
    """
    Converte uma seleção de páginas (1-based) em índices 0-based.

    Aceita: "1-3, 5, 8-" ; "-4" ; "10-7" (ordem decrescente). Vazio = todas.
    """
    spec = (spec or "").strip()
    if not spec:
        return list(range(page_count))
    pages: List[int] = []
    for token in (part.strip() for part in re.split(r"[,;]", spec)):
        if not token:
            continue
        if token.isdigit():
            start = end = int(token)
        else:
            match = _RANGE_TOKEN.match(token)
            if not match:
                raise ValidationError(f"Seleção de páginas inválida: '{token}'. Use, por exemplo: 1-3, 5, 8-", field="pages")
            start = int(match.group(1)) if match.group(1) else 1
            end = int(match.group(2)) if match.group(2) else page_count
        for number in (start, end):
            if not 1 <= number <= page_count:
                raise ValidationError(f"Página {number} não existe (o documento tem {page_count} páginas).", field="pages")
        step = 1 if end >= start else -1
        pages.extend(index - 1 for index in range(start, end + step, step))
    if unique:
        pages = list(dict.fromkeys(pages))
    return pages


def parse_page_groups(spec: str, page_count: int) -> List[List[int]]:
    """'1-3, 5, 8-10' -> [[0,1,2], [4], [7,8,9]] (cada grupo vira um arquivo)."""
    groups = [parse_pages(token, page_count) for token in re.split(r"[,;]", spec or "") if token.strip()]
    if not groups:
        raise ValidationError("Informe ao menos um intervalo de páginas.", field="ranges")
    return groups


def hex_to_rgb(color: str) -> Tuple[float, float, float]:
    color = (color or "#000000").lstrip("#")
    if len(color) != 6:
        raise ValidationError(f"Cor inválida: #{color}", field="color")
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def paper_rect(paper: str, orientation: str = "portrait") -> pymupdf.Rect:
    width, height = PAPER_SIZES.get(paper, PAPER_SIZES["A4"])
    if orientation == "landscape":
        width, height = height, width
    return pymupdf.Rect(0, 0, width, height)


def anchor_rect(area: pymupdf.Rect, size: Tuple[float, float], position: str, margin: float) -> pymupdf.Rect:
    """Posiciona um retângulo de `size` dentro de `area` conforme uma das 9 posições."""
    width, height = size
    vertical, horizontal = ("middle", "center") if position == "center" else position.split("-", 1)
    x0 = {"left": area.x0 + margin, "center": area.x0 + (area.width - width) / 2, "right": area.x1 - margin - width}[horizontal]
    y0 = {"top": area.y0 + margin, "middle": area.y0 + (area.height - height) / 2, "bottom": area.y1 - margin - height}[vertical]
    return pymupdf.Rect(x0, y0, x0 + width, y0 + height)


def rect_center(rect: pymupdf.Rect) -> pymupdf.Point:
    return pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def stamp_page(page: pymupdf.Page, stamp: pymupdf.Document, stamp_pno: int = 0, overlay: bool = True) -> None:
    """
    Aplica uma página-carimbo (do tamanho visível da página) respeitando a rotação.

    O carimbo é desenhado em coordenadas visíveis; a conversão para o espaço
    não rotacionado do PDF fica centralizada aqui.
    """
    page.show_pdf_page(page.rect * page.derotation_matrix, stamp, stamp_pno, rotate=page.rotation, overlay=overlay)


def new_stamp(page: pymupdf.Page) -> Tuple[pymupdf.Document, pymupdf.Page]:
    """Documento temporário com uma página do tamanho visível de `page`."""
    stamp = pymupdf.open()
    return stamp, stamp.new_page(width=page.rect.width, height=page.rect.height)


def flattened_copy(doc: pymupdf.Document) -> pymupdf.Document:
    """
    Cópia com anotações incorporadas ao conteúdo e rotação removida.

    Necessária antes de compor páginas com `show_pdf_page`, que ignora a
    rotação da página de origem e não desenha anotações.
    """
    copy = pymupdf.open()
    copy.insert_pdf(doc)
    copy.bake(annots=True, widgets=True)
    for page in copy:
        if page.rotation:
            page.remove_rotation()
    return copy


def page_is_blank(page: pymupdf.Page, threshold: float = 0.002) -> bool:
    """Página sem texto e (quase) sem pixels escuros — detecta folhas em branco escaneadas."""
    if page.get_text("text").strip():
        return False
    pix = page.get_pixmap(dpi=30, colorspace=pymupdf.csGRAY)
    dark = sum(pix.samples.count(value) for value in range(0, 200))
    return dark / max(1, pix.width * pix.height) < threshold


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            text = f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            return text.replace(".", ",")
        size /= 1024
    return f"{size:.1f} GB"


def require_count(files: Sequence[Path], minimum: int, maximum: Optional[int] = None, what: str = "arquivos") -> None:
    if len(files) < minimum:
        raise ValidationError(f"Selecione pelo menos {minimum} {what}.", field="files")
    if maximum is not None and len(files) > maximum:
        raise ValidationError(f"Selecione no máximo {maximum} {what}.", field="files")


def register_heif() -> None:
    """Habilita a leitura de HEIC/HEIF (fotos de iPhone) no Pillow, se pillow-heif estiver instalado."""
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()
