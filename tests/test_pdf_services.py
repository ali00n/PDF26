"""Testes do motor de PDF (serviços) e do catálogo de ferramentas."""

import html
import inspect
import shutil
import threading

import pymupdf
import pytest
from PIL import Image

from src.config.catalog import all_tools, tools_by_id
from src.domain.job import JobContext, safe_filename, unique_path
from src.domain.tool import Choice
from src.services.pdf import common, convert_from_pdf, convert_to_pdf, create, edit, externals, forms, inspection, optimize, organize, security, signature
from src.services.pdf.editor import EditorSession
from src.utils.exceptions import OperationCancelledError, PDFError, ValidationError
from tests.conftest import CPF, EMAIL, ink_bbox


def pages(path):
    with pymupdf.open(path) as doc:
        return doc.page_count


def text_of(path):
    with pymupdf.open(path) as doc:
        return "".join(page.get_text() for page in doc)


# ------------------------------------------------------------------ domínio / catálogo
def test_catalog_ids_unique_and_options_match_signatures():
    tools = all_tools()
    assert len(tools_by_id()) == len(tools) >= 55
    for tool in tools:
        if tool.run is None:
            assert tool.page in ("organizer", "editor", "reader", "form"), tool.id
            continue
        params = inspect.signature(tool.run).parameters
        accepts_kwargs = any(param.kind == param.VAR_KEYWORD for param in params.values())
        for option in tool.options:
            assert option.key in params or accepts_kwargs, f"{tool.id}: opção '{option.key}' não existe em {tool.run.__name__}"
            if isinstance(option, Choice):
                assert option.default in {value for value, _ in option.choices}, f"{tool.id}.{option.key}: padrão fora das opções"
            if option.show_if:
                assert option.show_if[0] in {other.key for other in tool.options}, f"{tool.id}.{option.key}: show_if aponta para opção inexistente"


def test_tool_search_ignores_accents():
    assert tools_by_id()["redact"].matches("lgpd cpf")
    assert tools_by_id()["compress"].matches("COMPRESSAO") is False
    assert tools_by_id()["compress"].matches("comprimir")
    assert tools_by_id()["sign_digital"].matches("certificado icp")


def test_unique_path_and_safe_filename(tmp_path):
    target = tmp_path / "a.pdf"
    target.write_text("x")
    assert unique_path(target).name == "a (1).pdf"
    assert safe_filename('a<b>:c"d/e\\f|g?h*') == "a_b__c_d_e_f_g_h_"


def test_parse_pages():
    assert common.parse_pages("", 4) == [0, 1, 2, 3]
    assert common.parse_pages("1-2, 4", 4) == [0, 1, 3]
    assert common.parse_pages("3-", 5) == [2, 3, 4]
    assert common.parse_pages("4-2", 5) == [3, 2, 1]
    assert common.parse_pages("1,1", 3, unique=False) == [0, 0]
    with pytest.raises(ValidationError):
        common.parse_pages("9", 3)
    with pytest.raises(ValidationError):
        common.parse_pages("a-b", 3)


def test_job_cancel_raises(sample_pdf):
    event = threading.Event()
    event.set()
    with pytest.raises(OperationCancelledError):
        organize.rotate(JobContext(cancel_event=event), [sample_pdf])


def test_output_never_overwrites_input(job, sample_pdf):
    first = organize.rotate(job, [sample_pdf]).files[0]
    second = organize.rotate(job, [sample_pdf]).files[0]
    assert first != second and first.name == "amostra_girado.pdf" and second.name == "amostra_girado (1).pdf"


# ------------------------------------------------------------------ organizar
def test_merge_keeps_bookmarks(job, sample_pdf, second_pdf):
    result = organize.merge(job, [sample_pdf, second_pdf], bookmarks=True)
    with pymupdf.open(result.files[0]) as doc:
        assert doc.page_count == 10
        toc = doc.get_toc()
        assert [1, "amostra", 1] == toc[0][:3]
        assert [2, "Introdução", 1] == toc[1][:3]
        assert any(entry[1] == "amostra_b" and entry[2] == 6 for entry in toc)


@pytest.mark.parametrize("mode,kwargs,expected", [("each", {}, 5), ("every", {"every": 2}, 3), ("ranges", {"ranges": "1-2, 3-5"}, 2), ("bookmarks", {}, 2)])
def test_split(job, sample_pdf, mode, kwargs, expected):
    result = organize.split(job, [sample_pdf], mode=mode, **kwargs)
    assert len(result.files) == expected
    assert sum(pages(path) for path in result.files) == 5


