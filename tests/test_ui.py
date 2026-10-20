"""Testes de fumaça da interface (CustomTkinter). Pulados automaticamente sem display."""

import time
from pathlib import Path

import pymupdf
import pytest

tk = pytest.importorskip("tkinter")

from src.config.catalog import all_tools  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    import os

    os.environ["PDF26_CONFIG_DIR"] = str(tmp_path_factory.mktemp("config"))
    try:
        from src.ui.app import PDF26App

        window = PDF26App()
    except tk.TclError as error:
        pytest.skip(f"Sem display para a interface: {error}")
    window.withdraw()
    errors = []
    window.report_callback_exception = lambda *exc: errors.append(exc)
    window.errors = errors
    yield window
    window.destroy()


@pytest.fixture(scope="module")
def pdf(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("arquivos") / "teste.pdf"
    doc = pymupdf.open()
    for number in range(1, 4):
        doc.new_page().insert_text((72, 72), f"Página {number}")
    doc.save(path)
    return path


def _wait(app, page, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while page.runner.running and time.time() < deadline:
        app.update()
        time.sleep(0.05)
    app.update()


def test_every_tool_page_opens(app, pdf):
    for tool in all_tools():
        accepts_pdf = tool.inputs is not None and ".pdf" in tool.inputs.extensions
        app.open_tool(tool.id, [pdf] if accepts_pdf else [])
        app.update()
    app.show_home("all")
    app.update()
    assert not app.errors


def test_generic_tool_runs(app, pdf):
    app.open_tool("rotate", [pdf])
    page = app.page
    page.run()
    _wait(app, page)
    assert page.status.cget("text").startswith("Concluído")
    assert (pdf.parent / "teste_girado.pdf").exists()
    app.show_home("all")


def test_validation_message(app):
    app.open_tool("merge")
    app.page.run()
    assert "Adicione" in app.page.status.cget("text")
    app.show_home("all")


def test_home_search_and_favorites(app):
    app.show_home("all")
    app.home.search.insert(0, "lgpd")
    app.home.refresh()
    assert "Resultados" in app.home._title.cget("text")
    app.home.clear_search()
    assert app.home.search.get() == ""
    favorite = app.toggle_favorite("ocr")
    assert favorite == app.prefs.is_favorite("ocr")


def test_editor_text_and_undo(app, pdf, tmp_path):
    work = tmp_path / "editar.pdf"
    work.write_bytes(pdf.read_bytes())
    app.open_tool("editor", [work])
    app.update()
    time.sleep(0.1)
    app.update()
    page = app.page
    assert page.session is not None
    page._edit(lambda session: session.add_shape(0, pymupdf.Rect(50, 50, 150, 120)))
    assert page.session.dirty and page.session.can_undo
    page.undo()
    page.session.dirty = False
    app.show_home("all")
