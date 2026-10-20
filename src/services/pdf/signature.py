"""Assinatura digital com certificado A1 (.pfx/.p12) e verificação de assinaturas, via pyHanko."""

from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import List, Sequence, Tuple

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import DependencyError, PDFError, ValidationError
from .common import MM, anchor_rect, opened

_STAMP_FONTS = ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")
_STAMP_TEXT = "Assinado digitalmente por:\n%(signer)s\nData: %(ts)s"


def _pyhanko():
    try:
        from pyhanko.sign import fields, signers
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    except ImportError as error:
        raise DependencyError("Pacote 'pyhanko' não instalado. Execute: pip install pyhanko", dependency="pyhanko") from error
    return fields, signers, IncrementalPdfFileWriter


def sign_digital(
    job: JobContext,
    files: Sequence[Path],
    certificate: str = "",
    cert_password: str = "",
    reason: str = "",
    location: str = "",
    visible: bool = True,
    which: str = "last",
    position: str = "bottom-right",
) -> ToolResult:
    """Assina com certificado digital (padrão PAdES / ICP-Brasil A1). A assinatura invalida se o PDF for alterado."""
    fields, signers, IncrementalPdfFileWriter = _pyhanko()
    if not certificate:
        raise ValidationError("Selecione o certificado (.pfx ou .p12).", field="certificate")
    try:
        signer = signers.SimpleSigner.load_pkcs12(certificate, passphrase=cert_password.encode() if cert_password else None)
    except Exception as error:
        raise ValidationError(f"Não foi possível abrir o certificado: {error}", field="cert_password") from error
    if signer is None:
        raise ValidationError("Senha do certificado incorreta ou arquivo inválido.", field="cert_password")

    outputs = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Assinando {path.name}")
        field_name, box, page_index = _field_layout(path, which, position) if visible else (_next_field_name(path), None, 0)
        metadata = signers.PdfSignatureMetadata(field_name=field_name, reason=reason or None, location=location or None, md_algorithm="sha256")
        pdf_signer = signers.PdfSigner(
            metadata,
            signer=signer,
            stamp_style=_stamp_style() if visible else None,
            new_field_spec=fields.SigFieldSpec(field_name, on_page=page_index, box=box),
        )
        target = job.output_file(path, "assinado_digital")
        try:
            with open(path, "rb") as source, open(target, "wb") as output:
                pdf_signer.sign_pdf(IncrementalPdfFileWriter(source, strict=False), output=output)
        except Exception as error:
            target.unlink(missing_ok=True)
            raise PDFError(f"Falha ao assinar '{path.name}': {error}") from error
        outputs.append(target)
    return ToolResult(outputs, message="Não altere o PDF após assinar: qualquer modificação invalida a assinatura.")


def _next_field_name(path: Path) -> str:
    with opened(path) as doc:
        existing = {widget.field_name for page in doc for widget in page.widgets()}
    return next(name for name in (f"Assinatura{index}" for index in range(1, 1000)) if name not in existing)


def _field_layout(path: Path, which: str, position: str) -> Tuple[str, Tuple[int, int, int, int], int]:
    """Calcula a caixa visível em coordenadas PDF (origem inferior esquerda, página sem rotação)."""
    with opened(path) as doc:
        page_index = 0 if which == "first" else doc.page_count - 1
        page = doc[page_index]
        visible = anchor_rect(page.rect, (75 * MM, 22 * MM), position, 12 * MM)
        unrotated = (visible * page.derotation_matrix).normalize()
        height = page.mediabox.height
        box = (round(unrotated.x0), round(height - unrotated.y1), round(unrotated.x1), round(height - unrotated.y0))
    return _next_field_name(path), box, page_index


def _stamp_style():
    from pyhanko import stamp
    from pyhanko.pdf_utils.text import TextBoxStyle

    engine = _unicode_font_engine()
    text_style = TextBoxStyle(font=engine, font_size=8) if engine else TextBoxStyle(font_size=8)
    return stamp.TextStampStyle(stamp_text=_STAMP_TEXT, text_box_style=text_style, border_width=1, timestamp_format="%d/%m/%Y %H:%M:%S")


def _unicode_font_engine():
    """Fonte TrueType do sistema para acentos (nomes ICP-Brasil); None usa a fonte padrão do pyHanko."""
    try:
        from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory
    except ImportError:
        return None
    fonts = _system_fonts()
    return GlyphAccumulatorFactory(str(fonts[0])) if fonts else None


def _system_fonts() -> List[Path]:
    roots = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", Path("/usr/share/fonts")]
    found = []
    for name in _STAMP_FONTS:
        for root in roots:
            matches = list(root.rglob(name)) if root.exists() else []
            found.extend(matches[:1])
    return found


def verify_signatures(job: JobContext, files: Sequence[Path]) -> ToolResult:
    """Relatório de integridade de cada assinatura (quem assinou, quando, se o documento foi alterado)."""
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign.validation import validate_pdf_signature
        from pyhanko_certvalidator import ValidationContext
    except ImportError as error:
        raise DependencyError("Pacote 'pyhanko' não instalado. Execute: pip install pyhanko", dependency="pyhanko") from error

    sections = []
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Verificando {path.name}")
        lines = [f"■ {path.name}"]
        with open(path, "rb") as stream:
            try:
                signatures = PdfFileReader(stream, strict=False).embedded_signatures
            except Exception as error:
                raise PDFError(f"Não foi possível ler '{path.name}': {error}") from error
            if not signatures:
                lines.append("  Nenhuma assinatura digital encontrada.")
            for signature in signatures:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)  # pyHanko avisa sobre o uso da lista de confiança do sistema
                    status = validate_pdf_signature(signature, ValidationContext(allow_fetching=False))
                lines.extend(_describe(signature, status))
        sections.append("\n".join(lines))
    return ToolResult(text="\n\n".join(sections))


def _describe(signature, status) -> List[str]:
    signer = signature.signer_cert.subject.human_friendly if signature.signer_cert else "desconhecido"
    when = status.signer_reported_dt.strftime("%d/%m/%Y %H:%M:%S") if status.signer_reported_dt else "não informado"
    intact = status.intact and status.valid
    coverage = getattr(status.coverage, "name", str(status.coverage))
    return [
        f"  Campo: {signature.field_name}",
        f"    Assinante: {signer}",
        f"    Data informada: {when}",
        f"    Integridade: {'OK — documento não foi alterado após assinar' if intact else 'FALHOU — assinatura inválida ou documento alterado'}",
        f"    Cobertura: {'documento inteiro' if coverage == 'ENTIRE_FILE' else 'revisão assinada (houve alterações incrementais depois)' if coverage == 'ENTIRE_REVISION' else coverage}",
        f"    Cadeia confiável: {'sim' if status.trusted else 'não verificada (raiz do certificado não está na lista de confiança)'}",
    ]
