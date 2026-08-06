"""Automação do Outlook Web via Playwright.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.
"""

import re

from playwright.sync_api import BrowserContext, Locator, Page, sync_playwright

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

# Classes CSS observadas na estrutura real do Outlook Web (calibradas via
# scripts/browser_inbox_debug.py) para localizar remetente, assunto e
# preview dentro de um item da lista. São classes geradas pelo build do
# Fluent UI (Griffel) e podem mudar quando a Microsoft atualizar o Outlook
# Web — se a extração parar de funcionar, recalibrar com o script de
# diagnóstico antes de mexer aqui.
_JS_EXTRACT_ITEM_FIELDS = """
el => {
    const senderSpan = el.querySelector('.ESO13 span[title]');
    const subjectSpan = el.querySelector('.IjzWp span');
    const previewSpan = el.querySelector('.ASFJj');
    const titledSpans = Array.from(el.querySelectorAll('span[title]'));
    const dateSpan = titledSpans.find(s => s !== senderSpan);
    return {
        sender_name: senderSpan ? senderSpan.textContent.trim() : null,
        sender_email: senderSpan ? senderSpan.getAttribute('title') : null,
        subject: subjectSpan ? subjectSpan.textContent.trim() : null,
        date_title: dateSpan ? dateSpan.getAttribute('title') : null,
        preview: previewSpan ? previewSpan.textContent.trim() : null,
    };
}
"""

# Itens fixados ("Fixado") no topo da caixa de entrada usam um layout mais
# compacto que não expõe data nem preview como elementos separados do DOM
# — só aparecem concatenados no aria-label da linha inteira. Esse regex é
# o fallback pra extrair a data nesse caso.
_DATE_IN_ARIA_LABEL_PATTERN = re.compile(r"\d{2}/\d{2}/\d{4}")


def _parse_message_row(raw: dict, row_aria_label: str) -> dict:
    """Combina os campos extraídos do DOM com informação só disponível no aria-label.

    Recebe o dicionário bruto de `_JS_EXTRACT_ITEM_FIELDS` e o aria-label
    da linha inteira (que sempre existe, mesmo quando faltam elementos
    visíveis — caso dos itens fixados).
    """
    sender_name = raw.get("sender_name") or ""
    prefix = row_aria_label.split(sender_name, 1)[0] if sender_name else ""

    date_title = raw.get("date_title")
    if date_title is None:
        match = _DATE_IN_ARIA_LABEL_PATTERN.search(row_aria_label)
        date_title = match.group(0) if match else None

    return {
        "sender_name": sender_name,
        "sender_email": raw.get("sender_email"),
        "subject": (raw.get("subject") or "").strip(),
        "received_at": date_title,
        "preview": raw.get("preview"),
        "is_pinned": "Fixado" in prefix,
        "has_attachments": "Tem anexos" in prefix,
    }


def _extract_message(item: Locator) -> dict:
    raw = item.evaluate(_JS_EXTRACT_ITEM_FIELDS)
    row_aria_label = item.get_attribute("aria-label") or ""
    message = _parse_message_row(raw, row_aria_label)
    message["conv_id"] = item.get_attribute("data-convid")
    return message


def list_visible_messages(page: Page) -> list[dict]:
    """Extrai os e-mails atualmente renderizados na tela (sem rolar a lista).

    Só cobre o que já está no DOM — a lista do Outlook Web é virtualizada,
    então isso não é uma varredura completa da caixa de entrada (ver
    PLANEJAMENTO.md, seção 1.3). A varredura completa (com scroll) é um
    passo futuro que reaproveita esta função para cada trecho carregado.
    """
    _, items = _find_message_items(page)
    if items is None:
        return []
    return [_extract_message(items.nth(i)) for i in range(items.count())]


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
    """Abre a caixa de entrada e espera os itens da lista aparecerem.

    Não usamos `wait_for_load_state("networkidle")`: o Outlook Web mantém
    sincronização em segundo plano o tempo todo, então a rede nunca fica
    de fato ociosa e essa espera expira por timeout. Esperar diretamente
    pelo primeiro seletor de item de e-mail é mais confiável.
    """
    page = context.new_page()
    page.goto(config.OWA_URL)
    combined_selector = ", ".join(_MESSAGE_ITEM_SELECTORS)
    page.wait_for_selector(combined_selector, timeout=60_000)
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

            print("\n--- aria-label de cada item (para calibrar o parser) ---\n")
            for i in range(count):
                aria_label = items.nth(i).get_attribute("aria-label")
                print(f"  [{i}] {aria_label!r}")

            html_dump_path = config.BASE_DIR / "debug_inbox_items.html"
            chunks = []
            for i in range(count):
                outer_html = items.nth(i).evaluate("el => el.outerHTML")
                chunks.append(f"<!-- ===== item [{i}] ===== -->\n{outer_html}")
            html_dump_path.write_text("\n\n".join(chunks), encoding="utf-8")
            print(f"\nHTML de todos os {count} itens salvo em {html_dump_path}")

        browser.close()
