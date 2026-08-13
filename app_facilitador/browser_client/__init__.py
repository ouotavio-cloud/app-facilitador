"""Automação do Outlook Web via Playwright.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.

Era um módulo só, de 1.300 linhas, misturando quatro assuntos que mudam
por motivos diferentes. Agora cada um tem o seu arquivo:

    session.py      abre o Chromium, faz o login, entrega a página pronta
    inbox.py        a lista: pastas, rolagem, abrir e ler uma mensagem
    downloads.py    os anexos do e-mail aberto: achar e baixar
    diagnostics.py  despejos da página real, para recalibrar seletores

Este arquivo é só a porta de entrada: reexporta o que o resto do app usa,
para que `from app_facilitador import browser_client` continue valendo e
ninguém precise saber em qual arquivo cada função mora.

Ao escrever teste que substitui uma função (`monkeypatch.setattr`), mire
no submódulo onde ela é DEFINIDA — `browser_client.inbox.open_message` —,
e não no nome reexportado aqui: quem chama por dentro do pacote enxerga o
submódulo, não este atalho.
"""

from app_facilitador.browser_client.diagnostics import (
    dump_inbox_debug,
    dump_message_debug,
    print_visible_messages,
)
from app_facilitador.browser_client.downloads import (
    download_attachment,
    find_attachments,
)
from app_facilitador.browser_client.inbox import (
    MESSAGE_ITEM_SELECTORS,
    list_folders,
    list_visible_messages,
    open_folder,
    open_message,
    read_message_body,
    scan_inbox,
    unpin_message,
)
from app_facilitador.browser_client.session import (
    LOGIN_POLL_MS,
    LOGIN_TIMEOUT_MS,
    first_page,
    login_and_save_session,
    open_browser_context,
    open_calendar_session,
    open_inbox_session,
)

__all__ = [
    "MESSAGE_ITEM_SELECTORS",
    "LOGIN_POLL_MS",
    "LOGIN_TIMEOUT_MS",
    "download_attachment",
    "dump_inbox_debug",
    "dump_message_debug",
    "find_attachments",
    "first_page",
    "list_folders",
    "list_visible_messages",
    "login_and_save_session",
    "open_browser_context",
    "open_calendar_session",
    "open_folder",
    "open_inbox_session",
    "open_message",
    "print_visible_messages",
    "read_message_body",
    "scan_inbox",
    "unpin_message",
]
