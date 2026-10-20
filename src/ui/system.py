"""Integração com o sistema operacional: abrir arquivos/pastas e mensagens de erro amigáveis."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from tkinter import messagebox

from ..utils.exceptions import PDF26Error, OperationCancelledError
from ..utils.logger import get_logger

logger = get_logger(__name__)

TEMP_DIR = Path(tempfile.gettempdir()) / "pdf26"


def temp_file(name: str) -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR / name


def open_path(path: Path) -> None:
    """Abre arquivo ou pasta com o programa padrão do sistema."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606 - caminho escolhido pelo usuário
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as error:
        messagebox.showerror("PDF26", f"Não foi possível abrir:\n{path}\n\n{error}")


def reveal(path: Path) -> None:
    """Abre a pasta do arquivo com ele selecionado (Windows Explorer)."""
    if sys.platform == "win32" and path.is_file():
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        open_path(path if path.is_dir() else path.parent)


def describe_error(error: BaseException) -> str:
    """Mensagem para o usuário: erros conhecidos mostram só a mensagem; inesperados são registrados no log."""
    if isinstance(error, OperationCancelledError):
        return "Operação cancelada."
    if isinstance(error, PDF26Error):
        return error.message
    logger.error("Erro inesperado", exc_info=error)
    return f"Erro inesperado: {error}\n\nDetalhes foram registrados na pasta logs do projeto."
