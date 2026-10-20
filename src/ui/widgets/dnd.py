"""Arrastar e soltar arquivos do Explorer (opcional: requer o pacote tkinterdnd2)."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from ...utils.logger import get_logger

logger = get_logger(__name__)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # recurso opcional
    DND_FILES, TkinterDnD = None, None

_enabled = False


def install(root) -> bool:
    """Carrega o tkdnd na janela raiz. Retorna False se indisponível."""
    global _enabled
    if TkinterDnD is None:
        return False
    try:
        root.TkdndVersion = TkinterDnD._require(root)
        _enabled = True
    except Exception as error:  # tkdnd ausente/incompatível: segue sem arrastar e soltar
        logger.warning(f"Arrastar e soltar indisponível: {error}")
    return _enabled


def enable_drop(widget, on_drop: Callable[[List[Path]], None]) -> None:
    """
    Registra `widget` e todos os descendentes como alvo de arquivos.

    Widgets do CustomTkinter são compostos (frame + canvas + label internos); registrar a
    árvore inteira garante que soltar sobre qualquer parte visível funcione.
    """
    if not _enabled:
        return

    def handler(event):
        on_drop([Path(item) for item in widget.tk.splitlist(event.data)])
        return event.action

    pending = [widget]
    while pending:
        target = pending.pop()
        pending.extend(target.winfo_children())
        try:
            target.drop_target_register(DND_FILES)
            target.dnd_bind("<<Drop>>", handler)
        except Exception as error:
            logger.debug(f"Alvo de soltar não registrado: {error}")
