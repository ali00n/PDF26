"""
PDF26 - Caixa de ferramentas PDF offline (CustomTkinter + PyMuPDF)

Ponto de entrada da aplicação.

Uso:
    python src/main.py                 # abre a tela inicial
    python src/main.py arquivo.pdf     # abre o arquivo no Leitor de PDF
    pythonw PDF26.pyw                  # Windows, sem janela de console
"""

import sys
from pathlib import Path

# Adiciona a raiz do projeto ao path (necessário para execução direta)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.logger import get_logger

logger = get_logger("main")


def run(argv=None) -> None:
    """Inicia a interface. Arquivos passados na linha de comando abrem no Leitor."""
    from src.ui.app import PDF26App

    files = [Path(arg) for arg in (sys.argv[1:] if argv is None else argv) if Path(arg).is_file()]
    logger.info("Iniciando PDF26")
    app = PDF26App(initial_files=files)
    app.mainloop()
    logger.info("PDF26 encerrado")


if __name__ == "__main__":
    run()
