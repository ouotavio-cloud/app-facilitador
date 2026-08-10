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

from app_facilitador import config, inbox_parser, paths

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

# Localiza os anexos pelo nome do arquivo, e não por classe de CSS.
#
# Toda a leitura do Outlook aqui depende de classes geradas pelo build da
# Microsoft, que mudam sem aviso. Para anexos dá para fazer melhor: um
# anexo é um elemento cujo rótulo termina em ".pdf", ".xlsx" e afins. Isso
# sobrevive a mudança de layout, porque descreve o conteúdo e não a
# aparência.
_JS_FIND_ATTACHMENTS = """
extensoes => {
    const vistos = new Set();
    const achados = [];

    for (const el of document.querySelectorAll('[aria-label], [title]')) {
        const rotulo = (el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
        if (!rotulo) continue;

        // O rótulo pode ser "Proposta.pdf" ou "Anexo Proposta.pdf, 240 KB".
        const casou = rotulo.match(/([^\\\\/:*?"<>|\\s][^\\\\/:*?"<>|]*\\.[A-Za-z0-9]{2,5})(?=$|[,;\\s])/);
        if (!casou) continue;

        const arquivo = casou[1].trim();
        const extensao = arquivo.slice(arquivo.lastIndexOf('.')).toLowerCase();
        if (!extensoes.includes(extensao)) continue;

        // Um mesmo anexo aparece em elementos aninhados (o cartão e o
        // botão dentro dele); ficamos com o mais interno, que é onde o
        // clique costuma funcionar.
        if (vistos.has(arquivo)) continue;
        vistos.add(arquivo);

        el.setAttribute('data-facilitador-anexo', arquivo);
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
    return True


def find_attachments(page: Page, extensions: list[str]) -> list[str]:
    """Nomes dos arquivos anexados visíveis no e-mail aberto.

    Marca cada elemento encontrado com `data-facilitador-anexo` para que o
    download consiga voltar nele depois sem repetir a busca.
    """
    return page.evaluate(_JS_FIND_ATTACHMENTS, extensions)


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
    alvo = page.locator(f'[data-facilitador-anexo="{filename}"]').first
    if alvo.count() == 0:
        return False

    try:
        alvo.scroll_into_view_if_needed(timeout=5_000)
        alvo.hover(timeout=5_000)
    except Exception:  # noqa: BLE001 - o anexo pode não aceitar hover
        pass

    for tentativa in (_baixar_pelo_botao, _baixar_pelo_menu):
        try:
            with page.expect_download(timeout=_DOWNLOAD_START_TIMEOUT_MS) as download:
                if not tentativa(page, alvo):
                    raise _SemAcionador
            download.value.save_as(str(destino))
            return True
        except _SemAcionador:
            continue
        except Exception:  # noqa: BLE001 - timeout ou clique sem efeito; tenta a próxima forma
            continue

    return False


def _baixar_pelo_botao(page: Page, alvo) -> bool:
    """Botão de download que aparece sobre o anexo ao passar o mouse."""
    botao = page.locator(
        '[aria-label*="Baixar" i], [aria-label*="Download" i], '
        '[title*="Baixar" i], [title*="Download" i]'
    ).first
    if botao.count() == 0:
        return False
    botao.click(timeout=5_000)
    return True


def _baixar_pelo_menu(page: Page, alvo) -> bool:
    """Item "Baixar" dentro do menu de mais ações do anexo."""
    menu = page.locator(
        '[aria-label*="mais ações" i], [aria-label*="more actions" i], '
        '[aria-label*="Mais opções" i]'
    ).first
    if menu.count() == 0:
        return False
    menu.click(timeout=5_000)

    item = page.get_by_role("menuitem").filter(has_text=re.compile("baixar|download", re.I)).first
    if item.count() == 0:
        return False
    item.click(timeout=5_000)
    return True


def dump_message_debug(page: Page, destino) -> None:
    """Salva o HTML do painel de leitura, para calibrar a busca de anexos.

    A leitura de anexos depende da estrutura da página, que a Microsoft
    muda sem aviso. Quando parar de funcionar, é este arquivo que mostra a
    estrutura nova.
    """
    html = page.evaluate(
        """
        () => {
            const painel = document.querySelector('[role="main"]')
                || document.querySelector('[role="document"]')
                || document.body;
            return painel.outerHTML;
        }
        """
    )
    destino.write_text(html, encoding="utf-8")


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
