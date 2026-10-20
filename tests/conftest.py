"""Fixtures com arquivos de exemplo gerados em tempo de execução."""

import datetime
import io
import sys
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.domain.job import JobContext  # noqa: E402

CPF = "123.456.789-09"
EMAIL = "fulano@exemplo.com.br"


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PDF26_CONFIG_DIR", str(tmp_path / "config"))


@pytest.fixture
def job(tmp_path):
    return JobContext(fallback_dir=tmp_path / "saida")


def _image_bytes(color=(30, 90, 200), size=(400, 300), fmt="PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    """5 páginas A4: texto 'Página N', CPF/e-mail na 1, imagem na 2, página 4 girada 90°, marcadores."""
    doc = pymupdf.open()
    for number in range(1, 6):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 100), f"Página {number} — conteúdo de teste", fontsize=16)
        page.insert_text((72, 140), f"Linha extra da página {number}", fontsize=11)
    doc[0].insert_text((72, 180), f"CPF: {CPF}  E-mail: {EMAIL}", fontsize=11)
    doc[1].insert_image(pymupdf.Rect(72, 200, 472, 500), stream=_image_bytes())
    doc[3].set_rotation(90)
    doc.set_toc([[1, "Introdução", 1], [2, "Detalhes", 2], [1, "Conclusão", 4]])
    doc.set_metadata({"title": "Documento de teste", "author": "PDF26"})
    path = tmp_path / "amostra.pdf"
    doc.save(path)
    return path


@pytest.fixture
def second_pdf(tmp_path, sample_pdf) -> Path:
    doc = pymupdf.open(sample_pdf)
    doc[2].insert_text((72, 300), "TEXTO NOVO NA VERSÃO B", fontsize=14)
    path = tmp_path / "amostra_b.pdf"
    doc.save(path)
    return path


@pytest.fixture
def form_pdf(tmp_path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    specs = [
        (pymupdf.PDF_WIDGET_TYPE_TEXT, "nome", pymupdf.Rect(72, 72, 300, 92), None),
        (pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "aceito", pymupdf.Rect(72, 110, 90, 128), None),
        (pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "estado", pymupdf.Rect(72, 150, 200, 170), ["SP", "RJ", "MG"]),
    ]
    for kind, name, rect, choices in specs:
        widget = pymupdf.Widget()
        widget.field_type, widget.field_name, widget.rect = kind, name, rect
        if choices:
            widget.choice_values = choices
            widget.field_value = choices[0]
        page.add_widget(widget)
    path = tmp_path / "formulario.pdf"
    doc.save(path)
    return path


@pytest.fixture
def images(tmp_path) -> list:
    png = tmp_path / "transparente.png"
    rgba = Image.new("RGBA", (300, 200), (255, 0, 0, 0))
    rgba.paste((255, 0, 0, 255), (0, 0, 150, 200))
    rgba.save(png)

    rotated = tmp_path / "foto_exif.jpg"
    photo = Image.new("RGB", (400, 200), "white")
    photo.paste((0, 0, 0), (0, 0, 200, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # girar 90° no sentido horário ao exibir
    photo.save(rotated, "JPEG", exif=exif)

    webp = tmp_path / "imagem.webp"
    Image.new("RGB", (320, 240), (0, 160, 80)).save(webp, "WEBP")

    files = [png, rotated, webp]
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
        heic = tmp_path / "iphone.heic"
        Image.new("RGB", (200, 300), (120, 60, 200)).save(heic, "HEIF")
        files.append(heic)
    except Exception:
        pass
    return files


@pytest.fixture
def text_files(tmp_path) -> list:
    txt = tmp_path / "nota.txt"
    txt.write_text("Ação, coração e ç.\nSegunda linha.\n", encoding="cp1252")
    md = tmp_path / "leia.md"
    md.write_text("# Título\n\nTexto com **negrito**.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    return [txt, md]


@pytest.fixture
def xlsx_file(tmp_path) -> Path:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.active.append(["Produto", "Valor"])
    workbook.active.append(["Caneta", 2.5])
    path = tmp_path / "planilha.xlsx"
    workbook.save(path)
    return path


@pytest.fixture
def table_pdf(tmp_path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    x0, y0, widths, height = 72, 100, [120, 120, 120], 24
    rows = [["Nome", "Cidade", "Valor"], ["Ana", "Recife", "1.234,56"], ["Bruno", "Natal", "99,90"]]
    for r, row in enumerate(rows):
        x = x0
        for c, value in enumerate(row):
            rect = pymupdf.Rect(x, y0 + r * height, x + widths[c], y0 + (r + 1) * height)
            page.draw_rect(rect, color=(0, 0, 0), width=0.8)
            page.insert_text((rect.x0 + 4, rect.y1 - 7), value, fontsize=11)
            x += widths[c]
    path = tmp_path / "tabela.pdf"
    doc.save(path)
    return path


@pytest.fixture
def pfx_certificate(tmp_path):
    """Certificado A1 autoassinado com nome acentuado (formato ICP-Brasil: NOME:CPF)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "JOSÉ DA CONCEIÇÃO:12345678909"), x509.NameAttribute(NameOID.COUNTRY_NAME, "BR")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
        .sign(key, hashes.SHA256())
    )
    data = pkcs12.serialize_key_and_certificates(b"teste", key, cert, None, serialization.BestAvailableEncryption(b"1234"))
    path = tmp_path / "certificado.pfx"
    path.write_bytes(data)
    return path, "1234"


def ink_bbox(page: pymupdf.Page, dpi: int = 36):
    """Caixa (em pontos, coordenadas visíveis) dos pixels escuros da página renderizada."""
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    box = image.point(lambda value: 255 if value < 200 else 0).getbbox()
    return tuple(value * 72 / dpi for value in box) if box else None
