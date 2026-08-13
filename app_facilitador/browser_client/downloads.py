"""Achar e baixar os anexos do e-mail que está aberto no painel de leitura.

É a parte mais frágil e a mais perigosa do app: frágil porque o Outlook
não expõe um botão de download estável, e perigosa porque um clique errado
mexe na caixa de e-mail do usuário. Os dois piores defeitos que este app
já teve nasceram aqui (anexo arquivado no processo errado e e-mail fixado
sem querer — ver CONTINUIDADE.md, v13 e v16).

A disciplina que saiu dali e vale para todo este módulo: **nunca clicar
"no botão que houver"**. Sem um acionador reconhecido com segurança, é
melhor não baixar do que arriscar mexer na caixa do usuário.
"""

import re
import unicodedata

from playwright.sync_api import Page

from app_facilitador import attachments, logs

_log = logs.get_logger("browser")

# Quanto esperar o download COMEÇAR depois do clique. Curto de propósito:
# um clique no acionador certo dispara o download em segundos. Se nada
# começa nesse tempo, o botão tentado estava errado — e é melhor falhar
# rápido e tentar a próxima forma do que pendurar o app. Era aqui que a
# varredura travava: com um timeout de 2 minutos por tentativa, cada
# e-mail com proposta prendia o app por minutos esperando um download que
# nunca vinha, porque os seletores do painel de leitura não bateram.
#
# O tempo de o arquivo terminar de baixar não é limitado aqui: uma vez
# começado, `save_as` espera o quanto for (proposta com projeto é pesada e
# a rede da obra nem sempre ajuda). O risco de um download começar e travar
# para sempre existe, mas é raro perto do de um seletor errado.
_DOWNLOAD_START_TIMEOUT_MS = 20_000

# Localiza os anexos do e-mail ABERTO, e só os dele.
#
# A versão anterior varria `[aria-label], [title]` da página inteira atrás
# de qualquer rótulo terminado em ".pdf", ".xlsx" e afins, e subia daí até
# achar um ancestral com botão. Parecia robusto — descreve o conteúdo, não
# a aparência — e era a origem dos dois piores defeitos do app:
#
#   1. **Anexo do e-mail errado.** As linhas da lista de mensagens também
#      exibem o nome dos arquivos que cada e-mail carrega. Varrendo a
#      página toda, os anexos de OUTRAS conversas entravam na lista do
#      e-mail aberto — e, como a lista vem antes do painel de leitura no
#      DOM, era a linha da lista que acabava marcada.
#   2. **E-mail fixado.** Marcada a linha da lista, o download procurava
#      nela um acionador e caía no último botão da linha, que é "Manter
#      esta mensagem na parte superior de sua pasta". Cada tentativa de
#      baixar fixava um e-mail na caixa do usuário.
#
# Agora partimos do cartão do anexo, não do nome do arquivo. No Outlook do
# usuário ele é `[role="option"]` dentro do `[role="listbox"]` de anexos, e
# tem a setinha (˅) "Mais ações" que abre o menu com "Salvar como". As
# linhas da lista de mensagens também são `[role="option"]` — o que as
# separa, e foi conferido contra o HTML real (ver `dump_message_debug`), é
# que linha de mensagem tem `data-convid` e nenhum `aria-haspopup`, e
# cartão de anexo tem `aria-haspopup` e nenhum `data-convid`.
_JS_FIND_ATTACHMENTS = """
extensoes => {
    // As marcas do e-mail anterior morrem aqui. Sem isto, o cartão de um
    // e-mail já fechado continuaria marcado e o download seguinte clicaria
    // nele — anexo de uma conversa gravado na pasta de outra.
    for (const velho of document.querySelectorAll('[data-facilitador-anexo]')) {
        velho.removeAttribute('data-facilitador-anexo');
    }

    const extensaoDe = nome => {
        const ponto = nome.lastIndexOf('.');
        return ponto < 0 ? '' : nome.slice(ponto).toLowerCase();
    };

    // O nome está no `title` de um filho do cartão ("Proposta.pdf") e, junto
    // com ação e tamanho, no aria-label do cartão ("Proposta.pdf Abrir 300
    // KB"). O `title` vem primeiro por ser o nome limpo; o aria-label é a
    // reserva para layouts que não o tenham.
    const nomeNoCartao = cartao => {
        for (const filho of cartao.querySelectorAll('[title]')) {
            const titulo = (filho.getAttribute('title') || '').trim();
            if (titulo && extensoes.includes(extensaoDe(titulo))) return titulo;
        }
        const rotulo = (cartao.getAttribute('aria-label') || '').trim();
        const casou = rotulo.match(/^(.+?\\.[A-Za-z0-9]{2,5})(?=$|\\s)/);
        if (casou && extensoes.includes(extensaoDe(casou[1]))) return casou[1];
        return null;
    };

    const vistos = new Set();
    const achados = [];

    for (const cartao of document.querySelectorAll('[role="option"]')) {
        // `closest` e não `hasAttribute`: descarta a linha da lista de
        // mensagens e também qualquer coisa renderizada dentro dela.
        if (cartao.closest('[data-convid]')) continue;
        if (!cartao.querySelector('[aria-haspopup]')) continue;

        const arquivo = nomeNoCartao(cartao);
        if (!arquivo || vistos.has(arquivo)) continue;
        vistos.add(arquivo);

        cartao.setAttribute('data-facilitador-anexo', arquivo);
        achados.push(arquivo);
    }

    return achados;
}
"""


