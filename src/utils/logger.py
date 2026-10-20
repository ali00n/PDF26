"""Logging no console (com cores) e em arquivo diário em logs/AAAA-MM-DD.log."""

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

# Cores ANSI por nível
COLORS = {"DEBUG": "\033[36m", "INFO": "\033[32m", "WARNING": "\033[33m", "ERROR": "\033[31m", "CRITICAL": "\033[35m", "RESET": "\033[0m"}
_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


class ColoredFormatter(logging.Formatter):
    """Formatter com cores para o console."""

    def format(self, record):
        record = logging.makeLogRecord(record.__dict__)
        record.levelname = f"{COLORS.get(record.levelname, COLORS['RESET'])}{record.levelname}{COLORS['RESET']}"
        return super().format(record)


def get_logger(name: str, log_to_file: bool = True) -> logging.Logger:
    """
    Obtém logger configurado (console INFO+ e arquivo DEBUG+).

    Args:
        name: Nome do logger (geralmente __name__)
        log_to_file: Se True, também grava em logs/
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    if sys.stdout is not None:  # pythonw (PDF26.pyw) não tem console
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.INFO)
        console.setFormatter(ColoredFormatter(_FORMAT, datefmt="%H:%M:%S"))
        logger.addHandler(console)

    if log_to_file:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_DIR / f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(file_handler)
    return logger
