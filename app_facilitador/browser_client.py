"""Automação do Outlook Web via Playwright.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.
"""

from collections.abc import Callable, Iterator

from playwright.sync_api import BrowserContext, Page, sync_playwright

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

# Quantas rodadas seguidas de scroll sem nenhuma conversa nova antes de
# considerar que a lista acabou. Mais de uma porque o carregamento é
# assíncrono: uma rodada vazia pode significar apenas que o Outlook ainda
# não devolveu o próximo bloco.
_STAGNANT_ROUNDS_BEFORE_STOP = 3

# Pausa após cada scroll, dando tempo do Outlook Web buscar e renderizar
# o próximo bloco da lista virtualizada.
_SCROLL_SETTLE_MS = 1_200


def login_and_save_session() -> None:
    """Abre um navegador visível para o usuário logar manualmente uma vez."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(config.OWA_URL)

        print(
            "\nUma janela do navegador foi aberta. Faça login normalmente "
            "com sua conta Microsoft até ver sua caixa de entrada."
        )
        input("Quando terminar de logar e ver seus e-mails, volte aqui e aperte Enter... ")

        context.storage_state(path=str(config.BROWSER_STATE_PATH))
        browser.close()
        print(f"Sessão salva em {config.BROWSER_STATE_PATH}. Já pode fechar o navegador.")


def _require_saved_session() -> None:
    if not config.BROWSER_STATE_PATH.exists():
        raise RuntimeError(
            "Nenhuma sessão salva encontrada. Rode primeiro: "
            "python scripts/browser_login.py"
        )


def _open_inbox(context: BrowserContext) -> Page:
    """Abre a caixa de entrada e espera os itens da lista aparecerem.

    Não usamos `wait_for_load_state("networkidle")`: o Outlook Web mantém
    sincronização em segundo plano o tempo todo, então a rede nunca fica
    de fato ociosa e essa espera expira por timeout. Esperar diretamente
    pelo primeiro seletor de item de e-mail é mais confiável.
    """
    page = context.new_page()
    page.goto(config.OWA_URL)
    page.wait_for_selector(", ".join(_MESSAGE_ITEM_SELECTORS), timeout=60_000)
    return page


def _find_message_items(page: Page):
    for selector in _MESSAGE_ITEM_SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            return selector, locator
    return None, None


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

        items = page.locator(selector)
        count = items.count()
        if count == 0:
            return
        items.nth(count - 1).scroll_into_view_if_needed()
        page.wait_for_timeout(_SCROLL_SETTLE_MS)


def open_inbox_session(headless: bool = False):
    """Context manager que entrega a caixa de entrada pronta para leitura.

    Centraliza o boilerplate de abrir o navegador com a sessão salva, para
    que os scripts e o scanner não repitam esse arranjo.
    """
    _require_saved_session()

    class _InboxSession:
        def __enter__(self) -> Page:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=headless)
            self._context = self._browser.new_context(
                storage_state=str(config.BROWSER_STATE_PATH)
            )
            return _open_inbox(self._context)

        def __exit__(self, *exc_info) -> None:
            self._browser.close()
            self._playwright.stop()

    return _InboxSession()


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
