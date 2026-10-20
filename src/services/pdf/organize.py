"""Serviços de organização: juntar, dividir, girar, remover/extrair páginas, montagem e imposição."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pymupdf

from ...domain.job import JobContext, ToolResult, safe_filename
from ...utils.exceptions import PDFError, ValidationError
from .common import MM, flattened_copy, opened, page_is_blank, paper_rect, parse_page_groups, parse_pages, require_count, save_pdf

NUP_GRID: Dict[int, Tuple[int, int]] = {2: (2, 1), 4: (2, 2), 6: (3, 2), 8: (4, 2), 9: (3, 3), 16: (4, 4)}  # (colunas, linhas) em paisagem


def merge(job: JobContext, files: Sequence[Path], bookmarks: bool = True) -> ToolResult:
    """Junta PDFs na ordem recebida, preservando marcadores e (opcional) criando um por arquivo."""
    require_count(files, 2, what="PDFs")
    out = pymupdf.open()
    toc: List[list] = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Juntando {path.name}")
        with opened(path) as src:
            offset = out.page_count
            out.insert_pdf(src)
            level_shift = 1 if bookmarks else 0
            if bookmarks:
                toc.append([1, path.stem, offset + 1])
            toc.extend([level + level_shift, title, page + offset] for level, title, page, *_ in src.get_toc(simple=True) if page > 0)
    out.set_toc(normalize_toc(toc))
    target = save_pdf(out, job.output_file(files[0], "unido"))
    return ToolResult([target], message=f"{len(files)} arquivos unidos ({out.page_count} páginas).")


def split(job: JobContext, files: Sequence[Path], mode: str = "each", every: int = 1, ranges: str = "") -> ToolResult:
    """Divide cada PDF em várias partes: página a página, a cada N páginas, por intervalos ou por marcadores."""
    outputs: List[Path] = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Dividindo {path.name}")
        with opened(path) as src:
            parts = _split_plan(src, mode, int(every), ranges)
            folder = job.output_folder(path, "dividido")
            width = len(str(len(parts)))
            for number, (label, pages) in enumerate(parts, 1):
                job.check_cancelled()
                part = pymupdf.open()
                for page in pages:
                    part.insert_pdf(src, from_page=page, to_page=page)
                name = f"{path.stem}_{str(number).zfill(width)}" + (f" - {safe_filename(label)}" if label else "")
                outputs.append(save_pdf(part, job.output_file(name=name, directory=folder)))
    return ToolResult(outputs, message=f"{len(outputs)} arquivos gerados.")


def _split_plan(src: pymupdf.Document, mode: str, every: int, ranges: str) -> List[Tuple[str, List[int]]]:
    count = src.page_count
    if mode == "each":
        return [("", [page]) for page in range(count)]
    if mode == "every":
        if every < 1:
            raise ValidationError("Informe um número de páginas maior que zero.", field="every")
        return [("", list(range(start, min(start + every, count)))) for start in range(0, count, every)]
    if mode == "ranges":
        return [("", group) for group in parse_page_groups(ranges, count)]
    if mode == "bookmarks":
        starts = sorted({(page - 1, title) for level, title, page, *_ in src.get_toc(simple=True) if level == 1 and page > 0})
        if not starts:
            raise PDFError("O PDF não possui marcadores de primeiro nível.")
        if starts[0][0] > 0:
            starts.insert(0, (0, "Início"))
        bounds = [page for page, _ in starts[1:]] + [count]
        return [(title, list(range(page, end))) for (page, title), end in zip(starts, bounds) if end > page]
    raise ValidationError(f"Modo de divisão desconhecido: {mode}", field="mode")


def rotate(job: JobContext, files: Sequence[Path], angle: str = "90", which: str = "all", pages: str = "") -> ToolResult:
    """Gira páginas em 90/180/270 graus (todas, pares, ímpares ou seleção)."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Girando {path.name}")
        with opened(path) as doc:
            for number in _select(doc, which, pages):
                page = doc[number]
                page.set_rotation((page.rotation + int(angle)) % 360)
            outputs.append(save_pdf(doc, job.output_file(path, "girado")))
    return ToolResult(outputs)


def _select(doc: pymupdf.Document, which: str, pages: str) -> List[int]:
    if which == "odd":
        return list(range(0, doc.page_count, 2))
    if which == "even":
        return list(range(1, doc.page_count, 2))
    if which == "custom":
        return parse_pages(pages, doc.page_count)
    return list(range(doc.page_count))


def remove_pages(job: JobContext, files: Sequence[Path], pages: str = "", remove_blank: bool = False) -> ToolResult:
    """Remove as páginas informadas e/ou páginas em branco."""
    if not pages.strip() and not remove_blank:
        raise ValidationError("Informe as páginas a remover ou marque 'Remover páginas em branco'.", field="pages")
    outputs, report = [], []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Analisando {path.name}")
        with opened(path) as doc:
            drop = set(parse_pages(pages, doc.page_count)) if pages.strip() else set()
            if remove_blank:
                drop |= {number for number in range(doc.page_count) if page_is_blank(doc[number])}
            keep = [number for number in range(doc.page_count) if number not in drop]
            if not keep:
                raise PDFError(f"Todas as páginas de '{path.name}' seriam removidas.")
            doc.select(keep)
            outputs.append(save_pdf(doc, job.output_file(path, "paginas_removidas")))
            report.append(f"{path.name}: {len(drop)} página(s) removida(s)")
    return ToolResult(outputs, text="\n".join(report))