def find_attachments(page: Page, extensions: list[str]) -> list[str]:
    """Nomes dos arquivos anexados visíveis no e-mail aberto.

    Marca cada elemento encontrado com `data-facilitador-anexo` para que o
    download consiga voltar nele depois sem repetir a busca.
    """
    achados = page.evaluate(_JS_FIND_ATTACHMENTS, extensions)
    _log.info("anexos encontrados no e-mail: %s", achados or "(nenhum)")
    return achados


def _locate_attachment(page: Page, filename: str):
    """O cartão do anexo, remarcando a página se a marca tiver sumido.

    O Outlook remonta o painel de leitura por conta própria — uma imagem que
    termina de carregar, a lista que se atualiza ao fundo — e a remontagem
    leva junto os atributos que não são dele, inclusive a marca deixada por
    `find_attachments`. Quando isso acontecia no meio de um e-mail, **todos**
    os anexos seguintes falhavam de uma vez, no mesmo segundo, com "não foi
    marcado na página": o app desistia de um e-mail inteiro por causa de uma
    remontagem entre achar e baixar. Procurar de novo custa uma chamada ao
    navegador e recupera o e-mail todo.
    """
    seletor = f'[data-facilitador-anexo="{filename}"]'

    alvo = page.locator(seletor).first
    if alvo.count() > 0:
        return alvo

    try:
        page.evaluate(_JS_FIND_ATTACHMENTS, sorted(attachments.DOCUMENT_EXTENSIONS))
    except Exception:  # noqa: BLE001 - página navegando; nada a recuperar
        return None

    alvo = page.locator(seletor).first
    if alvo.count() == 0:
        return None

    _log.info("marca de %r tinha sumido; remarquei a página", filename)
    return alvo


def _comparable_name(nome: str) -> str:
    """Nome de arquivo reduzido ao que dá para comparar entre dois lados.

    O navegador reescreve o nome ao salvar — troca acento, colapsa espaço,
    substitui caractere proibido. Comparar cru daria diferença onde é o
    mesmo arquivo.
    """
    sem_acento = unicodedata.normalize("NFKD", nome or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9.]+", "", sem_acento.lower())


def _is_requested_file(chegou: str, pedido: str) -> bool:
    """True se o download que chegou é mesmo o anexo que o app pediu.

    `expect_download` entrega **qualquer** download que a página dispare, e
    não necessariamente o que o clique pretendia. Sem conferir, dois erros
    passavam despercebidos e gravavam conteúdo trocado com o nome certo:

    - o botão **"Baixar tudo"** do painel, que empacota todos os anexos num
      zip só — o arquivo gravado como "Fulano - Proposta.pdf" seria o pacote
      inteiro;
    - o download **atrasado** da tentativa anterior, que chega enquanto o
      app já espera pelo anexo seguinte.

    Aceita truncamento (o Outlook encurta nome longo), mas exige a mesma
    extensão: um `.zip` chegando no lugar de um `.pdf` é o caso 1 acima.
    """
    a, b = _comparable_name(chegou), _comparable_name(pedido)
    if not a or not b:
        return False
    if a.rpartition(".")[2] != b.rpartition(".")[2]:
        return False
    return a == b or a.startswith(b[:20]) or b.startswith(a[:20])


