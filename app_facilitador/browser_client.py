"""Automação do Outlook Web via Playwright.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.
"""

import re
import time
from collections.abc import Callable, Iterator
from datetime import datetime

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app_facilitador import config, inbox_parser, logs, paths

_log = logs.get_logger("browser")

# Seletores candidatos para os itens da lista de e-mails na caixa de
# entrada do Outlook Web. Não há API estável para isso — é automação de
# interface, então mais de uma opção é tentada, da mais específica para a
# mais genérica, até uma encontrar elementos na tela.
_MESSAGE_ITEM_SELECTORS = [
    '[role="option"][aria-label]',
    'div[role="listitem"]',
    '[data-convid]',
]

# Extrai todos os itens renderizados de uma vez. Uma única chamada ao
# navegador por rodada, em vez de uma por item: a caixa do usuário tem
# milhares de conversas, e o custo de ida e volta por elemento tornaria a
# varredura completa inviável.
#
# As classes CSS (.ESO13, .IjzWp, .ASFJj) foram calibradas contra o HTML
# real da caixa de entrada via scripts/browser_inbox_debug.py. São classes
# geradas pelo build do Fluent UI e podem mudar quando a Microsoft
# atualizar o Outlook Web — se a extração parar de funcionar, recalibrar
# com o script de diagnóstico antes de mexer aqui.
_JS_EXTRACT_ALL_ITEMS = """
selector => {
    return Array.from(document.querySelectorAll(selector)).map(el => {
        const senderSpan = el.querySelector('.ESO13 span[title]');
        const subjectSpan = el.querySelector('.IjzWp span');
        const previewSpan = el.querySelector('.ASFJj');
        const titledSpans = Array.from(el.querySelectorAll('span[title]'));
        const dateSpan = titledSpans.find(s => s !== senderSpan);
        return {
            conv_id: el.getAttribute('data-convid'),
            aria_label: el.getAttribute('aria-label'),
            sender_name: senderSpan ? senderSpan.textContent.trim() : null,
            sender_email: senderSpan ? senderSpan.getAttribute('title') : null,
            subject: subjectSpan ? subjectSpan.textContent.trim() : null,
            date_title: dateSpan ? dateSpan.getAttribute('title') : null,
            preview: previewSpan ? previewSpan.textContent.trim() : null,
        };
    });
}
"""

# Rola a lista de e-mails de fato.
#
# Não dá para usar `scroll_into_view_if_needed()` no último item: ele já
# está dentro da viewport quando a lista é curta, então a chamada não faz
# nada e a varredura empaca nos primeiros e-mails. Aqui subimos dos itens
# até o ancestral que realmente rola e mexemos no `scrollTop` dele.
_JS_SCROLL_LIST = """
([selector, fraction]) => {
    const item = document.querySelector(selector);
    if (!item) return { scrolled: false, at_end: true };

    let el = item.parentElement;
    while (el && el !== document.body) {
        const overflowY = getComputedStyle(el).overflowY;
        const scrollable = overflowY === 'auto' || overflowY === 'scroll';
        if (scrollable && el.scrollHeight > el.clientHeight + 10) {
            const before = el.scrollTop;
            el.scrollTop = before + el.clientHeight * fraction;
            return {
                scrolled: el.scrollTop > before,
                at_end: el.scrollTop + el.clientHeight >= el.scrollHeight - 2,
            };
        }
        el = el.parentElement;
    }
    return { scrolled: false, at_end: true };
}
"""

# Quantas rodadas seguidas de scroll sem nenhuma conversa nova antes de
# considerar que a lista acabou. Mais de uma porque o carregamento é
# assíncrono: uma rodada vazia pode significar apenas que o Outlook ainda
# não devolveu o próximo bloco.
_STAGNANT_ROUNDS_BEFORE_STOP = 3

# Fração da altura visível avançada a cada scroll. Menos que uma tela
# inteira de propósito: a lista é virtualizada, e rolar a tela cheia
# descartaria itens do DOM antes de terem sido extraídos. A sobreposição
# garante que nenhuma conversa passe despercebida.
_SCROLL_FRACTION = 0.8

# Pausa após cada scroll, dando tempo do Outlook Web buscar e renderizar
# o próximo bloco da lista virtualizada.
_SCROLL_SETTLE_MS = 1_000

# Uma janela maior renderiza mais e-mails por vez, reduzindo o número de
# rodadas necessárias para percorrer uma caixa com milhares de conversas.
_VIEWPORT = {"width": 1600, "height": 1200}

# Usado para detectar que a lista trocou ao mudar de pasta.
_JS_FIRST_CONV_ID = """
selector => {
    const el = document.querySelector(selector);
    return el ? el.getAttribute('data-convid') : null;
}
"""

