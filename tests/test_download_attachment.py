"""Garante que baixar um anexo funciona pelo menu "Salvar como" e nunca
pendura o app.

Dois comportamentos são travados aqui:

- **O caminho real do Outlook do usuário**: o cartão do anexo não tem botão
  de baixar; tem uma setinha (˅) que abre um menu com "Salvar como". O
  download precisa clicar na setinha e depois no item de salvar.

- **Anti-congelamento**: quando não há acionador nenhum na tela, o app não
  pode ficar esperando um download que nunca vem. Era o bug que travava a
  varredura ao chegar numa proposta — o teste falha se ele voltar.

O navegador falso não fala com o Outlook. Ele registra se o app chegou a
*esperar* um download; esperar sem um clique ter disparado nada é o bug.
"""

import re

from app_facilitador import browser_client


class _LocatorFalso:
    def __init__(self, page, quantos: int):
        self._page = page
        self._quantos = quantos

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def count(self) -> int:
        return self._quantos

    def locator(self, selector: str):
        # Sub-busca dentro do cartão do anexo (ex.: a setinha do menu).
        return self._page.locator(selector)

    def filter(self, has_text=None):
        # Filtro do item de menu por texto — devolve o próprio item.
        return self

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def hover(self, timeout=None):
        pass

    def click(self, timeout=None):
        # Como no Playwright: clicar num elemento que não existe levanta —
        # é assim que _baixar_pelo_menu sabe que faltou o item "Salvar como".
        if self._quantos == 0:
            raise RuntimeError("elemento inexistente")
        self._page.cliques.append("click")


