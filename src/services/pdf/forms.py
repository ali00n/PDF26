"""Leitura e preenchimento de formulários PDF (AcroForm)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

import pymupdf

from ...domain.job import JobContext, ToolResult
from ...utils.exceptions import PDFError
from .common import opened, save_pdf

FieldValue = Union[str, bool]

_KINDS = {
    pymupdf.PDF_WIDGET_TYPE_TEXT: "text",
    pymupdf.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
    pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
    pymupdf.PDF_WIDGET_TYPE_COMBOBOX: "choice",
    pymupdf.PDF_WIDGET_TYPE_LISTBOX: "choice",
}


@dataclass
class FormField:
    name: str
    kind: str  # text | checkbox | radio | choice
    page: int
    value: FieldValue = ""
    choices: List[str] = field(default_factory=list)
    multiline: bool = False


def read_fields(path: Path, password: Optional[str] = None) -> List[FormField]:
    """Lista os campos editáveis; botões de rádio do mesmo grupo viram um único campo com opções."""
    fields: Dict[str, FormField] = {}
    with opened(path, password) as doc:
        for page in doc:
            for widget in page.widgets():
                kind = _KINDS.get(widget.field_type)
                if kind is None or widget.field_flags & pymupdf.PDF_FIELD_IS_READ_ONLY:
                    continue
                name = widget.field_name or f"campo_{widget.xref}"
                if kind == "radio":
                    entry = fields.setdefault(name, FormField(name, "radio", page.number))
                    state = str(widget.on_state())
                    entry.choices.append(state)
                    if _is_on(widget.field_value):
                        entry.value = state
                elif name not in fields:
                    fields[name] = FormField(
                        name,
                        kind,
                        page.number,
                        value=_is_on(widget.field_value) if kind == "checkbox" else str(widget.field_value or ""),
                        choices=list(widget.choice_values or []),
                        multiline=bool(widget.field_flags & pymupdf.PDF_TX_FIELD_IS_MULTILINE),
                    )
    return list(fields.values())


def _is_on(value) -> bool:
    return value not in (None, "", "Off", False)


def fill_form(job: JobContext, path: Path, values: Dict[str, FieldValue], flatten: bool = False, output: Optional[Path] = None) -> ToolResult:
    """Preenche os campos informados em `values` e salva uma cópia (opcionalmente achatada)."""
    with opened(path) as doc:
        if not doc.is_form_pdf:
            raise PDFError(f"'{path.name}' não possui campos de formulário.")
        changed = 0
        for page in doc:
            job.progress(page.number, doc.page_count, "Preenchendo campos")
            for widget in page.widgets():
                if widget.field_name not in values:
                    continue
                value = values[widget.field_name]
                if widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                    widget.field_value = widget.on_state() if value else "Off"
                elif widget.field_type == pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON:
                    widget.field_value = widget.on_state() if str(widget.on_state()) == str(value) else "Off"
                else:
                    widget.field_value = str(value)
                widget.update()
                changed += 1
        if flatten:
            doc.bake(annots=False, widgets=True)
        target = save_pdf(doc, output or job.output_file(path, "preenchido"))
    return ToolResult([target], message=f"{changed} campo(s) atualizado(s).")