# Pausa após trocar de pasta, dando tempo da nova lista assentar.
_FOLDER_SETTLE_MS = 1_500

# Quanto tempo o app espera o usuário concluir o login manual. Generoso
# de propósito: pode haver autenticação em dois fatores, celular longe da
# mesa, senha esquecida.
LOGIN_TIMEOUT_MS = 10 * 60 * 1_000

# De quanto em quanto tempo o app olha se o login já terminou. Um laço de
# espera curta, em vez de um `wait_for_selector` longo, para que o botão
# "Já entrei" da tela consiga interromper a espera e para que a janela
# fechada no meio do caminho seja percebida na hora.
LOGIN_POLL_MS = 1_000

# Sinais de que o Outlook abriu e o login terminou.
#
# A árvore de pastas entra além da lista de e-mails porque é o marcador
# mais confiável dos dois: ela existe mesmo numa caixa vazia e mesmo se o
# Outlook abrir num aviso de boas-vindas, situações em que esperar por uma
# linha de e-mail deixaria a conexão travada para sempre. A tela de login
# da Microsoft não tem nenhum dos dois.
_LOGIN_READY_SELECTORS = [*_MESSAGE_ITEM_SELECTORS, '[role="treeitem"]']


def open_browser_context(playwright, headless: bool):
    """Abre o Chromium com o perfil persistente do app.

    **Chromium, e não o Edge instalado na máquina.** Chegamos a usar o Edge
    para evitar 150 MB no download, e foi um erro: no Windows corporativo
    ele não preservava a conta entre execuções — o usuário precisava logar
    de novo o tempo todo — enquanto o Chromium mantinha. O Chromium passa a
    ser distribuído dentro do app; o tamanho é o preço de um login que dura.

    **Perfil persistente, e não `storage_state`.** Salvar cookies e
    localStorage num arquivo perde o que o login da Microsoft guarda em
    IndexedDB, e a sessão morria cedo. Um perfil de navegador de verdade
    guarda tudo, e a conta dura o mesmo que duraria no navegador do dia a
    dia.

    Devolve um contexto (não um navegador): no modo persistente o
    Playwright não expõe os dois separadamente.
    """
    paths.configure_playwright_browsers()
    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        return playwright.chromium.launch_persistent_context(
            str(config.BROWSER_PROFILE_DIR),
            headless=headless,
            viewport=_VIEWPORT,
        )
    except Exception as exc:  # noqa: BLE001 - sem navegador não há o que fazer
        raise RuntimeError(
            "Não foi possível abrir o navegador do app.\n"
            f"Detalhe: {str(exc).splitlines()[0]}\n"
            "Se você está rodando pelo código-fonte, falta executar: "
            "playwright install chromium"
        ) from exc


def first_page(context):
    """A aba do contexto persistente, criada se ainda não houver nenhuma.

    Um perfil persistente já abre com uma aba; criar outra deixaria uma
    janela em branco sobrando na tela do usuário.
    """
    return context.pages[0] if context.pages else context.new_page()


def _login_page_description(page: Page) -> str:
    """Onde o navegador está agora, em uma linha, para mostrar na tela.

    Sem isto, um login que não é detectado vira uma espera muda: não dá
    para saber se a pessoa ainda está na tela de senha, se caiu numa
    verificação em dois fatores ou se a caixa de entrada abriu e o app é
    que não a reconheceu.
    """
    try:
        url = page.url
    except Exception:  # noqa: BLE001 - página fechada ou navegando
        return "página desconhecida"

    if "login.microsoftonline.com" in url or "login.live.com" in url:
        return "tela de login da Microsoft"
    if "outlook.office.com" in url or "outlook.office365.com" in url:
        return "Outlook aberto"
    return url.split("?")[0][:80]


# Abaixo disso, a janela sumiu rápido demais para o usuário ter fechado.
_RODADAS_CEDO_DEMAIS = 5


def _mensagem_de_janela_fechada(rodada: int) -> str:
    """Explica o fechamento conforme quando ele aconteceu.

    Sumir em segundos não é a mesma coisa que desistir no meio do login, e
    a causa provável é outra: uma cópia do app ainda aberta segurando o
    mesmo perfil de navegador.
    """
    if rodada < _RODADAS_CEDO_DEMAIS:
        return (
            "A janela do navegador fechou sozinha logo depois de abrir, antes "
            "de dar tempo de logar. Verifique se não há outra cópia do App "
            "Facilitador aberta — duas ao mesmo tempo disputam o mesmo perfil "
            "de navegador."
        )
    return (
        "A janela do navegador foi fechada antes do login terminar. "
        "Clique em conectar de novo."
    )


