"""PDF26 - Caixa de ferramentas PDF offline (CustomTkinter + PyMuPDF)."""

import sys

__version__ = "1.0.0"

# Com o pacote pymupdf_layout instalado, `import pymupdf` carrega e ativa os modelos ONNX
# de análise de layout (~3 s e dezenas de MB). Só o PDF -> Markdown precisa deles: o
# carregamento fica bloqueado aqui e é liberado em convert_from_pdf.to_markdown.
sys.modules.setdefault("pymupdf.layout", None)