class _DownloadFalso:
    """Finge o `expect_download`. O que importa é o __exit__.

    No Playwright real, sair do `with` sem exceção faz o gerenciador
    *esperar* o download. Marcamos isso: se aconteceu sem um acionador ter
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


class _TecladoFalso:
    def __init__(self, page):
        self._page = page

    def press(self, tecla: str):
        self._page.teclas.append(tecla)


class _PageFalsa:
    """Modela o cartão do anexo com setinha e o menu "Salvar como".

    `tem_botao_comum` existe para representar a LINHA da lista de mensagens,
    que tem botões (marcar como não lido, sinalizar, fixar) e nenhuma
    setinha. É o alvo em que o app não pode clicar.
    """

    def __init__(
        self, tem_anexo=True, tem_setinha=True, tem_item_salvar=True,
        tem_botao_comum=None, marca_perdida=False,
    ):
        self._tem_anexo = tem_anexo
        # `marca_perdida` simula o Outlook remontando o painel entre achar e
        # baixar, o que apaga a marca deixada em `find_attachments`.
        self._marca_presente = tem_anexo and not marca_perdida
        self.remarcou = 0
        self._tem_setinha = tem_setinha
        self._tem_item_salvar = tem_item_salvar
        # Um cartão com setinha também tem botão comum; sem dizer nada, é
        # esse o caso.
        self._tem_botao_comum = tem_setinha if tem_botao_comum is None else tem_botao_comum
        self.esperou_download = False
        self.salvou = None
        self.cliques = []
        self.teclas = []
        self.keyboard = _TecladoFalso(self)

    def evaluate(self, script, arg=None):
        """Refaz a marcação dos anexos, como o JS de produção faria."""
        self.remarcou += 1
        self._marca_presente = self._tem_anexo
        return []

    def locator(self, selector: str):
        if "data-facilitador-anexo" in selector:
            return _LocatorFalso(self, 1 if self._marca_presente else 0)
        if "aria-haspopup" in selector:
            return _LocatorFalso(self, 1 if self._tem_setinha else 0)
        if "button" in selector:
            return _LocatorFalso(self, 1 if self._tem_botao_comum else 0)
        # seletores do botão de hover (reserva): não existem neste Outlook
        return _LocatorFalso(self, 0)

    def get_by_role(self, role: str):
        return _LocatorFalso(self, 1 if self._tem_item_salvar else 0)

    def expect_download(self, timeout=None):
        return _DownloadFalso(self)


def test_baixa_pelo_menu_salvar_como(tmp_path):
    """Clica na setinha e depois em 'Salvar como' — o caminho real."""
    page = _PageFalsa()
    destino = tmp_path / "x.pdf"

    baixou = browser_client.download_attachment(page, "Proposta.pdf", destino)

    assert baixou is True
    assert page.salvou == str(destino)


def test_nao_espera_download_sem_acionador(tmp_path):
    """Sem setinha nem botão: falha na hora, não pendura esperando."""
    page = _PageFalsa(tem_setinha=False, tem_item_salvar=False)

    baixou = browser_client.download_attachment(page, "Proposta.pdf", tmp_path / "x.pdf")

    assert baixou is False
    assert page.esperou_download is False  # o ponto: nunca ficou esperando


def test_setinha_sem_item_de_salvar_nao_trava(tmp_path):
    """Menu abre mas não tem 'Salvar como' (ex.: só OneDrive): não pendura."""
    page = _PageFalsa(tem_setinha=True, tem_item_salvar=False)

    baixou = browser_client.download_attachment(page, "Proposta.pdf", tmp_path / "x.pdf")

    assert baixou is False


def test_devolve_falso_quando_o_anexo_nem_existe(tmp_path):
    page = _PageFalsa(tem_anexo=False)

    assert (
        browser_client.download_attachment(page, "x.pdf", tmp_path / "x.pdf") is False
    )


def test_marca_perdida_e_refeita_em_vez_de_desistir(tmp_path):
    """O Outlook remonta o painel e leva a marca junto.

    No log do usuário isso derrubava o e-mail inteiro de uma vez: um anexo
    demorava, o painel remontava, e os outros quatro falhavam no mesmo
    segundo com "não foi marcado na página". O anexo continua lá — basta
    procurar de novo.
    """
    page = _PageFalsa(marca_perdida=True)

    baixou = browser_client.download_attachment(page, "Proposta.pdf", tmp_path / "x.pdf")

    assert baixou is True
    assert page.remarcou == 1


def test_sem_setinha_nao_clica_em_botao_nenhum(tmp_path):
    """O bug do e-mail fixado, na origem: clicar "o último botão que houver".

    Numa linha da lista de mensagens os botões são marcar como não lido,
    sinalizar e **fixar** — e fixar é o último. A reserva que clicava no
    último botão do alvo fixava um e-mail a cada anexo que o app tentava
    baixar. Sem setinha, o certo é desistir sem tocar em nada.
    """
    page = _PageFalsa(tem_setinha=False, tem_botao_comum=True)

    baixou = browser_client.download_attachment(page, "Proposta.pdf", tmp_path / "x.pdf")

    assert baixou is False
    assert page.cliques == []  # o ponto: nenhum clique, nenhum e-mail fixado
    assert page.esperou_download is False


def test_fecha_o_menu_quando_a_tentativa_falha(tmp_path):
    """Menu aberto sobra na tela e intercepta o clique do anexo seguinte."""
    page = _PageFalsa(tem_setinha=True, tem_item_salvar=False)

    browser_client.download_attachment(page, "Proposta.pdf", tmp_path / "x.pdf")

    assert "Escape" in page.teclas


def test_nao_cria_a_pasta_quando_o_download_falha(tmp_path):
    """As pastas vazias que o usuário achou: árvore montada, nada dentro.

    A pasta era criada ao montar o caminho, antes de saber se o arquivo
    viria. Com o download falhando, sobrava `Obra/Processo/Fornecedor`
    vazia — parecendo que a proposta estava lá.
    """
    destino = tmp_path / "661" / "SUP.2026-186" / "Engeform" / "Proposta.pdf"
    page = _PageFalsa(tem_setinha=False)

    assert browser_client.download_attachment(page, "Proposta.pdf", destino) is False
    assert not destino.parent.exists()
    assert not (tmp_path / "661").exists()


def test_cria_a_pasta_ao_baixar_de_verdade(tmp_path):
    """E quando o arquivo vem, a pasta precisa existir para recebê-lo."""
    destino = tmp_path / "661" / "SUP.2026-186" / "Engeform" / "Proposta.pdf"
    page = _PageFalsa()

    assert browser_client.download_attachment(page, "Proposta.pdf", destino) is True
    assert destino.parent.is_dir()
    assert page.salvou == str(destino)


def test_rotulo_salvar_reconhece_salvar_como():
    """A regressão que causou tudo: o item era 'Salvar como', não 'Baixar'."""
    assert browser_client._ROTULO_SALVAR.search("Salvar como")
    assert browser_client._ROTULO_SALVAR.search("Save as")
    assert browser_client._ROTULO_SALVAR.search("Baixar")
    # "Salvar no OneDrive" não é download local — não deve casar.
    assert not browser_client._ROTULO_SALVAR.search("Salvar no OneDrive – engeform")