def test_rotate_and_select(job, sample_pdf):
    result = organize.rotate(job, [sample_pdf], angle="180", which="custom", pages="1,4")
    with pymupdf.open(result.files[0]) as doc:
        assert [page.rotation for page in doc] == [180, 0, 0, 270, 0]


def test_remove_pages_and_blank(job, sample_pdf, tmp_path):
    doc = pymupdf.open(sample_pdf)
    doc.new_page()
    with_blank = tmp_path / "com_branco.pdf"
    doc.save(with_blank)
    result = organize.remove_pages(job, [with_blank], pages="2", remove_blank=True)
    assert pages(result.files[0]) == 4
    assert "Página 2" not in text_of(result.files[0])
    with pytest.raises(PDFError):
        organize.remove_pages(job, [sample_pdf], pages="1-5")


def test_extract_pages(job, sample_pdf):
    assert pages(organize.extract_pages(job, [sample_pdf], pages="2-3").files[0]) == 2
    assert len(organize.extract_pages(job, [sample_pdf], pages="1,5", separate=True).files) == 2


def test_assemble_with_rotation_and_blank(job, sample_pdf, second_pdf, tmp_path):
    refs = [organize.PageRef(1, 2), organize.PageRef(0, 0, rotation=90), organize.PageRef(0, 0, blank=True)]
    result = organize.assemble(job, [sample_pdf, second_pdf], refs, tmp_path / "montado.pdf")
    with pymupdf.open(result.files[0]) as doc:
        assert doc.page_count == 3
        assert "VERSÃO B" in doc[0].get_text()
        assert doc[1].rotation == 90
        assert not doc[2].get_text().strip()


def test_pages_per_sheet_handles_rotated_page(job, sample_pdf):
    result = organize.pages_per_sheet(job, [sample_pdf], per_sheet="4")
    with pymupdf.open(result.files[0]) as doc:
        assert doc.page_count == 2
        text = doc[0].get_text()
        assert "Página 1" in text and "Página 4" in text


def test_booklet_order():
    assert organize._booklet_order(8) == [(7, 0), (1, 6), (5, 2), (3, 4)]


def test_booklet(job, sample_pdf):
    result = organize.booklet(job, [sample_pdf])
    with pymupdf.open(result.files[0]) as doc:
        assert doc.page_count == 4
        assert doc[0].rect.width > doc[0].rect.height


def test_halve(job, sample_pdf):
    result = organize.halve(job, [sample_pdf], direction="horizontal")
    with pymupdf.open(result.files[0]) as doc:
        assert doc.page_count == 10
        assert "Página 1" in doc[0].get_text() and "Página 1" not in doc[1].get_text()


def test_bookmarks_roundtrip(job, sample_pdf):
    prefill = organize.bookmarks_prefill(sample_pdf)["toc_text"]
    assert "1 | Introdução | 1" in prefill
    result = organize.bookmarks(job, [sample_pdf], mode="edit", toc_text="1 | Novo | 2\n3 | Filho | 3")
    with pymupdf.open(result.files[0]) as doc:
        assert [entry[:3] for entry in doc.get_toc()] == [[1, "Novo", 2], [2, "Filho", 3]]
    with pytest.raises(ValidationError):
        organize.parse_toc_text("1 | sem página", 5)


def test_extract_images(job, sample_pdf):
    result = organize.extract_images(job, [sample_pdf])
    assert len(result.files) == 1 and result.files[0].suffix in (".png", ".jpeg", ".jpg")


# ------------------------------------------------------------------ editar
def test_watermark_text_on_rotated_page(job, sample_pdf):
    result = edit.watermark(job, [sample_pdf], text="SIGILOSO", opacity=50, angle=0, position="top-left")
    with pymupdf.open(result.files[0]) as doc:
        for page in doc:
            box = ink_bbox(page)
            assert box[0] < 60 and box[1] < 60, f"marca d'água fora do canto superior esquerdo na página {page.number + 1}: {box}"
        assert "SIGILOSO" in doc[3].get_text()


