"""Contexto de execução de uma ferramenta: progresso, cancelamento e nomes de saída."""

from __future__ import annotations

import itertools
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Union

from ..utils.exceptions import OperationCancelledError

PathLike = Union[str, Path]
ProgressCallback = Callable[[float, str], None]

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_STEM = 120


@dataclass
class ToolResult:
    """Resultado de uma ferramenta: arquivos gerados e/ou relatório em texto."""

    files: List[Path] = field(default_factory=list)
    text: str = ""
    message: str = ""


def safe_filename(name: str, fallback: str = "arquivo") -> str:
    """Remove caracteres inválidos no Windows e limita o tamanho do nome."""
    cleaned = _INVALID_CHARS.sub("_", name).strip().rstrip(". ")
    return cleaned[:_MAX_STEM] or fallback


def unique_path(path: Path) -> Path:
    """Retorna `path` ou, se já existir, `nome (1).ext`, `nome (2).ext`..."""
    if not path.exists():
        return path
    for index in itertools.count(1):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise AssertionError("unreachable")


class JobContext:
    """
    Dependências de uma execução de ferramenta.

    Args:
        output_dir: Pasta de saída escolhida pelo usuário. None = mesma pasta do arquivo de entrada.
        fallback_dir: Pasta usada quando a ferramenta não recebe arquivos (ex.: gerar QR Code).
        on_progress: Callback (fração 0..1, mensagem) chamado pela thread de trabalho.
        cancel_event: Evento compartilhado com a interface para interromper a execução.
    """

    def __init__(
        self,
        output_dir: Optional[PathLike] = None,
        fallback_dir: Optional[PathLike] = None,
        on_progress: Optional[ProgressCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else None
        self.fallback_dir = Path(fallback_dir) if fallback_dir else Path.home() / "Documents" / "PDF26"
        self._on_progress = on_progress
        self._cancel_event = cancel_event or threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        self._cancel_event.set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise OperationCancelledError("Operação cancelada pelo usuário.")

    def progress(self, current: float, total: float, message: str = "") -> None:
        """Informa progresso e interrompe a execução se o usuário cancelou."""
        self.check_cancelled()
        if self._on_progress:
            fraction = min(1.0, max(0.0, current / total)) if total else 0.0
            self._on_progress(fraction, message)

    def target_dir(self, source: Optional[PathLike] = None) -> Path:
        directory = self.output_dir or (Path(source).parent if source else self.fallback_dir)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def output_file(self, source: Optional[PathLike] = None, suffix: str = "", ext: str = ".pdf", name: Optional[str] = None, directory: Optional[Path] = None) -> Path:
        """
        Caminho de saída sem sobrescrever nada.

        Exemplo: source=C:/docs/contrato.pdf, suffix="comprimido" -> C:/docs/contrato_comprimido.pdf
        """
        stem = safe_filename(name or self._stem(source, suffix))
        return unique_path((directory or self.target_dir(source)) / f"{stem}{ext}")

    def output_folder(self, source: Optional[PathLike] = None, suffix: str = "", name: Optional[str] = None) -> Path:
        """Cria uma subpasta exclusiva para saídas com vários arquivos."""
        stem = safe_filename(name or self._stem(source, suffix))
        folder = unique_path(self.target_dir(source) / stem)
        folder.mkdir(parents=True)
        return folder

    @staticmethod
    def _stem(source: Optional[PathLike], suffix: str) -> str:
        if source is None:
            return suffix or "resultado"
        stem = Path(source).stem
        return f"{stem}_{suffix}" if suffix else stem
