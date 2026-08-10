"""Desfixar e-mails: só clica quando reconhece o controle com segurança.

O bug que motivou esta faxina (ver CONTINUIDADE.md) nasceu de um clique "no
botão que houver" quando o acionador esperado não estava na tela. Fazer a
mesma coisa aqui, só que para desafixar, seria repetir o erro na direção
oposta. Por isso o único comportamento que importa testar é: sem um rótulo
reconhecível, `unpin_message` não clica em NADA — nem no primeiro botão, nem
no último, nem em qualquer um.
"""

from app_facilitador import browser_client


class _ControleFalso:
    """Um controle dentro da linha: existe (e é clicável) ou não existe."""

    def __init__(self, linha, existe: bool):
        self._linha = linha
        self._existe = existe

    @property
    def first(self):
        return self

    def count(self) -> int:
        return 1 if self._existe else 0

    def click(self, timeout=None):
        if not self._existe:
            # Playwright real levantaria ao clicar num locator de count()==0;
            # o teste não pode nem chegar aqui se o código estiver certo.
            raise AssertionError("clicou num controle que não existe")
        self._linha.cliques.append("desafixou")


class _LinhaFalsa:
    """A linha `[data-convid=...]` da mensagem, com os controles configurados."""

    def __init__(self, tem_rotulo_explicito=False, tem_aria_pressed=False):
        self._tem_rotulo_explicito = tem_rotulo_explicito
        self._tem_aria_pressed = tem_aria_pressed
        self.cliques = []

    @property
    def first(self):
        return self

    def count(self) -> int:
        return 1

    def locator(self, selector: str):
        # O fake decide pelo trecho do seletor, não pelo texto inteiro —
        # sobrevive a reformulação do CSS desde que os termos-chave
        # continuem os mesmos.
        if "não manter" in selector:
            return _ControleFalso(self, self._tem_rotulo_explicito)
        if "aria-pressed" in selector:
            return _ControleFalso(self, self._tem_aria_pressed)
        raise AssertionError(f"seletor inesperado dentro da linha: {selector!r}")

    def click(self, timeout=None):
        raise AssertionError("clicou na linha inteira, e não num controle dela")


class _LinhaInexistente:
    @property
    def first(self):
        return self

    def count(self) -> int:
        return 0


class _PageFalsa:
    """A página: só sabe devolver a linha de uma conversa, ou nenhuma."""

    def __init__(self, linha=None):
        self._linha = linha if linha is not None else _LinhaInexistente()

    def locator(self, selector: str):
        assert "data-convid" in selector, f"esperava buscar a linha, veio {selector!r}"
        return self._linha


def test_desafixa_quando_o_rotulo_diz_explicitamente_para_nao_manter():
    linha = _LinhaFalsa(tem_rotulo_explicito=True)
    page = _PageFalsa(linha)

    assert browser_client.unpin_message(page, "conv-1") is True
    assert linha.cliques == ["desafixou"]


def test_desafixa_pelo_aria_pressed_quando_nao_ha_rotulo_explicito():
    """Reserva: o Outlook pode manter o mesmo texto e sinalizar só por estado."""
    linha = _LinhaFalsa(tem_aria_pressed=True)
    page = _PageFalsa(linha)

    assert browser_client.unpin_message(page, "conv-1") is True
    assert linha.cliques == ["desafixou"]


def test_nao_clica_em_nada_sem_controle_identificado():
    """O ponto central: sem rótulo reconhecível, zero cliques — nunca um chute."""
    linha = _LinhaFalsa()
    page = _PageFalsa(linha)

    assert browser_client.unpin_message(page, "conv-1") is False
    assert linha.cliques == []


def test_linha_que_sumiu_da_tela_nao_quebra():
    page = _PageFalsa(linha=None)

    assert browser_client.unpin_message(page, "conv-1") is False
