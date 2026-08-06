"""Automação do Outlook Web via Playwright.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.
"""

from playwright.sync_api import BrowserContext, Page, sync_playwright

from app_facilitador import config

# Seletores candidatos para os itens da lista de e-mails na caixa de
# entrada do Outlook Web. Não há API estável para isso — é automação de
# interface, então mais de uma opção é tentada, da mais específica para a
# mais genérica, até uma encontrar elementos na tela.
_MESSAGE_ITEM_SELECTORS = [
    '[role="option"][aria-label]',
    'div[role="listitem"]',
    '[data-convid]',
]


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


def _open_inbox(context: BrowserContext) -> Page:
    page = context.new_page()
    page.goto(config.OWA_URL)
    page.wait_for_load_state("networkidle", timeout=60_000)
    return page


def _find_message_items(page: Page):
    for selector in _MESSAGE_ITEM_SELECTORS:
        locator = page.locator(selector)
        if locator.count() > 0:
            return selector, locator
    return None, None


def dump_inbox_debug(limit: int = 10) -> None:
    """Abre a caixa de entrada e imprime o texto bruto dos primeiros itens.

    Serve para descobrir a estrutura real da tela (não há documentação
    oficial dos seletores do Outlook Web), calibrando a extração de dados
    de fato depois.
    """
    if not config.BROWSER_STATE_PATH.exists():
        raise RuntimeError(
            "Nenhuma sessão salva encontrada. Rode primeiro: "
            "python scripts/browser_login.py"
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(storage_state=str(config.BROWSER_STATE_PATH))
        page = _open_inbox(context)

        screenshot_path = config.BASE_DIR / "debug_inbox.png"
        page.screenshot(path=str(screenshot_path))
        print(f"Screenshot salvo em {screenshot_path}")

        selector, items = _find_message_items(page)
        if items is None:
            print(
                "Nenhum seletor conhecido encontrou itens na tela. "
                "Envie o screenshot para calibrar os seletores."
            )
        else:
            count = min(items.count(), limit)
            print(f"Seletor usado: {selector!r} — {items.count()} itens encontrados, mostrando {count}:\n")
            for i in range(count):
                text = items.nth(i).inner_text().replace("\n", " | ")
                print(f"  [{i}] {text}")

        browser.close()
