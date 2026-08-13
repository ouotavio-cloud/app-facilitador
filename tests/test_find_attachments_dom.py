"""Roda o JavaScript que acha os anexos contra o HTML real do Outlook.

Estes são os testes dos dois piores defeitos que o app já teve, e os dois
tinham a mesma origem: a busca de anexos varria a página inteira e não
distinguia o cartão de anexo do painel de leitura da LINHA da lista de
mensagens.

- **Anexo do e-mail errado.** Cada linha da lista exibe o nome dos arquivos
  que aquele e-mail carrega. Varrendo tudo, os anexos das outras conversas
  entravam na lista do e-mail aberto e eram gravados na pasta dele.
- **E-mail fixado.** Marcada a linha, o download procurava um acionador
  nela e caía no último botão — "Manter esta mensagem na parte superior de
  sua pasta". Cada anexo que o app tentava baixar fixava um e-mail na caixa
  do usuário.

A estrutura do HTML abaixo (papéis, atributos e a ordem dos botões da
linha) foi copiada do diagnóstico capturado na caixa real do usuário; o
conteúdo é inventado, para não guardar e-mail de ninguém no repositório. É
o que dá valor ao teste: o seletor é conferido contra a página que o
Outlook realmente monta, não contra uma que eu desenhei para passar.

O JavaScript é o de produção, executado num navegador de verdade — não uma
cópia. Sem browser instalado (é o caso da CI, que compila antes de baixar o
Chromium), o teste se pula em vez de falhar.
"""

import glob
import os

import pytest

from app_facilitador import attachments, browser_client

playwright_api = pytest.importorskip("playwright.sync_api")


def _lancar_chromium(playwright):
    """Chromium do Playwright, onde quer que ele esteja nesta máquina."""
    try:
        return playwright.chromium.launch()
    except Exception:  # noqa: BLE001 - navegador ausente ou noutro caminho
        pass

    raiz = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    for padrao in ("chromium-*/chrome-linux/chrome", "chromium-*/chrome-win/chrome.exe"):
        for caminho in sorted(glob.glob(os.path.join(raiz or "", padrao))):
            try:
                return playwright.chromium.launch(executable_path=caminho)
            except Exception:  # noqa: BLE001 - tenta o próximo
                continue
    pytest.skip("nenhum Chromium do Playwright disponível nesta máquina")


@pytest.fixture(scope="module")
def pagina():
    with playwright_api.sync_playwright() as playwright:
        navegador = _lancar_chromium(playwright)
        pagina = navegador.new_page()
        yield pagina
        navegador.close()


def _linha_da_lista(conv_id: str, arquivo: str) -> str:
    """Uma linha da lista de mensagens, com os anexos que ela anuncia.

    Os três botões, nesta ordem, são os do Outlook real — e o último é o de
    fixar, que era o que o download acabava clicando.
    """
    return f"""
    <div role="option" data-convid="{conv_id}" tabindex="0" aria-selected="false"
         aria-label="Tem anexos Fulano de Tal Assunto qualquer Qua, 05/08"
         data-focusable-row="true" class="jGG6V gDC9O UWKUc">
      <div class="lHRXq hDNlA" tabindex="-1">
        <button type="button" aria-label="Marcar como não lido"
                title="Marcar como não lido"></button>
        <button type="button" aria-label="Sinalizar esta mensagem"
                title="Sinalizar esta mensagem"></button>
        <button type="button" aria-label="Manter esta mensagem na parte superior de sua pasta"
                title="Manter esta mensagem na parte superior de sua pasta"></button>
        <div class="qAePI Jc4VX disableTextSelection dapZe">
          <div title="{arquivo}" class="GmWAd rpi8D">
            <div class="yUXK7 AVFDW F4Hsb ZreOl" title="{arquivo}">{arquivo}</div>
          </div>
          <div class="gy2aJ Ejrkd qAePI BzoU5 evkUo">+3</div>
        </div>
      </div>
    </div>
    """


def _cartao_de_anexo(arquivo: str, tamanho: str = "300 KB") -> str:
    """Um anexo do painel de leitura: [role=option] com a setinha (˅)."""
    return f"""
    <div role="option" aria-label="{arquivo} Abrir {tamanho}" tabindex="0" class="GpKSR C1V5C">
      <div draggable="true"><div class="feh0T"><div class="JA9Uf YyULm">
        <div class="uDIro">
          <div class="VlyYV PQeLQ QEiYT" title="{arquivo}">{arquivo}</div>
          <div class="rO2wz" title="{tamanho}"><span>{tamanho}</span></div>
        </div>
        <div class="o4euS">
          <button type="button" aria-label="Mais ações" aria-haspopup="true"
                  aria-expanded="false" title="Mais ações"></button>
        </div>
      </div></div></div>
    </div>
    """


