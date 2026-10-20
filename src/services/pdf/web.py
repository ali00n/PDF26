"""
Página web / arquivo HTML para PDF com Selenium.

Usa Chrome ou Edge em modo headless e o comando `Page.printToPDF` do Chrome DevTools
Protocol. O Selenium Manager baixa o driver compatível automaticamente.
"""

from __future__ import annotations

import base64
import contextlib
import time
from pathlib import Path
from typing import Iterator, List, Sequence
from urllib.parse import urlparse

from ...domain.job import JobContext, ToolResult, safe_filename
from ...utils.exceptions import DependencyError, PDFError, ValidationError
from ...utils.logger import get_logger
from .common import PAPER_SIZES

logger = get_logger(__name__)

_PAGE_LOAD_TIMEOUT = 90
_SCRIPT_TIMEOUT = 120
_POINTS_PER_INCH = 72
_MM_PER_INCH = 25.4

# Rola a página até o fim para disparar carregamento sob demanda (lazy-load) e volta ao topo.
# O fim é verificado no tique seguinte para o último evento de rolagem ser entregue;
# o limite de passos evita laço infinito em páginas com rolagem infinita.
_SCROLL_THROUGH_JS = """
const done = arguments[arguments.length - 1];
const step = Math.max(400, window.innerHeight * 0.8);
const maxSteps = 300;
let y = 0;
let steps = 0;
const timer = setInterval(() => {
    if (y >= document.documentElement.scrollHeight || ++steps > maxSteps) {
        clearInterval(timer);
        window.scrollTo(0, 0);
        done(true);
        return;
    }
    window.scrollTo(0, y);
    y += step;
}, 150);
"""


def webpage_to_pdf(
    job: JobContext,
    files: Sequence[Path],
    urls: str = "",
    paper: str = "A4",
    landscape: bool = False,
    background: bool = True,
    margin_mm: float = 10,
    scale: float = 100,
    wait_seconds: float = 2,
    scroll: bool = True,
    browser: str = "auto",
) -> ToolResult:
    """Converte uma ou mais URLs (uma por linha) em PDF."""
    targets = _parse_urls(urls)
    print_options = _print_options(paper, landscape, background, margin_mm, scale)
    outputs = []
    with chromium_driver(browser) as driver:
        for index, url in enumerate(targets):
            job.progress(index, len(targets), f"Carregando {url}")
            try:
                driver.get(url)
            except Exception as error:
                raise PDFError(f"Não foi possível abrir {url}: {error}") from error
            _settle(driver, scroll, float(wait_seconds))
            name = safe_filename(driver.title or urlparse(url).netloc, fallback="pagina")
            target = job.output_file(name=name)
            target.write_bytes(_print_pdf(driver, print_options))
            outputs.append(target)
    return ToolResult(outputs)


def html_file_to_pdf(path: Path, target: Path) -> Path:
    with chromium_driver("auto") as driver:
        driver.get(path.resolve().as_uri())
        _settle(driver, scroll=False, wait_seconds=0.5)
        target.write_bytes(_print_pdf(driver, _print_options("A4", False, True, 10, 100)))
    return target


def _parse_urls(text: str) -> List[str]:
    urls = []
    for line in filter(None, (line.strip() for line in (text or "").splitlines())):
        url = line if "://" in line else f"https://{line}"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https", "file") or not (parsed.netloc or parsed.scheme == "file"):
            raise ValidationError(f"URL inválida: {line}", field="urls")
        urls.append(url)
    if not urls:
        raise ValidationError("Informe ao menos uma URL.", field="urls")
    return urls


def _print_options(paper: str, landscape: bool, background: bool, margin_mm: float, scale: float) -> dict:
    width, height = PAPER_SIZES.get(paper, PAPER_SIZES["A4"])
    margin = float(margin_mm) / _MM_PER_INCH
    return {
        "paperWidth": width / _POINTS_PER_INCH,
        "paperHeight": height / _POINTS_PER_INCH,
        "landscape": bool(landscape),
        "printBackground": bool(background),
        "marginTop": margin,
        "marginBottom": margin,
        "marginLeft": margin,
        "marginRight": margin,
        "scale": max(0.1, min(2.0, float(scale) / 100)),
        "preferCSSPageSize": False,
    }


def _settle(driver, scroll: bool, wait_seconds: float) -> None:
    from selenium.webdriver.support.ui import WebDriverWait

    WebDriverWait(driver, _PAGE_LOAD_TIMEOUT).until(lambda d: d.execute_script("return document.readyState") == "complete")
    if scroll:
        try:
            driver.execute_async_script(_SCROLL_THROUGH_JS)
        except Exception as error:
            logger.warning(f"Rolagem automática falhou: {error}")
    time.sleep(max(0.0, wait_seconds))


def _print_pdf(driver, options: dict) -> bytes:
    try:
        result = driver.execute_cdp_cmd("Page.printToPDF", options)
    except Exception as error:
        raise PDFError(f"O navegador não conseguiu gerar o PDF: {error}") from error
    return base64.b64decode(result["data"])


@contextlib.contextmanager
def chromium_driver(preference: str = "auto") -> Iterator:
    """Inicia Chrome (ou Edge) headless; Selenium Manager resolve o driver."""
    try:
        from selenium import webdriver
    except ImportError as error:
        raise DependencyError("Pacote 'selenium' não instalado. Execute: pip install selenium", dependency="selenium") from error

    order = {"chrome": ["chrome"], "edge": ["edge"]}.get(preference, ["chrome", "edge"])
    errors = []
    driver = None
    for name in order:
        options = webdriver.ChromeOptions() if name == "chrome" else webdriver.EdgeOptions()
        for argument in ("--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1366,900", "--no-first-run", "--disable-extensions", "--log-level=3"):
            options.add_argument(argument)
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        try:
            driver = webdriver.Chrome(options=options) if name == "chrome" else webdriver.Edge(options=options)
            break
        except Exception as error:
            errors.append(f"{name}: {str(error).splitlines()[0]}")
    if driver is None:
        raise DependencyError("Não foi possível iniciar o Chrome nem o Edge. " + " | ".join(errors), dependency="browser")
    driver.set_page_load_timeout(_PAGE_LOAD_TIMEOUT)
    driver.set_script_timeout(_SCRIPT_TIMEOUT)
    try:
        yield driver
    finally:
        driver.quit()
