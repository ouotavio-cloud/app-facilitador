"""Abertura do navegador: Chromium com perfil persistente.

Duas decisões estão travadas aqui por terem custado retrabalho:

- **Chromium, não o Edge instalado.** Usar o Edge economizava 150 MB no
  download, mas no Windows corporativo do usuário ele não preservava a
  conta entre execuções — era preciso logar de novo o tempo todo.
- **Perfil persistente, não `storage_state`.** Salvar cookies e
  localStorage num arquivo perde o que o login da Microsoft guarda em
  IndexedDB, e a sessão morria cedo.
"""

import pytest

from app_facilitador import browser_client, config


class _FakeChromium:
    def __init__(self, falhar=False):
        self.chamadas = []
        self._falhar = falhar

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.chamadas.append({"user_data_dir": user_data_dir, **kwargs})
        if self._falhar:
            raise RuntimeError(
                "Executable doesn't exist at /caminho/chromium\n"
                "linha extra de ruído com instruções de instalação"
            )
        return "contexto"

    # Presente de propósito: se alguém voltar a usar `launch`, os testes
    # que checam o perfil persistente falham em vez de passar por acaso.
    def launch(self, **kwargs):
        raise AssertionError("O app precisa usar um perfil persistente")


class _FakePlaywright:
    def __init__(self, falhar=False):
        self.chromium = _FakeChromium(falhar)


@pytest.fixture
def perfil(tmp_path, monkeypatch):
    destino = tmp_path / "navegador"
    monkeypatch.setattr(config, "BROWSER_PROFILE_DIR", destino)
    return destino


def test_abre_o_chromium_com_o_perfil_do_app(perfil):
    playwright = _FakePlaywright()

    resultado = browser_client.open_browser_context(playwright, headless=True)

    assert resultado == "contexto"
    assert playwright.chromium.chamadas[0]["user_data_dir"] == str(perfil)


def test_cria_a_pasta_do_perfil_na_primeira_vez(perfil):
    assert not perfil.exists()

    browser_client.open_browser_context(_FakePlaywright(), headless=True)

    assert perfil.is_dir()


def test_sem_navegador_o_erro_diz_como_resolver(perfil):
    """Quem roda pelo código-fonte precisa saber que falta um comando."""
    with pytest.raises(RuntimeError) as erro:
        browser_client.open_browser_context(_FakePlaywright(falhar=True), headless=True)

    mensagem = str(erro.value)
    assert "playwright install chromium" in mensagem
    # Só a primeira linha da falha do Playwright: o resto é ruído.
    assert "linha extra de ruído" not in mensagem


class _FakeContextComAba:
    def __init__(self, abas):
        self.pages = abas
        self.abas_criadas = 0

    def new_page(self):
        self.abas_criadas += 1
        return "aba nova"


def test_reaproveita_a_aba_que_o_perfil_ja_abre():
    """Criar outra deixaria uma janela em branco sobrando na tela."""
    contexto = _FakeContextComAba(["aba existente"])

    assert browser_client.first_page(contexto) == "aba existente"
    assert contexto.abas_criadas == 0


def test_cria_uma_aba_quando_o_contexto_vem_vazio():
    contexto = _FakeContextComAba([])

    assert browser_client.first_page(contexto) == "aba nova"