def _montar_outlook(linhas: list[str], anexos_abertos: list[str]) -> str:
    """A tela do Outlook: lista de mensagens à esquerda, e-mail aberto à direita."""
    return f"""
    <div role="region" aria-label="Painel de navegação"></div>
    <div role="listbox" aria-label="Lista de mensagens" class="Cz7T5">
      {"".join(linhas)}
    </div>
    <div role="main" aria-label="Painel de Leitura" class="Mq3cC">
      <div role="document" aria-label="Corpo da mensagem">Segue nossa proposta.</div>
      <div class="T3idP kQkuc hg7Eg">
        <div role="listbox" aria-label="anexos de arquivo" class="E_kRz srnS5">
          {"".join(anexos_abertos)}
        </div>
      </div>
    </div>
    """


def _achar(pagina) -> list[str]:
    return pagina.evaluate(
        browser_client.downloads._JS_FIND_ATTACHMENTS, sorted(attachments.DOCUMENT_EXTENSIONS)
    )


def _marcados(pagina) -> list[str]:
    return pagina.evaluate(
        """() => Array.from(document.querySelectorAll('[data-facilitador-anexo]'))
                     .map(el => el.getAttribute('data-facilitador-anexo'))"""
    )


def test_acha_so_os_anexos_do_email_aberto(pagina):
    """O defeito principal: anexo de outra conversa entrando na lista.

    Três e-mails na lista, cada um anunciando um arquivo; o aberto tem
    outros dois. Só os dois do painel de leitura podem sair daqui.
    """
    pagina.set_content(
        _montar_outlook(
            linhas=[
                _linha_da_lista("conv-1", "NOTA FISCAL DE OUTRO EMAIL.pdf"),
                _linha_da_lista("conv-2", "Requisicao de outro email.xlsx"),
                _linha_da_lista("conv-3", "Contrato de outro email.docx"),
            ],
            anexos_abertos=[
                _cartao_de_anexo("Proposta Comercial 0018532-2026.pdf"),
                _cartao_de_anexo("Planilha de precos.xlsx", "88 KB"),
            ],
        )
    )

    assert _achar(pagina) == [
        "Proposta Comercial 0018532-2026.pdf",
        "Planilha de precos.xlsx",
    ]


def test_nunca_marca_a_linha_da_lista_de_mensagens(pagina):
    """A raiz do e-mail fixado: nada com `data-convid` pode virar alvo.

    Se uma linha da lista fosse marcada, o download procuraria a setinha
    nela, não acharia, e o clique cairia no botão de fixar.
    """
    pagina.set_content(
        _montar_outlook(
            linhas=[_linha_da_lista("conv-1", "Proposta de outro email.pdf")],
            anexos_abertos=[_cartao_de_anexo("Proposta Comercial.pdf")],
        )
    )
    _achar(pagina)

    marcadas = pagina.evaluate(
        """() => document.querySelectorAll('[data-convid] [data-facilitador-anexo],'
                                         + '[data-convid][data-facilitador-anexo]').length"""
    )
    assert marcadas == 0
    assert _marcados(pagina) == ["Proposta Comercial.pdf"]


def test_o_alvo_marcado_tem_a_setinha_do_menu(pagina):
    """O cartão marcado precisa conter o acionador que o download usa.

    É o contrato entre achar e baixar: `download_attachment` procura
    `[aria-haspopup]` dentro do que foi marcado.
    """
    pagina.set_content(
        _montar_outlook(
            linhas=[_linha_da_lista("conv-1", "Outro.pdf")],
            anexos_abertos=[_cartao_de_anexo("Proposta Comercial.pdf")],
        )
    )
    _achar(pagina)

    tem_setinha = pagina.evaluate(
        """() => {
            const alvo = document.querySelector('[data-facilitador-anexo]');
            return Boolean(alvo && alvo.querySelector('[aria-haspopup]'));
        }"""
    )
    assert tem_setinha is True


def test_limpa_as_marcas_do_email_anterior(pagina):
    """Marca velha em e-mail novo faria o download pegar o arquivo antigo.

    O Outlook não recarrega a página ao trocar de e-mail: o que sobra do
    anterior continua no DOM se ninguém apagar.
    """
    pagina.set_content(
        _montar_outlook([], [_cartao_de_anexo("Proposta antiga.pdf")])
    )
    assert _achar(pagina) == ["Proposta antiga.pdf"]

    # O mesmo cartão continua na página, e um e-mail novo abre ao lado.
    pagina.evaluate(
        """html => {
            document.querySelector('[role="listbox"][aria-label="anexos de arquivo"]')
                    .insertAdjacentHTML('beforeend', html);
        }""",
        _cartao_de_anexo("Proposta nova.pdf"),
    )
    pagina.evaluate(
        """() => {
            const cartoes = document.querySelectorAll('[role="option"]');
            cartoes[0].remove();  // o e-mail anterior fechou
        }"""
    )

    assert _achar(pagina) == ["Proposta nova.pdf"]
    assert _marcados(pagina) == ["Proposta nova.pdf"]


