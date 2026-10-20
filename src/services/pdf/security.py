"""Serviços de segurança: senha, desbloqueio, tarjas (LGPD), metadados, gerador de senha e assinatura visual."""

from __future__ import annotations

import re
import secrets
import string
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import ValidationError
from .common import MM, anchor_rect, hex_to_rgb, new_stamp, opened, parse_pages, save_pdf, stamp_page

REDACTION_PRESETS: Dict[str, str] = {
    "cpf": r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
    "cnpj": r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b",
    "email": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "phone": r"(?:\+?55\s?)?\(?\b\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b",
    "cep": r"\b\d{5}-\d{3}\b",
}
_AMBIGUOUS = set("Il1O0o")
_SYMBOLS = "!@#$%&*()-_=+[]{};:,.?/"
_PERMISSIONS = {
    "allow_print": pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ,
    "allow_copy": pymupdf.PDF_PERM_COPY,
    "allow_modify": pymupdf.PDF_PERM_MODIFY,
    "allow_annotate": pymupdf.PDF_PERM_ANNOTATE,
    "allow_forms": pymupdf.PDF_PERM_FORM,
    "allow_assemble": pymupdf.PDF_PERM_ASSEMBLE,
}
_SIGNATURE_FONTS = ("segoesc.ttf", "LHANDW.TTF", "BRUSHSCI.TTF", "Inkfree.ttf", "DejaVuSerif-Italic.ttf")


def protect(job: JobContext, files: Sequence[Path], user_password: str = "", owner_password: str = "", **permissions: bool) -> ToolResult:
    """Criptografa com AES-256. Sem senha de proprietário, uma aleatória é gerada para garantir as permissões."""
    if not user_password and not owner_password:
        raise ValidationError("Informe ao menos uma senha.", field="user_password")
    generated = not owner_password
    owner = owner_password or secrets.token_urlsafe(18)
    flags = pymupdf.PDF_PERM_ACCESSIBILITY
    for key, bit in _PERMISSIONS.items():
        if permissions.get(key):
            flags |= bit
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Protegendo {path.name}")
        with opened(path) as doc:
            target = job.output_file(path, "protegido")
            save_pdf(doc, target, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw=owner, user_pw=user_password, permissions=flags)
            outputs.append(target)
    note = f"Senha de proprietário gerada (guarde-a para alterar permissões): {owner}" if generated else ""
    return ToolResult(outputs, text=note)


