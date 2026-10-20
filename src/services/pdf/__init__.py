"""
Motor de PDF do PDF26 (PyMuPDF + pikepdf).

Cada função pública recebe `(job: JobContext, files: Sequence[Path], **opções)` e
devolve `ToolResult`. Módulos:

- organize: juntar, dividir, girar, remover/extrair páginas, montagem, N-up, livreto, marcadores, imagens
- edit: marca d'água, numeração, sobreposição, recorte, tamanho de página, metadados, achatar
- forms: leitura e preenchimento de formulários
- optimize: compressão, tons de cinza, web, OCR, reparo, rasterização, PDF/A
- security: senha, desbloqueio, tarjas (LGPD), metadados, gerador de senha, assinatura visual
- signature: assinatura digital com certificado A1 e verificação
- inspection: propriedades, pesquisa, comparação, preferências de exibição
- convert_to_pdf / convert_from_pdf / create / web: conversões e criação
- editor: sessão de edição interativa do Leitor/Editor
"""