def test_ignora_anexo_que_nao_e_documento(pagina):
    """Logotipo e assinatura não são proposta e não podem entrar."""
    pagina.set_content(
        _montar_outlook(
            linhas=[],
            anexos_abertos=[
                _cartao_de_anexo("logotipo-da-empresa.png", "12 KB"),
                _cartao_de_anexo("Proposta Comercial.pdf"),
            ],
        )
    )

    assert _achar(pagina) == ["Proposta Comercial.pdf"]


class TestAbrirEmail:
    """`open_message` só pode devolver True quando o painel de fato trocou.

    O sintoma na caixa do usuário era o pior possível: o app clicava na
    linha, esperava dois segundos fixos e lia o painel. Quando o clique não
    pegava, ele lia os anexos do e-mail ANTERIOR e os arquivava no processo
    deste — baixando sempre os mesmos arquivos e não baixando o que o resumo
    dizia estar baixando.
    """

    def _tela(self, selecionada: str | None, anexos: list[str]) -> str:
        linhas = []
        for conv in ("conv-1", "conv-2"):
            sel = "true" if conv == selecionada else "false"
            linhas.append(
                f'<div role="option" data-convid="{conv}" aria-selected="{sel}"'
                f' aria-label="Fulano Assunto {conv}"><button>x</button></div>'
            )
        cartoes = "".join(_cartao_de_anexo(a) for a in anexos)
        return f"""
        <div role="listbox" aria-label="Lista de mensagens">{''.join(linhas)}</div>
        <div role="main" aria-label="Painel de Leitura">
          <div role="listbox" aria-label="anexos de arquivo">{cartoes}</div>
        </div>
        """

    def test_abre_quando_a_linha_fica_selecionada_e_o_painel_troca(self, pagina):
        pagina.set_content(self._tela("conv-1", ["Antiga.pdf"]))
        antes = browser_client.inbox._reading_pane_fingerprint(pagina)

        # O Outlook seleciona conv-2 e troca os anexos do painel.
        pagina.set_content(self._tela("conv-2", ["Proposta Nova.pdf"]))

        assert browser_client.inbox._reading_pane_switched(pagina, "conv-2", antes) is True

    def test_recusa_quando_o_painel_nao_trocou(self, pagina, monkeypatch):
        """O clique selecionou a linha, mas o painel continua no e-mail antigo."""
        monkeypatch.setattr(browser_client.inbox, "_PANE_SWITCH_TIMEOUT_MS", 600)
        pagina.set_content(self._tela("conv-2", ["Antiga.pdf"]))
        antes = browser_client.inbox._reading_pane_fingerprint(pagina)

        assert browser_client.inbox._reading_pane_switched(pagina, "conv-2", antes) is False

    def test_recusa_quando_a_linha_nem_foi_selecionada(self, pagina, monkeypatch):
        """O clique não pegou: conv-1 segue selecionada, e pedimos conv-2."""
        monkeypatch.setattr(browser_client.inbox, "_PANE_SWITCH_TIMEOUT_MS", 600)
        pagina.set_content(self._tela("conv-1", ["Antiga.pdf"]))
        antes = "impressão de outro momento"

        assert browser_client.inbox._reading_pane_switched(pagina, "conv-2", antes) is False

    def test_a_impressao_inclui_os_nomes_dos_anexos(self, pagina):
        """É o que a varredura vai ler em seguida — é o que precisa ter mudado."""
        pagina.set_content(self._tela("conv-1", ["Proposta Comercial.pdf"]))

        assert "Proposta Comercial.pdf" in browser_client.inbox._reading_pane_fingerprint(pagina)


def test_email_sem_anexo_nao_devolve_nada(pagina):
    """Sem painel de anexos, a lista de mensagens não pode virar resultado."""
    pagina.set_content(
        _montar_outlook(
            linhas=[
                _linha_da_lista("conv-1", "Proposta de outro email.pdf"),
                _linha_da_lista("conv-2", "Planilha de outro email.xlsx"),
            ],
            anexos_abertos=[],
        )
    )

    assert _achar(pagina) == []