def unlock(job: JobContext, files: Sequence[Path], password: str = "") -> ToolResult:
    """Remove senha de abertura e restrições (requer a senha quando houver senha de abertura)."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Desbloqueando {path.name}")
        with opened(path, password or None) as doc:
            outputs.append(save_pdf(doc, job.output_file(path, "desbloqueado"), encryption=pymupdf.PDF_ENCRYPT_NONE))
    return ToolResult(outputs)


def redact(
    job: JobContext,
    files: Sequence[Path],
    terms: str = "",
    use_regex: bool = False,
    cpf: bool = False,
    cnpj: bool = False,
    email: bool = False,
    phone: bool = False,
    cep: bool = False,
    replacement: str = "",
    color: str = "#000000",
    pages: str = "",
) -> ToolResult:
    """Tarja definitivamente (remove o conteúdo, não só cobre) termos, expressões e dados pessoais."""
    patterns = _redaction_patterns(terms, use_regex, cpf=cpf, cnpj=cnpj, email=email, phone=phone, cep=cep)
    fill = hex_to_rgb(color)
    outputs, lines = [], []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Tarjando {path.name}")
        with opened(path) as doc:
            total = 0
            for number in parse_pages(pages, doc.page_count):
                page = doc[number]
                for quad in _find_quads(page, patterns):
                    page.add_redact_annot(quad, text=replacement or None, fill=fill, text_color=(1, 1, 1) if sum(fill) < 1.5 else (0, 0, 0))
                    total += 1
                if page.first_annot:
                    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS)
            outputs.append(save_pdf(doc, job.output_file(path, "tarjado"), garbage=4, clean=True))
            lines.append(f"{path.name}: {total} ocorrência(s) tarjada(s)")
    return ToolResult(outputs, text="\n".join(lines))


def _redaction_patterns(terms: str, use_regex: bool, **presets: bool) -> List[re.Pattern]:
    patterns = [re.compile(REDACTION_PRESETS[name]) for name, enabled in presets.items() if enabled]
    for line in filter(None, (line.strip() for line in (terms or "").splitlines())):
        try:
            patterns.append(re.compile(line if use_regex else re.escape(line), re.IGNORECASE))
        except re.error as error:
            raise ValidationError(f"Expressão regular inválida '{line}': {error}", field="terms") from error
    if not patterns:
        raise ValidationError("Informe termos a tarjar ou marque algum tipo de dado (CPF, CNPJ...).", field="terms")
    return patterns


def _find_quads(page: pymupdf.Page, patterns: List[re.Pattern]) -> List[pymupdf.Quad]:
    text = page.get_text("text")
    matches = {match.group(0).strip() for pattern in patterns for match in pattern.finditer(text)}
    quads: List[pymupdf.Quad] = []
    for match in filter(None, matches):
        quads.extend(page.search_for(match, quads=True))
    return quads


def remove_metadata(job: JobContext, files: Sequence[Path], attachments: bool = False, javascript: bool = True, thumbnails: bool = True) -> ToolResult:
    """Apaga informações do documento e XMP (autor, software, datas...), opcionalmente anexos e scripts."""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Limpando {path.name}")
        with opened(path) as doc:
            doc.scrub(
                metadata=True,
                xml_metadata=True,
                attached_files=attachments,
                embedded_files=attachments,
                javascript=javascript,
                thumbnails=thumbnails,
                clean_pages=False,
                hidden_text=False,
                redactions=False,
                remove_links=False,
                reset_fields=False,
                reset_responses=False,
            )
            outputs.append(save_pdf(doc, job.output_file(path, "sem_metadados"), garbage=4, clean=True))
    return ToolResult(outputs)


def generate_passwords(
    job: JobContext, files: Sequence[Path], length: int = 16, count: int = 5, upper: bool = True, lower: bool = True, digits: bool = True, symbols: bool = True, no_ambiguous: bool = True
) -> ToolResult:
    """Gera senhas aleatórias criptograficamente seguras (módulo secrets)."""
    pools = [pool for pool, enabled in ((string.ascii_uppercase, upper), (string.ascii_lowercase, lower), (string.digits, digits), (_SYMBOLS, symbols)) if enabled]
    if not pools:
        raise ValidationError("Selecione ao menos um tipo de caractere.", field="upper")
    if no_ambiguous:
        pools = ["".join(char for char in pool if char not in _AMBIGUOUS) for pool in pools]
    length = int(length)
    if length < len(pools):
        raise ValidationError(f"O tamanho mínimo é {len(pools)}.", field="length")
    alphabet = "".join(pools)
    passwords = []
    for _ in range(int(count)):
        chars = [secrets.choice(pool) for pool in pools] + [secrets.choice(alphabet) for _ in range(length - len(pools))]
        secrets.SystemRandom().shuffle(chars)
        passwords.append("".join(chars))
    return ToolResult(text="\n".join(passwords))


def sign_visual(
    job: JobContext,
    files: Sequence[Path],
    signature: str = "",
    which: str = "last",
    pages: str = "",
    position: str = "bottom-right",
    width_mm: float = 50,
    margin_mm: float = 15,
    add_date: bool = False,
) -> ToolResult:
    """Insere a imagem da assinatura manuscrita nas páginas escolhidas."""
    if not signature or not Path(signature).exists():
        raise ValidationError("Crie ou selecione uma assinatura.", field="signature")
    with Image.open(signature) as img:
        ratio = img.height / img.width
    image_bytes = Path(signature).read_bytes()
    stamp_text = f"Assinado em {datetime.now():%d/%m/%Y %H:%M}" if add_date else ""
    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Assinando {path.name}")
        with opened(path) as doc:
            for number in _signature_pages(doc.page_count, which, pages):
                page = doc[number]
                stamp, canvas = new_stamp(page)
                width = float(width_mm) * MM
                box = anchor_rect(canvas.rect, (width, width * ratio + (12 if stamp_text else 0)), position, float(margin_mm) * MM)
                canvas.insert_image(pymupdf.Rect(box.x0, box.y0, box.x1, box.y0 + width * ratio), stream=image_bytes, keep_proportion=True)
                if stamp_text:
                    canvas.insert_text((box.x0, box.y1 - 2), stamp_text, fontsize=8, fontname="helv", color=(0.25, 0.25, 0.25))
                stamp_page(page, stamp)
            outputs.append(save_pdf(doc, job.output_file(path, "assinado")))
    return ToolResult(outputs)


def _signature_pages(count: int, which: str, pages: str) -> List[int]:
    return {"first": [0], "last": [count - 1], "all": list(range(count))}.get(which) or parse_pages(pages, count)


def render_text_signature(text: str, target: Path, color: str = "#1E3A8A", height: int = 160) -> Path:
    """Desenha um nome digitado como assinatura (fonte cursiva do sistema) em PNG transparente."""
    if not text.strip():
        raise ValidationError("Digite o nome para a assinatura.", field="signature")
    font = _signature_font(int(height * 0.6))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), text, font=font)
    pad = height // 6
    image = Image.new("RGBA", (right - left + 2 * pad, bottom - top + 2 * pad), (0, 0, 0, 0))
    rgb = tuple(round(value * 255) for value in hex_to_rgb(color))
    ImageDraw.Draw(image).text((pad - left, pad - top), text, font=font, fill=rgb + (255,))
    image.save(target)
    return target


def _signature_font(size: int) -> ImageFont.FreeTypeFont:
    for name in _SIGNATURE_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)
