"""Automação do Outlook Web via Playwright.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.
"""

from collections.abc import Callable, Iterator

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app_facilitador import config, inbox_parser

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

# Navegadores já instalados que serão usados, na ordem de preferência.
#
# O app é distribuído como um executável que não deve exigir instalação
# de nada: usar o Edge — presente em qualquer Windows — evita baixar um
# Chromium de ~150 MB e evita o passo `playwright install`. O Chromium
# empacotado continua servindo de último recurso para quem roda pelo
# código-fonte.
_BROWSER_CHANNELS = ["msedge", "chrome"]

# Quanto tempo o app espera o usuário concluir o login manual. Generoso
# de propósito: pode haver autenticação em dois fatores, celular longe da
# mesa, senha esquecida.
LOGIN_TIMEOUT_MS = 10 * 60 * 1_000


def launch_browser(playwright, headless: bool):
    """Abre o navegador, preferindo um já instalado na máquina.

    Tenta o Edge, depois o Chrome, e só então o Chromium que o Playwright
    baixa à parte. Se nada funcionar, o erro precisa dizer o que tentou —
    "falha ao abrir o navegador" sozinho não ajudaria ninguém a resolver.
    """
    tentativas = []

    for channel in [*_BROWSER_CHANNELS, None]:
        try:
            if channel is None:
                return playwright.chromium.launch(headless=headless)
            return playwright.chromium.launch(headless=headless, channel=channel)
        except Exception as exc:  # noqa: BLE001 - qualquer falha é "não tem esse aqui"
            nome = channel or "Chromium empacotado"
            tentativas.append(f"{nome}: {str(exc).splitlines()[0]}")

    raise RuntimeError(
        "Não foi possível abrir um navegador. Tentativas:\n  "
        + "\n  ".join(tentativas)
    )


def login_and_save_session(on_status: Callable[[str], None] | None = None) -> None:
    """Abre um navegador visível para o usuário logar manualmente uma vez.

    Não pede confirmação no teclado: o app compilado não tem terminal onde
    apertar Enter. O fim do login é detectado sozinho, quando a lista de
    e-mails aparece na tela — que é exatamente o sinal de que a sessão
    serve para o resto do app.
    """

    def anunciar(mensagem: str) -> None:
        if on_status is not None:
            on_status(mensagem)
        else:
            print(mensagem)

    with sync_playwright() as playwright:
        browser = launch_browser(playwright, headless=False)
        context = browser.new_context(viewport=_VIEWPORT)
        page = context.new_page()
        page.goto(config.OWA_URL)

        anunciar(
            "Faça login com sua conta Microsoft na janela que abriu. "
            "Assim que sua caixa de entrada aparecer, o app salva o acesso "
            "e fecha a janela sozinho."
        )

        try:
            page.wait_for_selector(
                ", ".join(_MESSAGE_ITEM_SELECTORS), timeout=LOGIN_TIMEOUT_MS
            )
        except PlaywrightTimeoutError:
            browser.close()
            raise RuntimeError(
                "O login não foi concluído a tempo. Clique em conectar de novo."
            ) from None
        except Exception as exc:  # noqa: BLE001 - janela fechada no meio do caminho
            raise RuntimeError(
                "A janela do navegador foi fechada antes do login terminar."
            ) from exc

        context.storage_state(path=str(config.BROWSER_STATE_PATH))
        browser.close()
        anunciar("Acesso ao Outlook salvo. Já pode rodar a varredura.")


def _require_saved_session() -> None:
    if not config.BROWSER_STATE_PATH.exists():
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
    """
    selector, _ = _find_message_items(page)
    if selector is None:
        return

    seen: set[str] = set()
    stagnant_rounds = 0

    while stagnant_rounds < _STAGNANT_ROUNDS_BEFORE_STOP:
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


class _BrowserSession:
    """Abre o navegador com a sessão salva e o fecha ao final.

    Centraliza o arranjo de Playwright + estado de login, para que os
    scripts, o scanner e o app não o repitam.
    """

    def __init__(self, url: str, ready_selector: str, headless: bool):
        self._url = url
        self._ready_selector = ready_selector
        self._headless = headless

    def __enter__(self) -> Page:
        self._playwright = sync_playwright().start()
        self._browser = launch_browser(self._playwright, self._headless)
        self._context = self._browser.new_context(
            storage_state=str(config.BROWSER_STATE_PATH),
            viewport=_VIEWPORT,
        )
        page = self._context.new_page()
        page.goto(self._url)
        # Esperamos por um elemento da tela, e não por
        # `wait_for_load_state("networkidle")`: o Outlook Web sincroniza em
        # segundo plano o tempo todo, então a rede nunca fica ociosa e essa
        # espera expira por timeout.
        page.wait_for_selector(self._ready_selector, timeout=60_000)
        return page

    def __exit__(self, *exc_info) -> None:
        self._browser.close()
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
