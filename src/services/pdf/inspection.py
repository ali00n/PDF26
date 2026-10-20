"""Serviços de visualização e verificação: propriedades, pesquisa, comparação e preferências de exibição."""

from __future__ import annotations

import csv
import difflib
import html
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence

import pikepdf
import pymupdf
from PIL import Image, ImageChops

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import ValidationError
from .common import MM, human_size, opened, require_count, save_pdf

LAYOUTS = (
    ("", "Padrão do leitor"),
    ("SinglePage", "Uma página"),
    ("OneColumn", "Contínua"),
    ("TwoPageLeft", "Duas páginas"),
    ("TwoColumnLeft", "Duas páginas contínuas"),
    ("TwoPageRight", "Duas páginas (capa separada)"),
)
MODES = (("", "Padrão do leitor"), ("UseNone", "Somente documento"), ("UseOutlines", "Painel de marcadores"), ("UseThumbs", "Painel de miniaturas"), ("FullScreen", "Tela cheia"))
VIEWER_FLAGS = ("HideToolbar", "HideMenubar", "HideWindowUI", "FitWindow", "CenterWindow", "DisplayDocTitle")


def info(job: JobContext, files: Sequence[Path]) -> ToolResult:
    """Relatório técnico: versão, criptografia, metadados, tamanhos de página, fontes, imagens, formulários."""
    sections = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Analisando {path.name}")
        with opened(path) as doc:
            meta = doc.metadata
            sizes = Counter(_page_size_label(page.rect) for page in doc)
            fonts = sorted({(font[3], font[1] != "n/a" and font[2] != "Type3") for page in doc for font in page.get_fonts(full=False)})
            images = sum(len(page.get_images()) for page in doc)
            annots = sum(1 for page in doc for _ in page.annots())
            text_pages = sum(1 for page in doc if page.get_text("text").strip())
            lines = [
                f"■ {path.name}",
                f"  Tamanho: {human_size(path.stat().st_size)}",
                f"  Páginas: {doc.page_count} ({text_pages} com texto, {doc.page_count - text_pages} sem texto/escaneadas)",
                f"  Formato: {meta.get('format') or '-'}   Linearizado: {'sim' if _is_linearized(path) else 'não'}",
                f"  Criptografia: {meta.get('encryption') or 'nenhuma'}",
                f"  Título: {meta.get('title') or '-'}",
                f"  Autor: {meta.get('author') or '-'}",
                f"  Assunto: {meta.get('subject') or '-'}",
                f"  Palavras-chave: {meta.get('keywords') or '-'}",
                f"  Criador: {meta.get('creator') or '-'}   Produtor: {meta.get('producer') or '-'}",
                f"  Criado: {_pdf_date(meta.get('creationDate'))}   Modificado: {_pdf_date(meta.get('modDate'))}",
                "  Tamanhos de página: " + ", ".join(f"{label} ×{count}" for label, count in sizes.most_common()),
                f"  Imagens: {images}   Anotações: {annots}   Marcadores: {len(doc.get_toc())}   Anexos: {doc.embfile_count()}",
                f"  Formulário: {'sim' if doc.is_form_pdf else 'não'}",
                f"  Fontes ({len(fonts)}): " + (", ".join(f"{name}{'' if embedded else ' (não incorporada)'}" for name, embedded in fonts) or "nenhuma"),
            ]
        sections.append("\n".join(lines))
    return ToolResult(text="\n\n".join(sections))


def _page_size_label(rect: pymupdf.Rect) -> str:
    width_mm, height_mm = rect.width / MM, rect.height / MM
    for name, (w, h) in {"A3": (297, 420), "A4": (210, 297), "A5": (148, 210), "Carta": (216, 279), "Ofício": (216, 356)}.items():
        for a, b, suffix in ((w, h, ""), (h, w, " paisagem")):
            if abs(width_mm - a) < 3 and abs(height_mm - b) < 3:
                return name + suffix
    return f"{width_mm:.0f}×{height_mm:.0f} mm"


def _pdf_date(value: str) -> str:
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", value or "")
    if not match:
        return "-"
    year, month, day, hour, minute = match.groups()
    return f"{day}/{month}/{year}" + (f" {hour}:{minute or '00'}" if hour else "")


def _is_linearized(path: Path) -> bool:
    try:
        with pikepdf.open(path) as pdf:
            return pdf.is_linearized
    except Exception:
        return False