def login_and_save_session(
    on_status: Callable[[str], None] | None = None,
    should_finish: Callable[[], bool] | None = None,
) -> None:
    """Abre um navegador visível para o usuário logar manualmente uma vez.

    Não pede confirmação no teclado: o app compilado não tem terminal onde
    apertar Enter. O fim do login é detectado sozinho, quando a lista de
    e-mails aparece na tela — que é exatamente o sinal de que a sessão
    serve para o resto do app.

    Mas a detecção automática não é confiável o bastante para ser o único
    caminho: o Outlook pode abrir num aviso de boas-vindas, numa caixa
    vazia, ou com uma estrutura de página que os seletores não reconhecem,
    e aí a espera nunca terminaria. Por isso `should_finish` — ligado ao
    botão "Já entrei" do painel — permite ao usuário encerrar a espera na
    mão, e o laço curto (em vez de uma espera longa e bloqueante) é o que
    torna essa interrupção possível.
    """

    def anunciar(mensagem: str) -> None:
        if on_status is not None:
            on_status(mensagem)
        else:
            print(mensagem)

    with sync_playwright() as playwright:
        context = open_browser_context(playwright, headless=False)
        page = first_page(context)
        page.goto(config.OWA_URL)

        # A janela nova costuma abrir atrás do painel, e o usuário fica
        # olhando para "aguardando login" sem ver onde logar.
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001 - detalhe cosmético, não vale abortar
            pass

        seletor = ", ".join(_LOGIN_READY_SELECTORS)
        rodadas = LOGIN_TIMEOUT_MS // LOGIN_POLL_MS
        concluido = False

        for rodada in range(rodadas):
            if should_finish is not None and should_finish():
                concluido = True
                break

            # A janela fechada é detectada perguntando, e não deduzida de
            # uma exceção qualquer. O login da Microsoft é uma sequência
            # de redirecionamentos, e consultar a página no meio de uma
            # navegação levanta erro ("Execution context was destroyed")
            # sem que nada de errado tenha acontecido — tratar isso como
            # janela fechada abortava o login logo no primeiro redirect.
            if page.is_closed():
                raise RuntimeError(_mensagem_de_janela_fechada(rodada))

            try:
                if page.query_selector(seletor) is not None:
                    concluido = True
                    break
                onde = _login_page_description(page)
            except Exception:  # noqa: BLE001 - navegação em curso; tenta de novo
                onde = "carregando…"

            anunciar(
                f"Aguardando o login na janela do navegador — ela pode estar "
                f"atrás desta. Agora em: {onde}. "
                "Se sua caixa de entrada já apareceu lá, clique em 'Já entrei'."
            )

            # `time.sleep` em vez de `page.wait_for_timeout`: a espera não
            # precisa tocar no navegador, e assim não há como ela falhar
            # por causa de uma navegação em andamento.
            time.sleep(LOGIN_POLL_MS / 1000)

        if not concluido:
            context.close()
            raise RuntimeError(
                "O login não foi concluído a tempo. Clique em conectar de novo."
            )

        # O acesso em si já está no perfil do navegador — fechar o contexto
        # é o que garante que ele seja gravado em disco. Este arquivo só
        # registra que houve login, porque a pasta do perfil existe desde a
        # primeira vez que o navegador abriu, mesmo sem ninguém ter logado.
        context.close()
        config.LOGIN_MARKER_PATH.write_text(
            datetime.now().isoformat(timespec="seconds"), encoding="utf-8"
        )
        anunciar("Acesso ao Outlook salvo. Já pode rodar a varredura.")


def _require_saved_session() -> None:
    if not config.LOGIN_MARKER_PATH.exists():
        raise RuntimeError(
            "O app ainda não tem acesso ao seu Outlook. "
            "Clique em 'Conectar ao Outlook' no painel."
        )


def _find_message_items(page: Page):
    for selector in _MESSAGE_ITEM_SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            return selector, locator
    return None, None


def _raw_folder_names(page: Page) -> list[str]:
    return page.evaluate(
        """
        () => Array.from(document.querySelectorAll('[role="treeitem"]'))
            .map(el => (el.getAttribute('title') || el.textContent || '').trim())
            .filter(name => name.length > 0)
        """
    )


def list_folders(page: Page) -> list[str]:
    """Nomes das pastas de e-mail visíveis no painel de navegação.

    Serve para o usuário descobrir o nome a passar em `open_folder` —
    pastas criadas por ele têm nomes arbitrários ("caixa real") que o
    código não tem como adivinhar.
    """
    names = [inbox_parser.clean_folder_name(raw) for raw in _raw_folder_names(page)]
    # A árvore repete nomes quando uma pasta aparece também em Favoritos;
    # dict.fromkeys remove as repetições preservando a ordem da tela.
    return list(dict.fromkeys(name for name in names if name))


