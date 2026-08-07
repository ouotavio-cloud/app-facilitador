"""Escolha do navegador: usar o que já está instalado, não baixar um.

O app é distribuído como executável que não deve exigir preparo nenhum.
Depender do Chromium que o Playwright baixa à parte quebraria essa
premissa — daí preferir o Edge, presente em qualquer Windows.
"""

import pytest

from app_facilitador import browser_client


class _FakeChromium:
    """Finge ser o `playwright.chromium`, aceitando só os canais informados."""

    def __init__(self, canais_disponiveis):
        self._disponiveis = canais_disponiveis
        self.tentativas = []

    def launch(self, headless, channel=None):
        self.tentativas.append(channel)
        if channel not in self._disponiveis:
            raise RuntimeError(
                f"Executável não encontrado para {channel}\nlinha extra de ruído"
            )
        return f"navegador:{channel}"


class _FakePlaywright:
    def __init__(self, canais_disponiveis):
        self.chromium = _FakeChromium(canais_disponiveis)


def test_prefere_o_edge_quando_disponivel():
    playwright = _FakePlaywright({"msedge", "chrome", None})

    resultado = browser_client.launch_browser(playwright, headless=True)

    assert resultado == "navegador:msedge"
    assert playwright.chromium.tentativas == ["msedge"]


def test_cai_para_o_chrome_quando_nao_ha_edge():
    playwright = _FakePlaywright({"chrome", None})

    resultado = browser_client.launch_browser(playwright, headless=True)

    assert resultado == "navegador:chrome"


def test_usa_o_chromium_empacotado_como_ultimo_recurso():
    """Quem roda pelo código-fonte no Linux não tem Edge nem Chrome."""
    playwright = _FakePlaywright({None})

    resultado = browser_client.launch_browser(playwright, headless=True)

    assert resultado == "navegador:None"
    assert playwright.chromium.tentativas == ["msedge", "chrome", None]


def test_sem_nenhum_navegador_o_erro_diz_o_que_foi_tentado():
    """Um "falha ao abrir o navegador" seco não ajudaria a resolver nada."""
    playwright = _FakePlaywright(set())

    with pytest.raises(RuntimeError) as erro:
        browser_client.launch_browser(playwright, headless=True)

    mensagem = str(erro.value)
    assert "msedge" in mensagem
    assert "chrome" in mensagem
    assert "Chromium empacotado" in mensagem
    # Só a primeira linha de cada falha: o erro do Playwright tem dezenas
    # de linhas de instruções de instalação que aqui seriam ruído.
    assert "linha extra de ruído" not in mensagem