def test_watermark_tile_and_image(job, sample_pdf, images):
    assert edit.watermark(job, [sample_pdf], tile=True, angle=45).files
    assert edit.watermark(job, [sample_pdf], kind="image", image=str(images[0]), tile=True).files
    with pytest.raises(ValidationError):
        edit.watermark(job, [sample_pdf], kind="image", image="")


def test_page_numbers_on_rotated_page(job, sample_pdf):
    result = edit.page_numbers(job, [sample_pdf], template="Pág. {n}/{total}", position="bottom-right", skip_first=1)
    with pymupdf.open(result.files[0]) as doc:
        assert "Pág." not in doc[0].get_text()
        assert "Pág. 1/4" in doc[1].get_text()
        rotated = doc[3]
        hits = rotated.search_for("Pág. 3/4")
        assert hits
        visible = hits[0] * rotated.rotation_matrix
        assert visible.x0 > rotated.rect.width * 0.6 and visible.y0 > rotated.rect.height * 0.8
    with pytest.raises(ValidationError):
        edit.page_numbers(job, [sample_pdf], template="{pagina}")


def test_overlay(job, sample_pdf, second_pdf):
    result = edit.overlay(job, [sample_pdf], overlay_file=str(second_pdf), mode="foreground", repeat="match")
    assert "VERSÃO B" in text_of(result.files[0])


def test_crop_margins_and_auto(job, sample_pdf):
    result = edit.crop(job, [sample_pdf], mode="margins", top=20, bottom=20, left=10, right=10)
    with pymupdf.open(result.files[0]) as doc:
        assert round(doc[0].rect.width) == round(595 - 20 * common.MM)
        assert round(doc[0].rect.height) == round(842 - 40 * common.MM)
        assert round(doc[3].rect.width) == round(842 - 20 * common.MM), "página girada: margens laterais"
        assert round(doc[3].rect.height) == round(595 - 40 * common.MM), "página girada: margens superior/inferior"
    auto = edit.crop(job, [sample_pdf], mode="auto", padding=2)
    with pymupdf.open(auto.files[0]) as doc:
        assert doc[0].rect.width < 595 and "Página 1" in doc[0].get_text()
    with pytest.raises(ValidationError):
        edit.crop(job, [sample_pdf], mode="margins", top=200, bottom=200)


def test_resize(job, sample_pdf):
    result = edit.resize(job, [sample_pdf], paper="A5")
    with pymupdf.open(result.files[0]) as doc:
        assert round(doc[0].rect.width) == 420
        assert doc[3].rect.width > doc[3].rect.height
        assert "Página 4" in doc[3].get_text()


def test_document_info(job, sample_pdf):
    assert edit.document_info_prefill(sample_pdf)["title"] == "Documento de teste"
    result = edit.document_info(job, [sample_pdf], title="Novo título", author="Alisson", subject="", keywords="a, b", creator="", producer="")
    with pymupdf.open(result.files[0]) as doc:
        assert doc.metadata["title"] == "Novo título" and doc.metadata["author"] == "Alisson"


def test_forms_read_fill_flatten(job, form_pdf):
    fields = {field.name: field for field in forms.read_fields(form_pdf)}
    assert set(fields) == {"nome", "aceito", "estado"}
    assert fields["estado"].choices == ["SP", "RJ", "MG"]
    result = forms.fill_form(job, form_pdf, {"nome": "Maria José", "aceito": True, "estado": "MG"})
    filled = {field.name: field.value for field in forms.read_fields(result.files[0])}
    assert filled == {"nome": "Maria José", "aceito": True, "estado": "MG"}
    flat = forms.fill_form(job, form_pdf, {"nome": "Final"}, flatten=True)
    with pymupdf.open(flat.files[0]) as doc:
        assert not list(doc[0].widgets()) and "Final" in doc[0].get_text()


def test_flatten(job, form_pdf):
    with pymupdf.open(edit.flatten(job, [form_pdf]).files[0]) as doc:
        assert not list(doc[0].widgets())


# ------------------------------------------------------------------ otimizar
def test_compress_reports_and_never_grows(job, tmp_path):
    doc = pymupdf.open()
    noisy = Image.effect_noise((2400, 2400), 60).convert("RGB")
    buffer = __import__("io").BytesIO()
    noisy.save(buffer, "PNG")
    page = doc.new_page()
    page.insert_image(page.rect, stream=buffer.getvalue())
    big = tmp_path / "grande.pdf"
    doc.save(big)
    result = optimize.compress(job, [big], level="high")
    assert result.files[0].stat().st_size < big.stat().st_size / 3
    assert "→" in result.text


