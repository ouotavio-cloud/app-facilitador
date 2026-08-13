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

    def __init__(
        self,
        rodadas_ate_a_caixa=None,
        url="https://login.microsoftonline.com/x",
        rodadas_navegando=0,
        fechada=False,
    ):
        self._restantes = rodadas_ate_a_caixa
        self._navegando = rodadas_navegando
        self._fechada = fechada
        self.url = url
        self.trazida_para_frente = False

    def goto(self, url):
        # Ir para o Outlook sem sessão salva cai na tela de login — é o
        # redirecionamento que o usuário vê, e o que o app precisa saber
        # descrever enquanto espera.
        pass

    def bring_to_front(self):
        self.trazida_para_frente = True

    def is_closed(self):
        return self._fechada

    def query_selector(self, selector):
        if self._navegando > 0:
            self._navegando -= 1
            raise RuntimeError(
                "Execution context was destroyed, most likely because of a navigation"
            )
        if self._restantes is None:
            return None
        if self._restantes <= 0:
            self.url = "https://outlook.office.com/mail/"
            return object()
        self._restantes -= 1
        return None


class _FakeContext:
    """Contexto persistente: é ele que guarda o perfil, sem navegador à parte."""

    def __init__(self, page):
        self.pages = [page]
        self.fechado = False

    def new_page(self):
        raise AssertionError("O perfil persistente já abre com uma aba")

    def close(self):
        self.fechado = True


@pytest.fixture
def navegador_falso(tmp_path, monkeypatch):
    """Substitui o Playwright inteiro; nenhum navegador é aberto de verdade."""
    monkeypatch.setattr(config, "LOGIN_MARKER_PATH", tmp_path / ".conectado")
    monkeypatch.setattr(config, "BROWSER_PROFILE_DIR", tmp_path / "navegador")
    # Espera instantânea: sem isto cada rodada custaria um segundo real.
    monkeypatch.setattr(browser_client.session, "LOGIN_POLL_MS", 1)
    monkeypatch.setattr(browser_client.session, "LOGIN_TIMEOUT_MS", 5)

    criados = {}

    def _fabricar(page):
        context = _FakeContext(page)
        criados["context"] = context

        class _FakePlaywright:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(browser_client.session, "sync_playwright", lambda: _FakePlaywright())
        monkeypatch.setattr(
            browser_client.session, "open_browser_context", lambda pw, headless: context
        )
        return context

    criados["fabricar"] = _fabricar
    return criados


def test_detecta_a_caixa_de_entrada_e_registra_o_login(navegador_falso):
    page = _FakePage(rodadas_ate_a_caixa=2)
    context = navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(on_status=lambda _: None)

    assert config.LOGIN_MARKER_PATH.exists()
    # Fechar o contexto é o que grava o perfil em disco; sem isso a conta
    # não sobreviveria até a próxima execução.
    assert context.fechado


def test_traz_a_janela_de_login_para_a_frente(navegador_falso):
    """Ela abre atrás do painel, e o usuário fica esperando sem ver onde logar."""
    page = _FakePage(rodadas_ate_a_caixa=0)
    navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(on_status=lambda _: None)

    assert page.trazida_para_frente


def test_o_botao_ja_entrei_encerra_a_espera(navegador_falso):
    """O caso que travou de verdade: a caixa nunca é reconhecida."""
    page = _FakePage(rodadas_ate_a_caixa=None)
    context = navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(
        on_status=lambda _: None, should_finish=lambda: True
    )

    assert config.LOGIN_MARKER_PATH.exists()
    assert context.fechado


def test_sem_deteccao_e_sem_confirmacao_o_tempo_esgota(navegador_falso):
    page = _FakePage(rodadas_ate_a_caixa=None)
    context = navegador_falso["fabricar"](page)

    with pytest.raises(RuntimeError, match="não foi concluído a tempo"):
        browser_client.login_and_save_session(on_status=lambda _: None)

    assert context.fechado
    assert not config.LOGIN_MARKER_PATH.exists()


def test_janela_que_fecha_na_hora_aponta_outra_copia_do_app(navegador_falso):
    """Sumir em segundos não é o usuário desistindo — a causa é outra."""
    page = _FakePage(rodadas_ate_a_caixa=None, fechada=True)
    navegador_falso["fabricar"](page)

    with pytest.raises(RuntimeError, match="outra cópia do App"):
        browser_client.login_and_save_session(on_status=lambda _: None)


def test_janela_fechada_depois_de_um_tempo_e_tratada_como_desistencia(
    navegador_falso, monkeypatch
):
    monkeypatch.setattr(browser_client.session, "LOGIN_TIMEOUT_MS", 20)
    monkeypatch.setattr(browser_client.session, "_ROUNDS_TOO_EARLY", 2)

    page = _FakePage(rodadas_ate_a_caixa=None)
    navegador_falso["fabricar"](page)

    # Fecha só depois de algumas rodadas, como quem desistiu no meio.
    consultas = {"n": 0}
    original = page.is_closed

    def _fechou_depois():
        consultas["n"] += 1
        return consultas["n"] > 4

    page.is_closed = _fechou_depois
    assert original() is False

    with pytest.raises(RuntimeError, match="fechada antes do login terminar"):
        browser_client.login_and_save_session(on_status=lambda _: None)


def test_redirecionamento_do_login_nao_e_confundido_com_janela_fechada(navegador_falso):
    """O caso que quebrou a v3 na máquina do usuário.

    O login da Microsoft passa por vários redirecionamentos, e consultar a
    página durante um deles levanta erro sem que nada esteja errado.
    Tratar isso como "janela fechada" abortava o login no primeiro
    redirect — antes mesmo de a pessoa digitar a senha.
    """
    page = _FakePage(rodadas_ate_a_caixa=1, rodadas_navegando=2)
    navegador_falso["fabricar"](page)

    browser_client.login_and_save_session(on_status=lambda _: None)

    assert config.LOGIN_MARKER_PATH.exists()


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
    assert browser_client.session._login_page_description(_FakePage(url=url)) == esperado
