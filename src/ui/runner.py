"""Execução de operações em segundo plano com progresso entregue na thread da interface."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

from ..domain.job import JobContext
from ..utils.logger import get_logger

logger = get_logger(__name__)

_POLL_MS = 60


class JobRunner:
    """
    Roda `work(job)` numa thread. Os callbacks são chamados na thread do Tk:
    on_progress(fração, mensagem), on_success(resultado), on_error(exceção).
    """

    def __init__(self, widget: tk.Misc):
        self._widget = widget
        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._callbacks: dict = {}

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        work: Callable[[JobContext], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[BaseException], None],
        on_progress: Optional[Callable[[float, str], None]] = None,
        output_dir: Optional[Path] = None,
        fallback_dir: Optional[Path] = None,
    ) -> None:
        if self.running:
            raise RuntimeError("Já existe uma operação em andamento.")
        self._cancel = threading.Event()
        self._callbacks = {"progress": on_progress, "success": on_success, "error": on_error}
        job = JobContext(output_dir=output_dir, fallback_dir=fallback_dir, on_progress=lambda fraction, message: self._events.put(("progress", fraction, message)), cancel_event=self._cancel)

        def target():
            try:
                self._events.put(("success", work(job)))
            except Exception as error:  # repassado à interface, que decide como exibir
                logger.debug(traceback.format_exc())
                self._events.put(("error", error))

        self._thread = threading.Thread(target=target, name="pdf26-job", daemon=True)
        self._thread.start()
        self._poll()

    def cancel(self) -> None:
        self._cancel.set()

    def _poll(self) -> None:
        try:
            while True:
                kind, *payload = self._events.get_nowait()
                callback = self._callbacks.get(kind)
                if callback:
                    callback(*payload)
        except queue.Empty:
            pass
        if self.running or not self._events.empty():
            try:
                self._widget.after(_POLL_MS, self._poll)
            except tk.TclError:  # janela fechada durante a operação
                self.cancel()