def test_grayscale_raster_and_ghostscript(job, sample_pdf):
    raster = optimize.grayscale(job, [sample_pdf], method="raster", dpi=72).files[0]
    with pymupdf.open(raster) as doc:
        pix = doc[1].get_pixmap(dpi=20)
        r, g, b = pix.pixel(pix.width // 2, pix.height // 2)[:3]
        assert abs(r - g) < 8 and abs(g - b) < 8
    if externals.find_ghostscript():
        gs = optimize.grayscale(job, [sample_pdf], method="ghostscript").files[0]
        assert "Página 1" in text_of(gs)


def test_web_optimize(job, sample_pdf):
    import pikepdf

    with pikepdf.open(optimize.web_optimize(job, [sample_pdf]).files[0]) as pdf:
        assert pdf.is_linearized


@pytest.mark.skipif(not externals.find_tessdata(), reason="Tesseract não instalado")
def test_ocr(job, sample_pdf):
    scanned = optimize.rasterize(job, [sample_pdf], dpi=200).files[0]
    assert "Página" not in text_of(scanned)
    result = optimize.ocr(job, [scanned], language="por", dpi=200)
    assert "Página 1" in text_of(result.files[0])


def test_repair(job, sample_pdf, tmp_path):
    damaged = tmp_path / "danificado.pdf"
    data = sample_pdf.read_bytes()
    damaged.write_bytes(data[: data.rfind(b"xref")])
    result = optimize.repair(job, [damaged])
    assert pages(result.files[0]) == 5


def test_rasterize(job, sample_pdf):
    result = optimize.rasterize(job, [sample_pdf], dpi=72)
    assert pages(result.files[0]) == 5 and not text_of(result.files[0]).strip()


@pytest.mark.skipif(not externals.find_ghostscript(), reason="Ghostscript não instalado")
def test_pdfa(job, sample_pdf):
    result = optimize.pdfa(job, [sample_pdf], level="2")
    with pymupdf.open(result.files[0]) as doc:
        assert "pdfaid" in (doc.get_xml_metadata() or "")


# ------------------------------------------------------------------ segurança
def test_protect_and_unlock(job, sample_pdf):
    result = security.protect(job, [sample_pdf], user_password="abc", allow_print=True)
    protected = result.files[0]
    assert "Senha de proprietário gerada" in result.text
    with pymupdf.open(protected) as doc:
        assert doc.needs_pass
    with pytest.raises(PDFError):
        security.unlock(job, [protected], password="errada")
    unlocked = security.unlock(job, [protected], password="abc").files[0]
    with pymupdf.open(unlocked) as doc:
        assert not doc.needs_pass and doc.page_count == 5
    with pytest.raises(ValidationError):
        security.protect(job, [sample_pdf])


def test_redact_presets_remove_text(job, sample_pdf):
    result = security.redact(job, [sample_pdf], cpf=True, email=True, terms="Linha extra")
    text = text_of(result.files[0])
    assert CPF not in text and EMAIL not in text and "Linha extra" not in text
    assert "Página 1" in text
    assert "ocorrência" in result.text
    with pytest.raises(ValidationError):
        security.redact(job, [sample_pdf])


def test_remove_metadata(job, sample_pdf):
    with pymupdf.open(security.remove_metadata(job, [sample_pdf]).files[0]) as doc:
        assert not doc.metadata["title"] and not doc.metadata["author"]


def test_generate_passwords(job):
    result = security.generate_passwords(job, [], length=20, count=3, symbols=False)
    passwords = result.text.splitlines()
    assert len(passwords) == 3 and all(len(item) == 20 and item.isalnum() for item in passwords)
    assert not any(char in "Il1O0o" for item in passwords for char in item)


def test_sign_visual_and_text_signature(job, sample_pdf, tmp_path):
    signature_png = security.render_text_signature("Alisson Ribeiro", tmp_path / "assinatura.png")
    result = security.sign_visual(job, [sample_pdf], signature=str(signature_png), which="all", position="bottom-right", add_date=True)
    with pymupdf.open(result.files[0]) as doc:
        for page in doc:
            box = ink_bbox(page)
            assert box[2] > page.rect.width * 0.8 and box[3] > page.rect.height * 0.8, f"assinatura fora do canto na página {page.number + 1}"
        assert "Assinado em" in doc[3].get_text()


def test_digital_signature_and_verification(job, sample_pdf, pfx_certificate):
    pfx, password = pfx_certificate
    with pytest.raises(ValidationError):
        signature.sign_digital(job, [sample_pdf], certificate=str(pfx), cert_password="errada")
    signed = signature.sign_digital(job, [sample_pdf], certificate=str(pfx), cert_password=password, reason="Teste", location="São Paulo").files[0]
    report = signature.verify_signatures(job, [signed]).text
    assert "JOSÉ DA CONCEIÇÃO" in report and "Integridade: OK" in report and "documento inteiro" in report
    with pymupdf.open(signed) as doc:
        doc[0].insert_text((72, 400), "alteração posterior")
        doc.saveIncr()
    assert "houve alterações" in signature.verify_signatures(job, [signed]).text
    assert "Nenhuma assinatura" in signature.verify_signatures(job, [sample_pdf]).text


# ------------------------------------------------------------------ visualizar
def test_info_report(job, sample_pdf):
    report = inspection.info(job, [sample_pdf]).text
    assert "Páginas: 5" in report and "A4" in report and "Documento de teste" in report


def test_search(job, sample_pdf, second_pdf):
    result = inspection.search(job, [sample_pdf, second_pdf], query="versão b", export_csv=True)
    assert result.text.startswith("1 ocorrência") and result.files[0].suffix == ".csv"
    regex = inspection.search(job, [sample_pdf], query=r"\d{3}\.\d{3}\.\d{3}-\d{2}", use_regex=True)
    assert CPF in regex.text


def test_compare(job, sample_pdf, second_pdf):
    result = inspection.compare(job, [sample_pdf, second_pdf])
    assert "Página 3: texto diferente" in result.text
    assert {path.suffix for path in result.files} == {".html", ".pdf"}
    same = inspection.compare(job, [sample_pdf, sample_pdf], visual=False)
    assert "idênticos" in same.text


def test_viewer_preferences(job, sample_pdf):
    result = inspection.viewer_preferences(job, [sample_pdf], layout="TwoPageLeft", mode="UseOutlines", FitWindow=True)
    values = inspection.viewer_preferences_prefill(result.files[0])
    assert values["layout"] == "TwoPageLeft" and values["mode"] == "UseOutlines" and values["FitWindow"] and not values["HideToolbar"]


# ------------------------------------------------------------------ conversões
def test_images_to_pdf_respects_exif_and_formats(job, images):
    result = convert_to_pdf.images_to_pdf(job, images, paper="image", margin_mm=0)
    with pymupdf.open(result.files[0]) as doc:
        assert doc.page_count == len(images)
        exif_page = doc[1]
        assert exif_page.rect.height > exif_page.rect.width, "orientação EXIF não aplicada"
    separate = convert_to_pdf.images_to_pdf(job, images, single_file=False)
    assert len(separate.files) == len(images)


def test_text_and_markdown_to_pdf(job, text_files):
    result = convert_to_pdf.text_to_pdf(job, text_files)
    assert "Ação, coração" in text_of(result.files[0])
    assert "Título" in text_of(result.files[1]) and "negrito" in text_of(result.files[1])


@pytest.mark.skipif(not externals.find_soffice(), reason="LibreOffice não instalado")
def test_office_to_pdf_with_libreoffice(job, xlsx_file):
    result = convert_to_pdf.office_to_pdf(job, [xlsx_file])
    assert "Caneta" in text_of(result.files[0])


def test_convert_any_merge(job, images, text_files, sample_pdf, tmp_path):
    svg = tmp_path / "desenho.svg"
    svg.write_text("<svg xmlns='http://www.w3.org/2000/svg' width='200' height='100'><text x='10' y='50'>SVG ok</text></svg>")
    result = convert_to_pdf.convert_any(job, [sample_pdf, images[0], text_files[0], svg], merge=True)
    assert pages(result.files[0]) == 8 and "SVG ok" in text_of(result.files[0])
    with pytest.raises(ValidationError):
        convert_to_pdf.convert_file(tmp_path / "x.xyz", tmp_path / "x.pdf")


def test_pdf_to_images(job, sample_pdf):
    pngs = convert_from_pdf.to_images(job, [sample_pdf], fmt="png", dpi=50, pages="1-2")
    assert len(pngs.files) == 2
    with Image.open(pngs.files[0]) as image:
        assert abs(image.size[0] - 595 * 50 / 72) <= 1
    tiff = convert_from_pdf.to_images(job, [sample_pdf], fmt="tiff", dpi=40, single_tiff=True).files[0]
    with Image.open(tiff) as image:
        assert image.n_frames == 5


def test_pdf_to_text_html_markdown_svg(job, sample_pdf):
    assert "Página 3" in convert_from_pdf.to_text(job, [sample_pdf]).files[0].read_text(encoding="utf-8")
    assert "Página 2" in html.unescape(convert_from_pdf.to_html(job, [sample_pdf]).files[0].read_text(encoding="utf-8"))
    assert "Página" in convert_from_pdf.to_markdown(job, [sample_pdf]).files[0].read_text(encoding="utf-8")
    assert len(convert_from_pdf.to_svg(job, [sample_pdf], pages="1").files) == 1


def test_pdf_to_word(job, sample_pdf):
    from docx import Document

    docx = convert_from_pdf.to_word(job, [sample_pdf], pages="1-2").files[0]
    assert "Página 1" in "\n".join(paragraph.text for paragraph in Document(docx).paragraphs)


def test_pdf_to_excel_tables(job, table_pdf):
    from openpyxl import load_workbook

    xlsx = convert_from_pdf.to_excel(job, [table_pdf]).files[0]
    sheet = load_workbook(xlsx).worksheets[0]
    values = [[cell.value for cell in row] for row in sheet.iter_rows()]
    assert values[0] == ["Nome", "Cidade", "Valor"] and values[1][2] == 1234.56


def test_pdf_to_powerpoint(job, sample_pdf):
    from pptx import Presentation

    assert len(Presentation(convert_from_pdf.to_powerpoint(job, [sample_pdf], dpi=72).files[0]).slides) == 5


def test_create_tools(job):
    written = create.write_pdf(job, [], title="Ofício nº 1", content="Prezados,\n\nSegue documento.")
    assert "Ofício nº 1" in text_of(written.files[0])
    blank = create.blank_pdf(job, [], pages=3, paper="Carta", orientation="landscape")
    with pymupdf.open(blank.files[0]) as doc:
        assert doc.page_count == 3 and round(doc[0].rect.width) == 792
    qr = create.qr_code(job, [], content="https://exemplo.com.br", as_pdf=True)
    assert {path.suffix for path in qr.files} == {".png", ".pdf"}


def test_convert_images(job, images):
    result = create.convert_images(job, images, fmt="jpg", max_side=100)
    assert len(result.files) == len(images)
    for path in result.files:
        with Image.open(path) as image:
            assert image.format == "JPEG" and max(image.size) <= 100
    with Image.open(result.files[1]) as rotated:
        assert rotated.height > rotated.width


# ------------------------------------------------------------------ editor
def test_editor_session(sample_pdf, tmp_path):
    working = tmp_path / "editar.pdf"
    shutil.copy(sample_pdf, working)
    session = EditorSession(working)
    rotated = 3
    width, height = session.page_size(rotated)
    session.add_text(rotated, pymupdf.Rect(20, 20, 220, 50), "Anotação ação", font_size=14)
    session.add_highlight(0, pymupdf.Rect(60, 80, 400, 110))
    session.add_shape(1, pymupdf.Rect(100, 100, 200, 200), kind="ellipse")
    session.add_ink(1, [(10, 10), (50, 60), (90, 20)])
    session.add_note(2, (50, 50), "Comentário")
    session.redact(0, pymupdf.Rect(60, 160, 500, 190))
    assert session.can_undo and session.dirty
    hits = session.search("Página 2")
    assert hits and hits[0][0] == 1
    session.rotate_page(4, 90)
    session.undo()
    assert session.doc[4].rotation == 0
    session.save()
    with pymupdf.open(working) as doc:
        assert CPF not in doc[0].get_text()
        assert len(list(doc[0].annots())) == 1
        page = doc[rotated]
        annot = next(page.annots())
        assert "Anotação ação" in annot.info["content"]
        visible = annot.rect * page.rotation_matrix
        assert visible.x0 < 40 and visible.y0 < 40, f"texto fora da posição clicada: {visible} (página {width}x{height})"
    session.close()