def search(job: JobContext, files: Sequence[Path], query: str = "", use_regex: bool = False, case_sensitive: bool = False, export_csv: bool = False) -> ToolResult:
    """Procura texto em vários PDFs e lista arquivo, página e trecho de cada ocorrência."""
    if not query.strip():
        raise ValidationError("Digite o texto a pesquisar.", field="query")
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query if use_regex else re.escape(query), flags)
    except re.error as error:
        raise ValidationError(f"Expressão regular inválida: {error}", field="query") from error
    rows: List[Dict[str, str]] = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Pesquisando {path.name}")
        with opened(path) as doc:
            for page in doc:
                text = " ".join(page.get_text("text").split())
                for match in pattern.finditer(text):
                    start, end = max(0, match.start() - 60), min(len(text), match.end() + 60)
                    rows.append({"arquivo": path.name, "pagina": str(page.number + 1), "trecho": ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")})
    lines = [f"{len(rows)} ocorrência(s) em {len({row['arquivo'] for row in rows})} de {len(files)} arquivo(s).", ""]
    lines += [f"{row['arquivo']} — pág. {row['pagina']}: {row['trecho']}" for row in rows]
    outputs = []
    if export_csv and rows:
        target = job.output_file(files[0], ext=".csv", name="resultado_pesquisa")
        with open(target, "w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["arquivo", "pagina", "trecho"], delimiter=";")
            writer.writeheader()
            writer.writerows(rows)
        outputs.append(target)
    return ToolResult(outputs, text="\n".join(lines))


def compare(job: JobContext, files: Sequence[Path], visual: bool = True, dpi: int = 80) -> ToolResult:
    """Compara dois PDFs: relatório de diferenças de texto (HTML) e PDF com diferenças visuais destacadas."""
    require_count(files, 2, 2, "PDFs")
    first, second = files
    outputs, summary = [], []
    with opened(first) as doc_a, opened(second) as doc_b:
        pages = max(doc_a.page_count, doc_b.page_count)
        report = [f"<h1>Comparação</h1><p><b>A:</b> {html.escape(first.name)}<br><b>B:</b> {html.escape(second.name)}</p>"]
        differ = difflib.HtmlDiff(wrapcolumn=90)
        visual_doc = pymupdf.open() if visual else None
        for number in range(pages):
            job.progress(number, pages, f"Comparando página {number + 1}")
            text_a = doc_a[number].get_text("text").splitlines() if number < doc_a.page_count else []
            text_b = doc_b[number].get_text("text").splitlines() if number < doc_b.page_count else []
            text_changed = text_a != text_b
            if text_changed:
                summary.append(f"Página {number + 1}: texto diferente")
                report.append(f"<h2>Página {number + 1}</h2>" + differ.make_table(text_a, text_b, "A", "B", context=True, numlines=2))
            if visual_doc is not None and _visual_diff_page(visual_doc, doc_a, doc_b, number, dpi) and not text_changed:
                summary.append(f"Página {number + 1}: diferença visual")
        if doc_a.page_count != doc_b.page_count:
            summary.insert(0, f"Quantidade de páginas: A={doc_a.page_count}, B={doc_b.page_count}")
        if len(report) == 1:
            report.append("<p>Nenhuma diferença de texto.</p>")
        html_target = job.output_file(first, "comparacao", ext=".html")
        html_target.write_text(_html_page("".join(report)), encoding="utf-8")
        outputs.append(html_target)
        if visual_doc is not None:
            outputs.append(save_pdf(visual_doc, job.output_file(first, "diferencas")))
    text = "\n".join(summary) if summary else "Os documentos são idênticos (texto e aparência)."
    return ToolResult(outputs, text=text)


def _visual_diff_page(out: pymupdf.Document, doc_a: pymupdf.Document, doc_b: pymupdf.Document, number: int, dpi: int) -> bool:
    """Adiciona ao `out` a página B com as diferenças em vermelho. Retorna True se houver diferença."""
    image_a = _render(doc_a, number, dpi)
    image_b = _render(doc_b, number, dpi)
    size = (max(image_a.width, image_b.width), max(image_a.height, image_b.height))
    canvas_a, canvas_b = Image.new("RGB", size, "white"), Image.new("RGB", size, "white")
    canvas_a.paste(image_a)
    canvas_b.paste(image_b)
    mask = ImageChops.difference(canvas_a, canvas_b).convert("L").point(lambda value: 255 if value > 40 else 0)
    changed = mask.getbbox() is not None
    faded = Image.blend(canvas_b, Image.new("RGB", size, "white"), 0.55)
    faded.paste(Image.new("RGB", size, (230, 30, 30)), mask=mask)
    page = out.new_page(width=size[0] * 72 / dpi, height=size[1] * 72 / dpi)
    page.insert_image(page.rect, pixmap=pymupdf.Pixmap(pymupdf.csRGB, size[0], size[1], faded.tobytes(), False))
    page.insert_text((12, 20), f"Página {number + 1} — {'diferenças em vermelho' if changed else 'sem diferenças'}", fontsize=10, color=(0.8, 0.1, 0.1))
    return changed


def _render(doc: pymupdf.Document, number: int, dpi: int) -> Image.Image:
    if number >= doc.page_count:
        return Image.new("RGB", (1, 1), "white")
    pix = doc[number].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _html_page(body: str) -> str:
    style = (
        "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1f2328}table.diff{font-family:Consolas,monospace;font-size:12px;border-collapse:collapse;margin-bottom:24px}"
        ".diff_header{background:#eef}.diff_add{background:#c8f7c5}.diff_chg{background:#fff3b0}.diff_sub{background:#ffc9c9}td{padding:1px 6px}"
    )
    return f"<!doctype html><html lang='pt-br'><meta charset='utf-8'><title>Comparação de PDFs</title><style>{style}</style><body>{body}</body></html>"


def viewer_preferences(job: JobContext, files: Sequence[Path], layout: str = "", mode: str = "", **flags: bool) -> ToolResult:
    """Define como o leitor abre o documento: layout, painel lateral e opções da janela."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Atualizando {path.name}")
        with opened(path) as doc:
            if layout:
                doc.set_pagelayout(layout)
            if mode:
                doc.set_pagemode(mode)
            entries = " ".join(f"/{name} {'true' if flags.get(name) else 'false'}" for name in VIEWER_FLAGS)
            doc.xref_set_key(doc.pdf_catalog(), "ViewerPreferences", f"<<{entries}>>")
            outputs.append(save_pdf(doc, job.output_file(path, "preferencias")))
    return ToolResult(outputs)


def viewer_preferences_prefill(path: Path) -> dict:
    with opened(path) as doc:
        catalog = doc.pdf_catalog()
        values = {"layout": doc.pagelayout if doc.pagelayout in dict(LAYOUTS) else "", "mode": doc.pagemode if doc.pagemode in dict(MODES) else ""}
        kind, prefs = doc.xref_get_key(catalog, "ViewerPreferences")
        for name in VIEWER_FLAGS:
            values[name] = kind != "null" and f"/{name} true" in (doc.xref_object(int(prefs.split()[0])) if kind == "xref" else prefs)
    return values
