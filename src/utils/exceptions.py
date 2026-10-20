"""Hierarquia de exceções do PDF26."""

from typing import Any, Dict, Optional


class PDF26Error(Exception):
    """Base de todos os erros esperados do aplicativo (exibidos ao usuário sem traceback)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self):
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class ValidationError(PDF26Error):
    """Entrada inválida do usuário (opção, seleção de páginas, quantidade de arquivos)."""

    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.field = field
        super().__init__(message, details)
        if field:
            self.details["field"] = field


class PDFError(PDF26Error):
    """Falha em operação de PDF (arquivo inválido, senha incorreta, página inexistente...)."""

    def __init__(self, message: str, file: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.file = file
        super().__init__(message, details)
        if file:
            self.details["file"] = file


class DependencyError(PDF26Error):
    """Dependência externa ausente (Tesseract, Ghostscript, LibreOffice, Office, navegador ou pacote Python)."""

    def __init__(self, message: str, dependency: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        self.dependency = dependency
        super().__init__(message, details)
        if dependency:
            self.details["dependency"] = dependency


class OperationCancelledError(PDF26Error):
    """Operação interrompida pelo usuário."""
