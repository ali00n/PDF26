# PDF26

Caixa de ferramentas PDF para desktop, inspirada no PDF24 Creator: **57 ferramentas que rodam offline**. Os arquivos não saem do computador.

Feito em Python com **CustomTkinter** (interface) e **PyMuPDF/pikepdf** (motor de PDF).

## Ferramentas

| Categoria | Ferramentas |
|-----------|-------------|
| **Criar** | Escrever PDF, Página web para PDF (Selenium), Imagens para PDF, Gerar QR Code, PDF em branco |
| **Organizar** | Juntar, Dividir, Organizar páginas (miniaturas com arrastar e soltar), Remover páginas, Extrair páginas, Girar, Páginas por folha, Criar livreto, Dividir páginas ao meio, Marcadores, Extrair imagens |
| **Editar** | Editor (texto, destaque, formas, desenho, nota, imagem, assinatura, tarja), Marca d'água, Numerar páginas, Sobrepor PDF, Recortar, Alterar tamanho da página, Informações do documento, Preencher formulário, Achatar |
| **Otimizar** | Comprimir, Tons de cinza, Otimizar para web, OCR, Reparar, Rasterizar, PDF/A |
| **Segurança** | Proteger com senha (AES-256), Desbloquear, Assinar (manuscrita), Assinatura digital com certificado A1 (.pfx), Tarjar dados (LGPD: CPF, CNPJ, e-mail, telefone, CEP), Remover metadados, Gerar senha |
| **Visualizar** | Leitor, Comparar PDFs, Pesquisar em vários PDFs, Propriedades, Verificar assinaturas, Preferências de exibição |
| **Converter para PDF** | Office, imagens, texto/Markdown, HTML, EPUB, SVG, XPS |
| **Converter de PDF** | Imagens, Word, Excel, PowerPoint, texto, HTML, Markdown, SVG; conversão entre formatos de imagem (HEIC, WEBP, PNG, JPG...) |

Interface com busca (sem acento), favoritas, recentes, tema claro/escuro, arrastar e soltar arquivos e processamento em segundo plano com progresso e cancelamento. O arquivo de entrada nunca é sobrescrito.

## Instalação

Requer Python 3.11+ (testado no Windows 10/11).

```bash
git clone https://github.com/ali00n/PDF26.git
cd PDF26
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python src/main.py                # tela inicial
python src/main.py contrato.pdf   # abre direto no Leitor
pythonw PDF26.pyw                 # Windows, sem janela de console (ou duplo clique)
```

Atalhos: `Ctrl+F` pesquisar ferramenta · `Ctrl+Enter` executar · `Esc` voltar · `Ctrl+O` abrir PDF no Leitor.

## Programas externos (opcionais)

São detectados automaticamente; os caminhos também podem ser informados em **Configurações**.

| Programa | Usado em |
|----------|----------|
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) + idioma Português | OCR |
| [Ghostscript](https://ghostscript.com/releases/gsdnld.html) | PDF/A e tons de cinza preservando o texto |
| Microsoft Office (via pywin32) ou LibreOffice | Office → PDF |
| Google Chrome ou Microsoft Edge | Página web/HTML → PDF |

## Estrutura

```
src/
├── main.py                  # ponto de entrada
├── config/                  # preferências do usuário e catálogo de ferramentas
├── domain/                  # ToolSpec, opções, JobContext (progresso, cancelamento, nomes de saída)
├── services/pdf/            # motor de PDF, sem interface e testável
├── ui/                      # CustomTkinter: app, pages, widgets, dialogs
└── utils/                   # logger e exceções
tests/                       # testes do motor e da interface
docs/PDF26.md                # arquitetura e como adicionar ferramentas
```

## Testes

```bash
pytest -v
```

São 59 testes do motor de PDF e 5 da interface (os da interface são pulados sem display).