class _WrongFile(Exception):
    """Chegou um download, mas de outro arquivo — não pode ser gravado."""


class _NoTrigger(Exception):
    """O botão/menu de baixar não foi encontrado — não há download a esperar.

    Existe para sair de dentro do `expect_download` por exceção, e não por
    `continue`: sair pela porta normal faria o `expect_download` esperar o
    download inteiro (o timeout todo) por um clique que nunca aconteceu.
    Levantar uma exceção faz o `expect_download` desistir na hora.
    """


def download_attachment(page: Page, filename: str, destino) -> bool:
    """Baixa um anexo já localizado por `find_attachments`.

    O Outlook não expõe um botão de download estável: dependendo do tipo
    de arquivo e do tamanho da janela, ele aparece ao passar o mouse, ou
    fica escondido num menu "mais ações". Tentamos as duas formas, do
    caminho mais curto para o mais longo.

    Cada tentativa espera o download **começar** por um tempo curto
    (`_DOWNLOAD_START_TIMEOUT_MS`): se o acionador certo foi clicado, o
    Outlook dispara o download em segundos. Só depois de começado é que
    esperamos o arquivo terminar, aí sim com folga. Sem essa separação, um
    seletor errado prendia o app pelo timeout inteiro a cada anexo — foi o
    que travava a varredura ao chegar numa proposta.
    """
    alvo = _locate_attachment(page, filename)
    if alvo is None:
        _log.warning("anexo %r não está na página; não dá para baixar", filename)
        return False

    try:
        alvo.scroll_into_view_if_needed(timeout=5_000)
        alvo.hover(timeout=5_000)
    except Exception:  # noqa: BLE001 - o anexo pode não aceitar hover
        pass

    # A ordem importa: no Outlook do usuário o caminho real é a setinha (˅)
    # que abre "Salvar como". O botão de hover fica como reserva, para
    # layouts em que ele exista.
    for tentativa in (_download_via_menu, _download_via_button):
        try:
            with page.expect_download(timeout=_DOWNLOAD_START_TIMEOUT_MS) as download:
                if not tentativa(page, alvo):
                    raise _NoTrigger

            chegou = download.value
            if not _is_requested_file(chegou.suggested_filename, filename):
                _log.warning(
                    "pedi %r e veio %r — descartado para não gravar conteúdo "
                    "trocado", filename, chegou.suggested_filename,
                )
                raise _WrongFile

            # A pasta nasce agora, com o download já começado — e não antes,
            # ao montar o caminho. Criá-la cedo enchia `Propostas` de árvores
            # `Obra/Processo/Fornecedor` vazias toda vez que um download
            # falhava: o usuário abria a pasta da proposta e não havia nada
            # dentro, sem nada indicando que o arquivo nunca chegou.
            destino.parent.mkdir(parents=True, exist_ok=True)
            chegou.save_as(str(destino))
            _log.info("baixou %r via %s", filename, tentativa.__name__)
            return True
        except _WrongFile:
            _close_open_menu(page)
            continue
        except _NoTrigger:
            _log.debug("%s: acionador não encontrado para %r", tentativa.__name__, filename)
            _close_open_menu(page)
            continue
        except Exception as exc:  # noqa: BLE001 - timeout ou clique sem efeito; tenta a próxima forma
            _log.debug(
                "%s falhou para %r: %s", tentativa.__name__, filename,
                str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__,
            )
            _close_open_menu(page)
            continue

    _log.warning("nenhum caminho de download funcionou para %r", filename)
    return False


def _close_open_menu(page: Page) -> None:
    """Fecha com Esc o menu que uma tentativa de download deixou aberto.

    A setinha do anexo abre um menu que cobre a tela. Se o item "Salvar
    como" não foi clicado — porque o menu não trouxe esse item, ou porque o
    download não começou a tempo —, o menu fica aberto e intercepta os
    cliques seguintes: o anexo seguinte falhava por estar atrás dele, e a
    falha se propagava pelo resto do e-mail.
    """
    try:
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001 - sem menu aberto, ou página navegando
        pass