def open_folder(page: Page, folder_name: str) -> None:
    """Abre uma pasta pelo nome e espera a lista de e-mails trocar.

    Levanta `RuntimeError` se a pasta não existir, em vez de varrer
    silenciosamente a pasta errada.
    """
    # Não dá para casar pelo nome exato do elemento: o Outlook anexa a
    # contagem de itens ao rótulo da pasta ("caixa real - 4.410 itens
    # (2 não lidos)"), que muda a cada e-mail que chega. Comparamos o
    # nome limpo de cada item da árvore.
    wanted = inbox_parser.normalize_folder_name(folder_name)
    tree_items = page.get_by_role("treeitem")

    item = None
    for index in range(tree_items.count()):
        candidate = tree_items.nth(index)
        raw = candidate.get_attribute("title") or candidate.inner_text()
        if inbox_parser.normalize_folder_name(inbox_parser.clean_folder_name(raw)) == wanted:
            item = candidate
            break

    if item is None:
        available = ", ".join(list_folders(page)) or "(nenhuma encontrada)"
        raise RuntimeError(
            f"Pasta {folder_name!r} não encontrada. Pastas disponíveis: {available}"
        )

    selector, _ = _find_message_items(page)
    before = page.evaluate(_JS_FIRST_CONV_ID, selector) if selector else None

    item.click()

    # A troca de pasta não recarrega a página, então esperar por um
    # seletor não basta: os itens da pasta anterior ainda estão lá. O
    # sinal de que a nova lista chegou é o primeiro item ter mudado.
    if selector is not None:
        try:
            page.wait_for_function(
                """
                ([selector, before]) => {
                    const el = document.querySelector(selector);
                    const current = el ? el.getAttribute('data-convid') : null;
                    return current !== before;
                }
                """,
                arg=[selector, before],
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            # Uma pasta vazia, ou uma cujo primeiro e-mail é o mesmo da
            # anterior, não muda o primeiro item. Seguir em frente é
            # melhor que abortar: a extração seguinte mostra o que há.
            pass

    page.wait_for_timeout(_FOLDER_SETTLE_MS)


def list_visible_messages(page: Page) -> list[dict]:
    """Extrai os e-mails atualmente renderizados na tela (sem rolar a lista)."""
    selector, _ = _find_message_items(page)
    if selector is None:
        return []
    raw_items = page.evaluate(_JS_EXTRACT_ALL_ITEMS, selector)
    return [inbox_parser.parse_message_row(raw) for raw in raw_items]


def scan_inbox(
    page: Page,
    max_messages: int | None = None,
    on_progress: Callable[[int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> Iterator[dict]:
    """Percorre a caixa de entrada inteira, rolando a lista, e produz cada e-mail.

    A lista do Outlook Web é virtualizada: só os itens visíveis existem no
    DOM, e os demais são carregados conforme a rolagem. Por isso a
    varredura alterna extrair o que está na tela e rolar para o fim, até
    parar de aparecer conversa nova (ver PLANEJAMENTO.md, seção 1.3 — a
    varredura precisa cobrir o histórico, não só a primeira tela).

    A deduplicação é por `conv_id` (o `data-convid` do Outlook), porque os
    itens já vistos continuam reaparecendo na extração enquanto estiverem
    renderizados.

    `should_stop`, quando devolve True, encerra a rolagem entre um bloco e
    o próximo — é o que dá efeito ao botão "Parar" da tela.
    """
    selector, _ = _find_message_items(page)
    if selector is None:
        return

    seen: set[str] = set()
    stagnant_rounds = 0

    while stagnant_rounds < _STAGNANT_ROUNDS_BEFORE_STOP:
        if should_stop is not None and should_stop():
            return
        raw_items = page.evaluate(_JS_EXTRACT_ALL_ITEMS, selector)
        found_new = False

        for raw in raw_items:
            # O aria-label serve de identidade reserva: sem uma chave para
            # todo item, um item sem `conv_id` seria contado como novo em
            # toda rodada e a varredura nunca terminaria.
            key = raw.get("conv_id") or raw.get("aria_label")
            if key is None or key in seen:
                continue
            seen.add(key)

            found_new = True
            yield inbox_parser.parse_message_row(raw)

            if max_messages is not None and len(seen) >= max_messages:
                return

        stagnant_rounds = 0 if found_new else stagnant_rounds + 1

        if on_progress is not None:
            on_progress(len(seen))

        scroll = page.evaluate(_JS_SCROLL_LIST, [selector, _SCROLL_FRACTION])
        # Chegar ao fim da barra de rolagem não significa fim da lista: o
        # Outlook carrega o próximo bloco quando o fim é alcançado. Só
        # paramos quando, além disso, as rodadas seguintes não trouxerem
        # nenhuma conversa nova.
        if not scroll["scrolled"] and scroll["at_end"]:
            stagnant_rounds += 1

        page.wait_for_timeout(_SCROLL_SETTLE_MS)


# Quanto esperar o e-mail abrir no painel de leitura.
_MESSAGE_OPEN_TIMEOUT_MS = 20_000

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


def open_message(page: Page, conv_id: str) -> bool:
    """Abre um e-mail no painel de leitura. False se a linha sumiu da tela.

    Só funciona enquanto a conversa está renderizada — a lista é
    virtualizada, então isto precisa acontecer logo depois de ela ter sido
    lida, não numa segunda passada.

    Abrir marca o e-mail como lido no Outlook. É um efeito colateral real
    na caixa do usuário, e por isso só e-mails já identificados como
    proposta são abertos, nunca a caixa inteira.
    """
    linha = page.locator(f'[data-convid="{conv_id}"]').first
    if linha.count() == 0:
        return False

    try:
        linha.click(timeout=_MESSAGE_OPEN_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - linha descartada pela virtualização
        return False

    # O painel de leitura monta em etapas; sem esta pausa a busca por
    # anexos acontece antes de eles existirem.
    page.wait_for_timeout(2_000)
    _log.info("abriu o e-mail %s", conv_id)
    return True


def find_attachments(page: Page, extensions: list[str]) -> list[str]:
    """Nomes dos arquivos anexados visíveis no e-mail aberto.

    Marca cada elemento encontrado com `data-facilitador-anexo` para que o
    download consiga voltar nele depois sem repetir a busca.
    """
    achados = page.evaluate(_JS_FIND_ATTACHMENTS, extensions)
    _log.info("anexos encontrados no e-mail: %s", achados or "(nenhum)")
    return achados


def read_message_body(page: Page) -> str:
    """Texto do corpo do e-mail aberto no painel de leitura.

    Serve para procurar o código do processo no corpo, não só no assunto —
    o fornecedor muitas vezes escreve o código no texto ("segue proposta da
    SUP.2026-197") sem repeti-lo no assunto.

    Best-effort: se o painel não for reconhecido, devolve "". `innerText`
    (e não `textContent`) porque respeita quebras e ignora o que está
    escondido, ficando perto do que a pessoa lê na tela.
    """
    try:
        return page.evaluate(
            """
            () => {
                const painel = document.querySelector('[role="main"]')
                    || document.querySelector('[role="document"]')
                    || document.body;
                return (painel.innerText || '').trim();
            }
            """
        )
    except Exception:  # noqa: BLE001 - painel navegando/ausente: melhor vazio que quebrar
        return ""


def _localizar_anexo(page: Page, filename: str):
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
        page.evaluate(_JS_FIND_ATTACHMENTS, sorted(config_extensoes()))
    except Exception:  # noqa: BLE001 - página navegando; nada a recuperar
        return None

    alvo = page.locator(seletor).first
    if alvo.count() == 0:
        return None

    _log.info("marca de %r tinha sumido; remarquei a página", filename)
    return alvo


class _SemAcionador(Exception):
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
    alvo = _localizar_anexo(page, filename)
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
    for tentativa in (_baixar_pelo_menu, _baixar_pelo_botao):
        try:
            with page.expect_download(timeout=_DOWNLOAD_START_TIMEOUT_MS) as download:
                if not tentativa(page, alvo):
                    raise _SemAcionador
            # A pasta nasce agora, com o download já começado — e não antes,
            # ao montar o caminho. Criá-la cedo enchia `Propostas` de árvores
            # `Obra/Processo/Fornecedor` vazias toda vez que um download
            # falhava: o usuário abria a pasta da proposta e não havia nada
            # dentro, sem nada indicando que o arquivo nunca chegou.
            destino.parent.mkdir(parents=True, exist_ok=True)
            download.value.save_as(str(destino))
            _log.info("baixou %r via %s", filename, tentativa.__name__)
            return True
        except _SemAcionador:
            _log.debug("%s: acionador não encontrado para %r", tentativa.__name__, filename)
            _fechar_menu_aberto(page)
            continue
        except Exception as exc:  # noqa: BLE001 - timeout ou clique sem efeito; tenta a próxima forma
            _log.debug(
                "%s falhou para %r: %s", tentativa.__name__, filename,
                str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__,
            )
            _fechar_menu_aberto(page)
            continue

    _log.warning("nenhum caminho de download funcionou para %r", filename)
    return False


def _fechar_menu_aberto(page: Page) -> None:
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
_ROTULO_SALVAR = re.compile(r"salvar como|baixar|download|save as", re.I)


def _baixar_pelo_menu(page: Page, alvo) -> bool:
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

    item = page.get_by_role("menuitem").filter(has_text=_ROTULO_SALVAR).first
    try:
        # `click` espera o item aparecer sozinho — o menu monta com um
        # pequeno atraso depois do clique na setinha.
        item.click(timeout=5_000)
    except Exception:  # noqa: BLE001 - o menu não trouxe um item de salvar
        return False
    return True


def _baixar_pelo_botao(page: Page, alvo) -> bool:
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


# O controle que desfixa uma mensagem é identificado pelo RÓTULO
# (aria-label/title), nunca pela posição.
#
# Só vimos, no diagnóstico real, o rótulo de quando a mensagem AINDA NÃO
# está fixada: "Manter esta mensagem na parte superior de sua pasta" (é
# esse botão que a v12 clicava por engano — ver CONTINUIDADE.md). Não há
# uma captura real do mesmo botão já fixado, então `_find_unpin_control`
# procura as variações mais prováveis do rótulo nesse estado. Se nenhuma
# bater, devolve None e a mensagem entra na lista para o usuário desafixar
# à mão — o app nunca adivinha clicando em outra coisa.


def _find_unpin_control(page: Page, conv_id: str):
    """O controle que desfixa a mensagem, só quando dá para reconhecê-lo com
    segurança pelo rótulo — nunca pela posição.

    A causa do e-mail fixado foi um clique "no botão que houver" quando o
    acionador esperado não estava lá. Desafixar com o mesmo tipo de clique
    às cegas seria repetir o erro, só que na direção oposta. Sem um rótulo
    reconhecível, é melhor devolver None e deixar o e-mail para o usuário
    resolver à mão.
    """
    linha = page.locator(f'[data-convid="{conv_id}"]').first
    if linha.count() == 0:
        return None

    candidato = linha.locator(
        '[aria-label*="não manter" i], [title*="não manter" i], '
        '[aria-label*="desafixar" i], [title*="desafixar" i], '
        '[aria-label*="deixar de fixar" i], [title*="deixar de fixar" i], '
        '[aria-label*="unpin" i], [title*="unpin" i]'
    ).first
    if candidato.count() > 0:
        return candidato

    # Reserva: o Outlook pode manter o MESMO rótulo de "Manter esta
    # mensagem..." nos dois estados e sinalizar só por `aria-pressed`. Só
    # serve quando esse sinal está presente E o rótulo ainda é o de
    # fixar/manter — nunca "qualquer botão pressionado".
    candidato = linha.locator(
        '[aria-pressed="true"][aria-label*="parte superior" i], '
        '[aria-pressed="true"][title*="parte superior" i]'
    ).first
    if candidato.count() > 0:
        return candidato

    return None


def unpin_message(page: Page, conv_id: str) -> bool:
    """Desfixa um e-mail já identificado como fixado (`message["is_pinned"]`).

    Existe para desfazer o estrago de um bug já corrigido: versões
    anteriores do app, tentando baixar um anexo, clicavam sem querer em
    "Manter esta mensagem na parte superior de sua pasta" e fixavam o
    e-mail (ver CONTINUIDADE.md). Best-effort por natureza — quando o
    controle não é reconhecido com segurança, devolve False sem clicar em
    nada, e quem chama registra o e-mail para resolução manual.
    """
    alvo = _find_unpin_control(page, conv_id)
    if alvo is None:
        _log.warning("não achei o controle de desafixar para %s; pulei", conv_id)
        return False

    try:
        alvo.click(timeout=5_000)
        _log.info("desafixou o e-mail %s", conv_id)
        return True
    except Exception as exc:  # noqa: BLE001 - clique sem efeito; melhor reportar que travar
        _log.debug("desafixar falhou para %s: %s", conv_id, exc)
        return False


# Extrai a estrutura em volta de cada anexo: o cartão do anexo e os
# controles (botões, menus, links) perto dele. É o que faltava no
# diagnóstico anterior, que pegava só [role=main] e não continha os anexos —
# eles ficam fora dessa região no novo Outlook.
_JS_DUMP_ANEXOS = """
extensoes => {
    const relatorio = [];
    for (const el of document.querySelectorAll('[aria-label], [title]')) {
        const rotulo = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
        const casou = rotulo.match(/([^\\\\/:*?"<>|\\s][^\\\\/:*?"<>|]*\\.[A-Za-z0-9]{2,5})(?=$|[,;\\s])/);
        if (!casou) continue;
        const ext = casou[1].slice(casou[1].lastIndexOf('.')).toLowerCase();
        if (!extensoes.includes(ext)) continue;

        // Sobe alguns níveis montando o cartão do anexo.
        let cartao = el;
        for (let i = 0; i < 5 && cartao.parentElement; i++) {
            const papel = cartao.parentElement.getAttribute('role') || '';
            if (['toolbar','main','region','document'].includes(papel)) break;
            cartao = cartao.parentElement;
        }
        const controles = Array.from(
            cartao.querySelectorAll('[aria-haspopup], button, [role="button"], [role="menuitem"], a[href]')
        ).map(c => ({
            tag: c.tagName.toLowerCase(),
            role: c.getAttribute('role'),
            haspopup: c.getAttribute('aria-haspopup'),
            label: c.getAttribute('aria-label') || c.getAttribute('title') || (c.textContent||'').trim().slice(0,40),
        }));

        relatorio.push({
            arquivo: casou[1],
            rotulo_do_elemento: rotulo.slice(0, 120),
            tag_do_elemento: el.tagName.toLowerCase(),
            controles_no_cartao: controles,
            html_do_cartao: cartao.outerHTML.slice(0, 4000),
        });
    }
    return relatorio;
}
"""


# Mede se o painel de leitura está mostrando UMA mensagem ou uma CONVERSA
# inteira, e procura o controle que expande as mensagens recolhidas.
#
# É o buraco que sobrou: a lista do Outlook agrupa por conversa
# (`data-convid`), e abrir a linha mostra só a mensagem mais recente da
# thread. A proposta que o fornecedor mandou lá atrás fica recolhida, e os
# anexos dela nem chegam ao DOM — no banco real do usuário havia duas linhas
# para a SUP.2026-185, embora quatro fornecedores tenham respondido.
#
# Não dá para calibrar esse clique sem ver a estrutura real (foi tentar
# adivinhar acionador que fez o app fixar e-mail). Este relatório é o que
# permite acertar da próxima vez, sem outra compilação às cegas.
_JS_DUMP_CONVERSA = """
() => {
    const painel = document.querySelector('[role="main"]') || document.body;

    // Cada corpo de mensagem renderizado. Mais de um = a thread está
    // expandida; exatamente um = só a última mensagem está aberta.
    const corpos = painel.querySelectorAll('[role="document"]');

    // Candidatos a cabeçalho de mensagem recolhida: qualquer coisa
    // clicável/expansível dentro do painel, com o rótulo e o estado.
    const candidatos = Array.from(
        painel.querySelectorAll('[aria-expanded], [role="button"], [role="heading"], button')
    ).slice(0, 60).map(el => ({
        tag: el.tagName.toLowerCase(),
        role: el.getAttribute('role'),
        expandido: el.getAttribute('aria-expanded'),
        rotulo: (el.getAttribute('aria-label') || el.getAttribute('title')
                 || (el.textContent || '').trim()).slice(0, 90),
    })).filter(c => c.rotulo);

    return {
        corpos_de_mensagem_no_painel: corpos.length,
        conversa_agrupada_provavel: corpos.length <= 1,
        candidatos_a_expandir: candidatos,
        html_do_topo_do_painel: painel.outerHTML.slice(0, 6000),
    };
}
"""


def dump_message_debug(page: Page, destino) -> None:
    """Salva a estrutura real dos anexos, para calibrar o download.

    A leitura de anexos depende da estrutura da página, que a Microsoft muda
    sem aviso. O diagnóstico antigo salvava só `[role=main]`, e os anexos do
    novo Outlook ficam FORA dessa região — por isso o arquivo saía sem eles.
    Agora salvamos: (1) um relatório focado em cada anexo, com os controles
    (botões/menus) ao redor, que é o que preciso para acertar o clique;
    (2) um relatório da CONVERSA, que diz se o painel está mostrando a thread
    inteira ou só a última mensagem — é o que falta para alcançar a proposta
    que o fornecedor mandou no meio do assunto; e (3) o `body` inteiro como
    reserva, para nada escapar.
    """
    import json

    try:
        anexos = page.evaluate(_JS_DUMP_ANEXOS, sorted(config_extensoes()))
    except Exception as exc:  # noqa: BLE001 - diagnóstico não pode quebrar a varredura
        anexos = [{"erro": str(exc)}]

    try:
        conversa = page.evaluate(_JS_DUMP_CONVERSA)
    except Exception as exc:  # noqa: BLE001 - idem
        conversa = {"erro": str(exc)}

    try:
        corpo = page.evaluate("() => document.body.outerHTML")
    except Exception:  # noqa: BLE001
        corpo = ""

    conteudo = (
        "=== RELATÓRIO DOS ANEXOS (controles ao redor de cada arquivo) ===\n"
        + json.dumps(anexos, ensure_ascii=False, indent=2)
        + "\n\n=== RELATÓRIO DA CONVERSA (thread inteira ou só a última?) ===\n"
        + json.dumps(conversa, ensure_ascii=False, indent=2)
        + "\n\n=== BODY COMPLETO (reserva) ===\n"
        + corpo
    )
    destino.write_text(conteudo, encoding="utf-8")


def config_extensoes() -> set[str]:
    """Extensões de documento, para o diagnóstico usar a mesma lista."""
    from app_facilitador import attachments

    return attachments.DOCUMENT_EXTENSIONS


class _BrowserSession:
    """Abre o navegador com o perfil já logado e o fecha ao final.

    Centraliza o arranjo de Playwright + perfil persistente, para que os
    scripts, o scanner e o app não o repitam.
    """

    def __init__(self, url: str, ready_selector: str, headless: bool):
        self._url = url
        self._ready_selector = ready_selector
        self._headless = headless

    def __enter__(self) -> Page:
        self._playwright = sync_playwright().start()
        self._context = open_browser_context(self._playwright, self._headless)
        page = first_page(self._context)
        page.goto(self._url)
        # Esperamos por um elemento da tela, e não por
        # `wait_for_load_state("networkidle")`: o Outlook Web sincroniza em
        # segundo plano o tempo todo, então a rede nunca fica ociosa e essa
        # espera expira por timeout.
        page.wait_for_selector(self._ready_selector, timeout=60_000)
        return page

    def __exit__(self, *exc_info) -> None:
        # Fechar o contexto grava o perfil em disco: é o que mantém a conta
        # válida para a próxima execução.
        self._context.close()
        self._playwright.stop()


def open_inbox_session(headless: bool = False) -> _BrowserSession:
    """Context manager que entrega a caixa de entrada pronta para leitura."""
    _require_saved_session()
    return _BrowserSession(
        config.OWA_URL, ", ".join(_MESSAGE_ITEM_SELECTORS), headless
    )


def open_calendar_session(headless: bool = False) -> _BrowserSession:
    """Context manager que entrega o calendário do dia pronto para leitura."""
    _require_saved_session()
    # A grade do calendário é montada por JS; esperar por ela evita ler a
    # página antes dos compromissos existirem.
    return _BrowserSession(
        config.OWA_CALENDAR_URL, '[role="grid"], [role="main"]', headless
    )


def print_visible_messages() -> None:
    """Abre a caixa de entrada e imprime os e-mails visíveis já estruturados."""
    with open_inbox_session() as page:
        messages = list_visible_messages(page)
        print(f"{len(messages)} e-mails visíveis:\n")
        for i, message in enumerate(messages):
            flags = ""
            if message["is_pinned"]:
                flags += " [Fixado]"
            if message["has_attachments"]:
                flags += " [Tem anexos]"
            print(f"[{i}]{flags}")
            print(f"  De: {message['sender_name']} <{message['sender_email']}>")
            print(f"  Assunto: {message['subject']}")
            print(f"  Recebido: {message['received_at_raw']}")
            preview = message["preview"]
            if preview:
                print(f"  Preview: {preview[:120]}")
            print()


def dump_inbox_debug(limit: int = 10) -> None:
    """Abre a caixa de entrada e imprime a estrutura bruta dos primeiros itens.

    Ferramenta de calibração: quando a Microsoft mudar o layout do Outlook
    Web e a extração parar de funcionar, é por aqui que se descobre a nova
    estrutura antes de ajustar os seletores.
    """
    with open_inbox_session() as page:
        screenshot_path = config.BASE_DIR / "debug_inbox.png"
        page.screenshot(path=str(screenshot_path))
        print(f"Screenshot salvo em {screenshot_path}")

        selector, items = _find_message_items(page)
        if items is None:
            print(
                "Nenhum seletor conhecido encontrou itens na tela. "
                "Envie o screenshot para calibrar os seletores."
            )
            return

        count = min(items.count(), limit)
        print(f"Seletor usado: {selector!r} — {items.count()} itens encontrados, mostrando {count}:\n")
        for i in range(count):
            text = items.nth(i).inner_text().replace("\n", " | ")
            print(f"  [{i}] {text}")

        print("\n--- aria-label de cada item (para calibrar o parser) ---\n")
        for i in range(count):
            print(f"  [{i}] {items.nth(i).get_attribute('aria-label')!r}")

        html_dump_path = config.BASE_DIR / "debug_inbox_items.html"
        chunks = [
            f"<!-- ===== item [{i}] ===== -->\n{items.nth(i).evaluate('el => el.outerHTML')}"
            for i in range(count)
        ]
        html_dump_path.write_text("\n\n".join(chunks), encoding="utf-8")
        print(f"\nHTML de todos os {count} itens salvo em {html_dump_path}")
