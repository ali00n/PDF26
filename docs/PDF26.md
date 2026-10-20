# PDF26 — Arquitetura

## Camadas

| Camada | Pasta | Responsabilidade |
|--------|-------|------------------|
| Domínio | `src/domain/` | `ToolSpec`, opções (`Choice`, `Number`, `Text`, `Flag`, `Color`, `FilePick`, `Signature`), `JobContext`, `ToolResult` |
| Serviços | `src/services/pdf/` | Operações de PDF puras: recebem arquivos e opções, devolvem `ToolResult`. Sem Tk. |
| Configuração | `src/config/catalog.py`, `app_config.py` | Liga ferramentas a serviços; preferências do usuário |
| Apresentação | `src/ui/` | CustomTkinter: telas, widgets e diálogos |

A interface nunca chama PyMuPDF diretamente (exceto miniaturas no organizador); toda regra fica em `services/pdf`.

## Contrato de um serviço

```python
def compress(job: JobContext, files: Sequence[Path], level: str = "medium", grayscale: bool = False) -> ToolResult:
    for index, path in enumerate(files):
        job.progress(index, len(files), f"Comprimindo {path.name}")   # também verifica cancelamento
        with opened(path) as doc:
            ...
            target = save_pdf(doc, job.output_file(path, "comprimido"))  # nunca sobrescreve
    return ToolResult(outputs, text="relatório opcional")
```

- Os nomes dos parâmetros são as chaves das opções no catálogo (`tests/test_pdf_services.py::test_catalog_ids_unique_and_options_match_signatures` garante isso).
- Erros esperados: `ValidationError` (entrada do usuário), `PDFError` (arquivo), `DependencyError` (programa externo).

## Adicionar uma ferramenta

1. Implemente a função em `src/services/pdf/<módulo>.py` seguindo o contrato acima.
2. Registre em `src/config/catalog.py`:

```python
ToolSpec(
    "minha_ferramenta", "Nome na tela", "Descrição curta", "edit", "ABC",
    meu_modulo.minha_funcao,
    inputs=PDFS,
    options=(Number("dpi", "Resolução", 150, minimum=72, maximum=600, unit="dpi"),),
    keywords="palavras para a busca",
)
```

3. Escreva um teste em `tests/test_pdf_services.py`. A tela é gerada automaticamente a partir das opções.

Opções podem depender de outras: `show_if=("modo", ("valor1", "valor2"))`. `prefill=funcao(path) -> dict` preenche o formulário ao adicionar o arquivo.

## Coordenadas em páginas giradas (PyMuPDF)

- `page.rect` é a área **visível** (já girada); anotações, `search_for`, `insert_*` usam coordenadas **não giradas**.
- Visível → PDF: `rect * page.derotation_matrix`; PDF → visível: `rect * page.rotation_matrix`.
- Carimbos (marca d'água, numeração, assinatura): desenhe numa página temporária do tamanho visível e aplique com `common.stamp_page()`.
- `show_pdf_page` ignora a rotação da origem e não desenha anotações: use `common.flattened_copy()` antes de compor páginas (N-up, livreto, redimensionar).

## Particularidades do CustomTkinter 6

- `CTkFrame` vazio tem 200×200 px por padrão: sempre informe `width`/`height` em frames que podem ficar vazios.
- `CTkEntry` com `textvariable` não mostra placeholder; use `theme.set_entry_text()` para trocar o texto mantendo o placeholder.
- Widgets Tk puros (Canvas) não seguem o tema: use `theme.color(PAR)` e redesenhe em `on_appearance_change()`.

## PyMuPDF 2.0

- `find_tables().extract()` separa pontuação em outra linha ("1 234 56\n. ,"); o texto de cada célula é lido pela caixa (`convert_from_pdf._table_rows`).
- `Rect.center` não existe; use `common.rect_center()`.
