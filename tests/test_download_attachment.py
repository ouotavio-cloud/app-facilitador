"""Garante que baixar um anexo nunca pendura o app.

Este é o bug que travava a varredura ao chegar numa proposta: quando os
seletores do botão de baixar não batem com o Outlook real, o código antigo
saía do `expect_download` por `continue` — e sair assim fazia o Playwright
esperar o download inteiro (o timeout todo) por um clique que nunca
aconteceu, duas vezes, minutos parado por anexo.

O navegador falso aqui não fala com o Outlook. Ele registra uma coisa só:
se o app chegou a *esperar* um download. Quando não há acionador para
clicar, esperar seria o bug — o teste falha se isso voltar a acontecer.
"""

from app_facilitador import browser_client


class _LocatorFalso:
    def __init__(self, quantos: int):
        self._quantos = quantos

    @property
    def first(self):
        return self

    def count(self) -> int:
        return self._quantos

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def hover(self, timeout=None):
        pass

    def click(self, timeout=None):
        pass


class _DownloadFalso:
    """Finge o `expect_download`. O que importa é o __exit__.

    No Playwright real, sair do `with` sem exceção faz o gerenciador
    *esperar* o download. Marcamos isso: se aconteceu sem um clique ter
    disparado nada, é o congelamento voltando.
    """

    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._page.esperou_download = True
        return False

    @property
    def value(self):
        return self

    def save_as(self, destino):
        self._page.salvou = destino


class _PageFalsa:
    def __init__(self, tem_acionador: bool):
        self._tem_acionador = tem_acionador
        self.esperou_download = False
        self.salvou = None

    def locator(self, selector: str):
        if "data-facilitador-anexo" in selector:
            return _LocatorFalso(1)  # o anexo em si existe
        # seletores de botão/menu de download
        return _LocatorFalso(1 if self._tem_acionador else 0)

    def expect_download(self, timeout=None):
        return _DownloadFalso(self)


def test_nao_espera_download_quando_nao_ha_botao(tmp_path):
    """Sem acionador na tela: falha na hora, não pendura esperando."""
    page = _PageFalsa(tem_acionador=False)

    baixou = browser_client.download_attachment(page, "Proposta.pdf", tmp_path / "x.pdf")

    assert baixou is False
    assert page.esperou_download is False  # o ponto: nunca ficou esperando


def test_baixa_quando_o_acionador_existe(tmp_path):
    page = _PageFalsa(tem_acionador=True)
    destino = tmp_path / "x.pdf"

    baixou = browser_client.download_attachment(page, "Proposta.pdf", destino)

    assert baixou is True
    assert page.salvou == str(destino)


def test_devolve_falso_quando_o_anexo_nem_existe(tmp_path):
    class _SemAnexo(_PageFalsa):
        def locator(self, selector):
            return _LocatorFalso(0)

    assert (
        browser_client.download_attachment(
            _SemAnexo(tem_acionador=True), "x.pdf", tmp_path / "x.pdf"
        )
        is False
    )
