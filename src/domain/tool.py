"""Modelos de domínio das ferramentas: categorias, opções configuráveis e especificação de entrada."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from .job import ToolResult

FileTypes = Tuple[Tuple[str, str], ...]

PDF_TYPES: FileTypes = (("Arquivos PDF", "*.pdf"),)
IMAGE_TYPES: FileTypes = (("Imagens", "*.png *.jpg *.jpeg *.jpe *.bmp *.gif *.tif *.tiff *.webp *.heic *.heif *.jfif *.ico"),)
OFFICE_TYPES: FileTypes = (("Documentos Office", "*.doc *.docx *.docm *.rtf *.odt *.xls *.xlsx *.xlsm *.ods *.csv *.ppt *.pptx *.odp *.pub *.vsd *.vsdx *.odg"),)
TEXT_TYPES: FileTypes = (("Texto e Markdown", "*.txt *.md *.markdown *.log *.csv *.json *.xml"),)
CERT_TYPES: FileTypes = (("Certificado A1", "*.pfx *.p12"),)
ALL_TYPES: FileTypes = (("Todos os arquivos", "*.*"),)


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    color: str


CATEGORIES: Tuple[Category, ...] = (
    Category("create", "Criar", "#0EA5E9"),
    Category("organize", "Organizar", "#6366F1"),
    Category("edit", "Editar", "#F59E0B"),
    Category("optimize", "Otimizar", "#10B981"),
    Category("security", "Segurança", "#EF4444"),
    Category("view", "Visualizar e verificar", "#8B5CF6"),
    Category("to_pdf", "Converter para PDF", "#F97316"),
    Category("from_pdf", "Converter de PDF", "#14B8A6"),
)
CATEGORY_BY_ID: Dict[str, Category] = {category.id: category for category in CATEGORIES}

# Condição de visibilidade: (chave de outra opção, valores que tornam esta opção visível)
ShowIf = Optional[Tuple[str, Tuple[Any, ...]]]


@dataclass(frozen=True)
class Option:
    key: str
    label: str
    default: Any = None
    help: str = ""
    show_if: ShowIf = None


@dataclass(frozen=True)
class Choice(Option):
    choices: Tuple[Tuple[str, str], ...] = ()  # (valor, rótulo)
    segmented: bool = False


@dataclass(frozen=True)
class Number(Option):
    minimum: float = 0
    maximum: float = 100
    step: float = 1
    integer: bool = True
    unit: str = ""


@dataclass(frozen=True)
class Text(Option):
    placeholder: str = ""
    secret: bool = False
    multiline: bool = False
    height: int = 120
    required: bool = False


@dataclass(frozen=True)
class Flag(Option):
    pass


@dataclass(frozen=True)
class Color(Option):
    pass


@dataclass(frozen=True)
class FilePick(Option):
    filetypes: FileTypes = ALL_TYPES
    required: bool = False


@dataclass(frozen=True)
class Signature(Option):
    """Assinatura manuscrita: desenhada na tela, carregada de imagem ou digitada."""

    required: bool = True


@dataclass(frozen=True)
class FileInput:
    filetypes: FileTypes = PDF_TYPES
    min_files: int = 1
    max_files: Optional[int] = None
    label: str = "Arquivos"

    @property
    def extensions(self) -> Tuple[str, ...]:
        patterns = " ".join(pattern for _, pattern in self.filetypes).split()
        return tuple(pattern.lstrip("*").lower() for pattern in patterns if pattern != "*.*")


Runner = Callable[..., ToolResult]
Prefill = Callable[[Path], Dict[str, Any]]


@dataclass(frozen=True)
class ToolSpec:
    """
    Especificação declarativa de uma ferramenta.

    `run(job, files, **opções)` executa a operação; `page` define a tela usada
    ("generic" monta o formulário a partir de `options`).
    """

    id: str
    name: str
    description: str
    category: str
    icon: str
    run: Optional[Runner] = None
    inputs: Optional[FileInput] = FileInput()
    options: Tuple[Option, ...] = ()
    keywords: str = ""
    page: str = "generic"
    prefill: Optional[Prefill] = None
    run_label: str = "Executar"

    @property
    def color(self) -> str:
        return CATEGORY_BY_ID[self.category].color

    def matches(self, query: str) -> bool:
        terms = normalize(query).split()
        haystack = normalize(f"{self.name} {self.description} {self.keywords} {CATEGORY_BY_ID[self.category].label}")
        return all(term in haystack for term in terms)


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para busca."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
