"""Conexão com o Outlook: detecção automática, saída manual e falhas.

Estes testes existem por causa de uma trava real: a espera dependia só de
reconhecer a lista de e-mails na tela, e quando o Outlook do usuário abriu
de um jeito que os seletores não reconheceram, o app ficou "aguardando
login" para sempre, sem dizer onde tinha parado nem oferecer saída.
"""

import pytest

from app_facilitador import browser_client, config


class _FakePage:
    """Página que só vira "caixa de entrada" depois de N verificações."""

    def __init__(self, rodadas_ate_a_caixa=None, url="https://login.microsoftonline.com/x"):
        self._restantes = rodadas_ate_a_caixa
        self.url = url
        self.esperas = 0
        self.trazida_para_frente = False

    def goto(self, url):
        # Ir para o Outlook sem sessão salva cai na tela de login — é o
        # redirecionamento que o usuário vê, e o que o app precisa saber
        # descrever enquanto espera.
        pass

    def bring_to_front(self):
        self.trazida_para_frente = True

    def query_selector(self, selector):
        if self._restantes is None:
            return None
        if self._restantes <= 0:
            self.url = "https://outlook.office.com/mail/"
            return object()
        self._restantes -= 1
        return None

    def wait_for_timeout(self, ms):
        self.esperas += 1


class _FakePageFechada(_FakePage):
    def wait_for_timeout(self, ms):
        raise RuntimeError("Target page, context or browser has been closed")


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.estado_salvo_em = None

    def new_page(self):
        return self._page

    def storage_state(self, path):
        self.estado_salvo_em = path


class _FakeBrowser:
    def __init__(self, page):
        self.context = _FakeContext(page)
        self.fechado = False

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        self.fechado = True


@pytest.fixture
def navegador_falso(tmp_path, monkeypatch):
    """Substitui o Playwright inteiro; nenhum navegador é aberto de verdade."""
    monkeypatch.setattr(config, "BROWSER_STATE_PATH", tmp_path / "state.json")
    # Espera instantânea: sem isto cada rodada custaria um segundo real.
    monkeypatch.setattr(browser_client, "LOGIN_POLL_MS", 1)
    monkeypatch.setattr(browser_client, "LOGIN_TIMEOUT_MS", 5)

    criados = {}

    def _fabricar(page):
        browser = _FakeBrowser(page)
        criados["browser"] = browser

        class _FakePlaywright:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(browser_client, "sync_playwright", lambda: _FakePlaywright())
        monkeypatch.setattr(browser_client, "launch_browser", lambda pw, headless: browser)
        return browser

    criados["fabricar"] = _fabricar
    return criados


def test_detecta_a_caixa_de_entrada_e_salva_o_acesso(navegador_falso, tmp_path):
    page = _FakePage(rodadas_ate_a_caixa=2)
    browser = navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(on_status=lambda _: None)

    assert browser.context.estado_salvo_em == str(config.BROWSER_STATE_PATH)
    assert browser.fechado


def test_traz_a_janela_de_login_para_a_frente(navegador_falso):
    """Ela abre atrás do painel, e o usuário fica esperando sem ver onde logar."""
    page = _FakePage(rodadas_ate_a_caixa=0)
    navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(on_status=lambda _: None)

    assert page.trazida_para_frente


def test_o_botao_ja_entrei_encerra_a_espera(navegador_falso):
    """O caso que travou de verdade: a caixa nunca é reconhecida."""
    page = _FakePage(rodadas_ate_a_caixa=None)
    browser = navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(
        on_status=lambda _: None, should_finish=lambda: True
    )

    assert browser.context.estado_salvo_em is not None


def test_sem_deteccao_e_sem_confirmacao_o_tempo_esgota(navegador_falso):
    page = _FakePage(rodadas_ate_a_caixa=None)
    browser = navegador_falso["fabricar"](page)

    with pytest.raises(RuntimeError, match="não foi concluído a tempo"):
        browser_client.login_and_save_session(on_status=lambda _: None)

    assert browser.fechado
    assert browser.context.estado_salvo_em is None


def test_janela_fechada_no_meio_vira_erro_explicativo(navegador_falso):
    page = _FakePageFechada(rodadas_ate_a_caixa=None)
    navegador_falso["fabricar"](page)

    with pytest.raises(RuntimeError, match="fechada antes do login terminar"):
        browser_client.login_and_save_session(on_status=lambda _: None)


def test_o_andamento_diz_em_que_pagina_o_navegador_esta(navegador_falso):
    """Uma espera muda não deixa ninguém descobrir por que travou."""
    page = _FakePage(rodadas_ate_a_caixa=None)
    navegador_falso["fabricar"](page)
    mensagens = []

    with pytest.raises(RuntimeError):
        browser_client.login_and_save_session(on_status=mensagens.append)

    assert any("tela de login da Microsoft" in m for m in mensagens)
    assert any("Já entrei" in m for m in mensagens)


@pytest.mark.parametrize(
    "url, esperado",
    [
        ("https://login.microsoftonline.com/common/oauth2/authorize", "tela de login da Microsoft"),
        ("https://outlook.office.com/mail/", "Outlook aberto"),
        ("https://outlook.office365.com/mail/inbox", "Outlook aberto"),
    ],
)
def test_descricao_da_pagina_atual(url, esperado):
    assert browser_client._login_page_description(_FakePage(url=url)) == esperado