# Rótulos do item de menu que salva o anexo em disco. "Salvar como" é o que
# aparece no Outlook do usuário; os demais cobrem outros idiomas/versões.
# "Salvar no OneDrive" fica de fora de propósito: salva na nuvem, não na
# máquina, e é outro fluxo (nem gera download local para o Playwright pegar).
_SAVE_LABEL = re.compile(r"salvar como|baixar|download|save as", re.I)

# Rótulos que casam com o de salvar mas fazem outra coisa. "Baixar tudo"
# existe de verdade no painel de leitura do usuário (conferido no HTML real)
# e empacota TODOS os anexos num zip — clicar nele gravaria o pacote inteiro
# com o nome de um arquivo só. "Salvar tudo no OneDrive" salva na nuvem e nem
# gera download local.
_NOT_SAVE_LABEL = re.compile(r"\btudo\b|\ball\b|onedrive", re.I)


def _download_via_menu(page: Page, alvo) -> bool:
    """Abre a setinha (˅) do anexo e clica em "Salvar como".

    É o caminho real no Outlook do usuário: o cartão do anexo não tem botão
    de baixar visível, só um menu suspenso com Visualização, Abrir, Salvar
    no OneDrive, Copiar e Salvar como.
    """
    # Só `aria-haspopup` serve de acionador — é o que a setinha é.
    #
    # Havia aqui uma reserva: sem `aria-haspopup`, clicar no último botão do
    # cartão. Ela é a causa do e-mail fixado. Quando o alvo não era um cartão
    # de anexo (ver `_JS_FIND_ATTACHMENTS`), o último botão era "Manter esta
    # mensagem na parte superior de sua pasta", e cada anexo que o app tentava
    # baixar fixava um e-mail. Um clique às cegas em "o último botão que
    # houver" não tem como ser seguro: numa linha de mensagem os botões são
    # fixar, sinalizar e marcar como não lido. Sem setinha, é melhor não
    # baixar do que mexer na caixa do usuário.
    gatilho = alvo.locator('[aria-haspopup]').first
    if gatilho.count() == 0:
        return False
    gatilho.click(timeout=5_000)

    # `:visible` limita ao menu que ACABOU de abrir. Sem isso a busca varria
    # a página inteira e podia pegar o item de um menu anterior que ficou
    # montado no DOM — clicando no "Salvar como" do anexo errado.
    #
    # `has_not_text` afasta "Baixar tudo", que casa com o padrão de salvar
    # (contém "baixar") mas empacota todos os anexos num zip.
    item = (
        page.locator('[role="menuitem"]:visible')
        .filter(has_text=_SAVE_LABEL)
        .filter(has_not_text=_NOT_SAVE_LABEL)
        .first
    )
    try:
        # `click` espera o item aparecer sozinho — o menu monta com um
        # pequeno atraso depois do clique na setinha.
        item.click(timeout=5_000)
    except Exception:  # noqa: BLE001 - o menu não trouxe um item de salvar
        return False
    return True


def _download_via_button(page: Page, alvo) -> bool:
    """Botão de download que aparece sobre o anexo ao passar o mouse.

    Reserva: alguns layouts do Outlook mostram um botão direto.

    Procura **só dentro do cartão do anexo**. Antes procurava também na
    página inteira, o que era pior que não achar nada: o painel de leitura
    tem um "Baixar tudo" ao lado da lista de anexos, e um clique nele
    salvaria o pacote inteiro com o nome do arquivo da vez — todos os anexos
    do e-mail gravados como se fossem a proposta de um fornecedor. Fora do
    cartão não existe botão que baixe este anexo, e sim vários que fazem
    outra coisa.
    """
    botao = alvo.locator(
        '[aria-label*="Baixar" i], [aria-label*="Download" i], '
        '[title*="Baixar" i], [title*="Download" i]'
    ).first
    if botao.count() > 0:
        botao.click(timeout=5_000)
        return True
    return False