def extract_pages(job: JobContext, files: Sequence[Path], pages: str = "1", separate: bool = False) -> ToolResult:
    """Extrai páginas para um novo PDF (ou um arquivo por página)."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Extraindo de {path.name}")
        with opened(path) as src:
            selection = parse_pages(pages, src.page_count, unique=False)
            if separate:
                folder = job.output_folder(path, "paginas")
                for number in selection:
                    part = pymupdf.open()
                    part.insert_pdf(src, from_page=number, to_page=number)
                    outputs.append(save_pdf(part, job.output_file(name=f"{path.stem}_p{number + 1}", directory=folder)))
            else:
                src.select(selection)
                outputs.append(save_pdf(src, job.output_file(path, "extraido")))
    return ToolResult(outputs)


@dataclass(frozen=True)
class PageRef:
    """Página na montagem visual: documento de origem, índice da página e rotação extra."""

    source: int
    page: int
    rotation: int = 0
    blank: bool = False


def assemble(job: JobContext, sources: Sequence[Path], pages: Sequence[PageRef], output: Path) -> ToolResult:
    """Gera um PDF a partir da lista de páginas montada no organizador visual."""
    if not pages:
        raise ValidationError("Não há páginas para salvar.", field="pages")
    docs = [pymupdf.open(path) for path in sources]
    try:
        out = pymupdf.open()
        for index, ref in enumerate(pages):
            job.progress(index, len(pages), "Montando páginas")
            if ref.blank:
                size = out[-1].rect if out.page_count else paper_rect("A4")
                out.new_page(width=size.width, height=size.height)
            else:
                out.insert_pdf(docs[ref.source], from_page=ref.page, to_page=ref.page)
            if ref.rotation:
                page = out[-1]
                page.set_rotation((page.rotation + ref.rotation) % 360)
        return ToolResult([save_pdf(out, output)], message=f"{len(pages)} páginas salvas.")
    finally:
        for doc in docs:
            doc.close()


def pages_per_sheet(job: JobContext, files: Sequence[Path], per_sheet: str = "2", paper: str = "A4", orientation: str = "auto", margin_mm: float = 5, border: bool = False) -> ToolResult:
    """Imposição N-up: várias páginas por folha."""
    columns, rows = NUP_GRID[int(per_sheet)]
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Montando {path.name}")
        with opened(path) as original:
            src = flattened_copy(original)
            sheet = _best_sheet(paper, orientation, src[0].rect, columns, rows)
            cols, rws = (columns, rows) if sheet.width >= sheet.height else (rows, columns)
            out = pymupdf.open()
            cell_w, cell_h = sheet.width / cols, sheet.height / rws
            margin = float(margin_mm) * MM
            for number in range(src.page_count):
                slot = number % (cols * rws)
                if slot == 0:
                    target = out.new_page(width=sheet.width, height=sheet.height)
                x0, y0 = (slot % cols) * cell_w, (slot // cols) * cell_h
                inner = pymupdf.Rect(x0 + margin, y0 + margin, x0 + cell_w - margin, y0 + cell_h - margin)
                target.show_pdf_page(inner, src, number)
                if border:
                    target.draw_rect(inner, color=(0.6, 0.6, 0.6), width=0.5)
            outputs.append(save_pdf(out, job.output_file(path, f"{per_sheet}_por_folha")))
    return ToolResult(outputs)


def _best_sheet(paper: str, orientation: str, page: pymupdf.Rect, columns: int, rows: int) -> pymupdf.Rect:
    if orientation in ("portrait", "landscape"):
        return paper_rect(paper, orientation)

    def scale(sheet: pymupdf.Rect) -> float:
        cols, rws = (columns, rows) if sheet.width >= sheet.height else (rows, columns)
        return min(sheet.width / cols / page.width, sheet.height / rws / page.height)

    return max((paper_rect(paper, "portrait"), paper_rect(paper, "landscape")), key=scale)


def booklet(job: JobContext, files: Sequence[Path], paper: str = "A4") -> ToolResult:
    """Livreto para impressão frente e verso: dobrar ao meio e grampear."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Montando livreto {path.name}")
        with opened(path) as original:
            src = flattened_copy(original)
            total = -(-src.page_count // 4) * 4
            sheet = paper_rect(paper, "landscape")
            half = sheet.width / 2
            out = pymupdf.open()
            for side in _booklet_order(total):
                target = out.new_page(width=sheet.width, height=sheet.height)
                for slot, number in enumerate(side):
                    if number < src.page_count:
                        target.show_pdf_page(pymupdf.Rect(slot * half, 0, (slot + 1) * half, sheet.height), src, number)
            outputs.append(save_pdf(out, job.output_file(path, "livreto")))
    return ToolResult(outputs, message="Imprima frente e verso virando pela borda curta.")


def _booklet_order(total: int) -> List[Tuple[int, int]]:
    sides = []
    for sheet in range(total // 4):
        sides.append((total - 1 - 2 * sheet, 2 * sheet))
        sides.append((2 * sheet + 1, total - 2 - 2 * sheet))
    return sides


def halve(job: JobContext, files: Sequence[Path], direction: str = "vertical", right_to_left: bool = False) -> ToolResult:
    """Corta cada página em duas metades (ex.: livro escaneado com duas páginas por folha)."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Dividindo páginas de {path.name}")
        with opened(path) as original:
            src = flattened_copy(original)
            out = pymupdf.open()
            for page in src:
                r = page.rect
                if direction == "vertical":
                    halves = [pymupdf.Rect(r.x0, r.y0, r.x0 + r.width / 2, r.y1), pymupdf.Rect(r.x0 + r.width / 2, r.y0, r.x1, r.y1)]
                else:
                    halves = [pymupdf.Rect(r.x0, r.y0, r.x1, r.y0 + r.height / 2), pymupdf.Rect(r.x0, r.y0 + r.height / 2, r.x1, r.y1)]
                if right_to_left:
                    halves.reverse()
                for clip in halves:
                    target = out.new_page(width=clip.width, height=clip.height)
                    target.show_pdf_page(target.rect, src, page.number, clip=clip)
            outputs.append(save_pdf(out, job.output_file(path, "metades")))
    return ToolResult(outputs)


def bookmarks(job: JobContext, files: Sequence[Path], mode: str = "edit", toc_text: str = "") -> ToolResult:
    """Edita, cria (um por página) ou remove marcadores. Formato de edição: 'nível | título | página'."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Marcadores de {path.name}")
        with opened(path) as doc:
            if mode == "remove":
                toc = []
            elif mode == "per_page":
                toc = [[1, f"Página {number}", number] for number in range(1, doc.page_count + 1)]
            else:
                toc = parse_toc_text(toc_text, doc.page_count)
            doc.set_toc(toc)
            outputs.append(save_pdf(doc, job.output_file(path, "marcadores")))
    return ToolResult(outputs)


def bookmarks_prefill(path: Path) -> dict:
    with opened(path) as doc:
        return {"toc_text": "\n".join(f"{level} | {title} | {page}" for level, title, page, *_ in doc.get_toc(simple=True))}


def parse_toc_text(text: str, page_count: int) -> List[list]:
    toc = []
    for line_number, line in enumerate(filter(str.strip, (text or "").splitlines()), 1):
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3 or not parts[0].isdigit() or not parts[2].lstrip("-").isdigit():
            raise ValidationError(f"Linha {line_number} inválida: '{line.strip()}'. Use: nível | título | página", field="toc_text")
        level, title, page = int(parts[0]), parts[1], int(parts[2])
        if not 1 <= page <= page_count:
            raise ValidationError(f"Linha {line_number}: página {page} não existe.", field="toc_text")
        toc.append([level, title, page])
    return normalize_toc(toc)


def normalize_toc(toc: List[list]) -> List[list]:
    """Garante a hierarquia exigida pelo PDF: começa no nível 1 e sobe no máximo 1 por vez."""
    previous = 0
    for entry in toc:
        entry[0] = max(1, min(entry[0], previous + 1))
        previous = entry[0]
    return toc


def extract_images(job: JobContext, files: Sequence[Path], min_size: int = 32, to_png: bool = False) -> ToolResult:
    """Extrai as imagens incorporadas (sem perda), ignorando as menores que `min_size` px."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Extraindo imagens de {path.name}")
        with opened(path) as doc:
            folder = job.output_folder(path, "imagens")
            seen = set()
            for page in doc:
                for xref, smask, width, height, *_ in page.get_images(full=True):
                    if xref in seen or min(width, height) < int(min_size):
                        continue
                    seen.add(xref)
                    outputs.append(_save_image(doc, xref, smask, folder / f"p{page.number + 1}_img{xref}", to_png))
            if not seen:
                folder.rmdir()
    return ToolResult(outputs, message=f"{len(outputs)} imagens extraídas.")


def _save_image(doc: pymupdf.Document, xref: int, smask: int, stem: Path, to_png: bool) -> Path:
    if smask or to_png:
        pix = pymupdf.Pixmap(doc, xref)
        if smask:
            pix = pymupdf.Pixmap(pix, pymupdf.Pixmap(doc, smask))
        if pix.colorspace and pix.colorspace.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        target = stem.with_suffix(".png")
        pix.save(target)
        return target
    info = doc.extract_image(xref)
    target = stem.with_suffix(f".{info['ext']}")
    target.write_bytes(info["image"])
    return target
