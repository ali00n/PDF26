"""
Localização de programas externos opcionais.

- Tesseract (OCR)            -> pasta tessdata
- Ghostscript (PDF/A, cinza) -> gswin64c.exe / gs
- LibreOffice (Office->PDF)  -> soffice.exe
- Microsoft Office (Office->PDF via COM, apenas Windows)

Caminhos configurados pelo usuário têm prioridade (ver `configure`).
"""

from __future__ import annotations

import glob
import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from ...utils.exceptions import DependencyError

IS_WINDOWS = sys.platform == "win32"


@dataclass
class ExternalPaths:
    ghostscript: str = ""
    soffice: str = ""
    tessdata: str = ""


_overrides = ExternalPaths()


def configure(ghostscript: str = "", soffice: str = "", tessdata: str = "") -> None:
    """Define caminhos escolhidos pelo usuário e limpa o cache de detecção."""
    _overrides.ghostscript, _overrides.soffice, _overrides.tessdata = ghostscript, soffice, tessdata
    for cached in (find_ghostscript, find_soffice, find_tessdata):
        cached.cache_clear()


def _existing(path: str) -> Optional[str]:
    return path if path and Path(path).exists() else None


def _program_files(*patterns: str) -> Optional[str]:
    roots = [os.environ.get(var, "") for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for pattern in patterns:
            matches = sorted(glob.glob(os.path.join(root, pattern)), reverse=True)  # versão mais recente primeiro
            if matches:
                return matches[0]
    return None


@lru_cache(maxsize=None)
def find_ghostscript() -> Optional[str]:
    return (
        _existing(_overrides.ghostscript)
        or next(filter(None, (shutil.which(name) for name in ("gswin64c", "gswin32c", "gs"))), None)
        or (_program_files(r"gs\gs*\bin\gswin64c.exe", r"gs\gs*\bin\gswin32c.exe") if IS_WINDOWS else None)
    )


@lru_cache(maxsize=None)
def find_soffice() -> Optional[str]:
    return (
        _existing(_overrides.soffice)
        or next(filter(None, (shutil.which(name) for name in ("soffice", "libreoffice"))), None)
        or (_program_files(r"LibreOffice\program\soffice.exe") if IS_WINDOWS else None)
    )


@lru_cache(maxsize=None)
def find_tessdata() -> Optional[str]:
    candidates = [_overrides.tessdata, os.environ.get("TESSDATA_PREFIX", "")]
    if IS_WINDOWS:
        candidates.append(_program_files(r"Tesseract-OCR\tessdata") or "")
    tesseract = shutil.which("tesseract")
    if tesseract:
        candidates.append(str(Path(tesseract).parent / "tessdata"))
    candidates += glob.glob("/usr/share/tesseract-ocr/*/tessdata") + ["/usr/share/tessdata", "/usr/local/share/tessdata", "/opt/homebrew/share/tessdata"]
    for candidate in filter(None, candidates):
        if list(Path(candidate).glob("*.traineddata")):
            return str(Path(candidate))
    return None


def tesseract_languages() -> List[str]:
    tessdata = find_tessdata()
    if not tessdata:
        return []
    return sorted(path.stem for path in Path(tessdata).glob("*.traineddata") if path.stem != "osd")


def office_available() -> bool:
    """pywin32 instalado no Windows (a existência do Office só é confirmada ao converter)."""
    return IS_WINDOWS and importlib.util.find_spec("win32com") is not None


def require_ghostscript() -> str:
    path = find_ghostscript()
    if not path:
        raise DependencyError(
            "Ghostscript não encontrado. Instale em https://ghostscript.com/releases/gsdnld.html ou informe o caminho em Configurações.",
            dependency="ghostscript",
        )
    return path


def require_tessdata(language: str) -> str:
    tessdata = find_tessdata()
    if not tessdata:
        raise DependencyError(
            "Tesseract OCR não encontrado. Instale o Tesseract (github.com/UB-Mannheim/tesseract/wiki) com o idioma Português ou informe a pasta tessdata em Configurações.",
            dependency="tesseract",
        )
    missing = [lang for lang in language.split("+") if not (Path(tessdata) / f"{lang}.traineddata").exists()]
    if missing:
        raise DependencyError(f"Idioma(s) de OCR não instalado(s): {', '.join(missing)}. Pasta: {tessdata}", dependency="tesseract")
    return tessdata
