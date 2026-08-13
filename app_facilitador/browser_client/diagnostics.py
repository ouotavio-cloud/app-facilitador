"""Despejos da estrutura real da página, para recalibrar os seletores.

A leitura do Outlook depende da estrutura da página, que a Microsoft muda
sem aviso. Quando algo para de funcionar, é por aqui que se descobre a
estrutura nova — antes de mexer nos seletores, e sem outra compilação às
cegas.

Nada aqui roda na varredura normal: é ferramenta de calibração, chamada
pelos scripts de `scripts/` e por `scanner` na primeira falha de download.
"""

import json

from playwright.sync_api import Page

from app_facilitador import attachments, config
from app_facilitador.browser_client import inbox, session

# Extrai a estrutura em volta de cada anexo: o cartão do anexo e os
# controles (botões, menus, links) perto dele. É o que faltava no
# diagnóstico anterior, que pegava só [role=main] e não continha os anexos —
# eles ficam fora dessa região no novo Outlook.
_JS_DUMP_ATTACHMENTS = """
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
_JS_DUMP_CONVERSATION = """
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

    O arquivo contém e-mail real do usuário (nomes de anexo, assunto,
    remetente): fica na pasta de dados e nunca é versionado.
    """
    try:
        anexos = page.evaluate(
            _JS_DUMP_ATTACHMENTS, sorted(attachments.DOCUMENT_EXTENSIONS)
        )
    except Exception as exc:  # noqa: BLE001 - diagnóstico não pode quebrar a varredura
        anexos = [{"erro": str(exc)}]

    try:
        conversa = page.evaluate(_JS_DUMP_CONVERSATION)
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


def print_visible_messages() -> None:
    """Abre a caixa de entrada e imprime os e-mails visíveis já estruturados."""
    with session.open_inbox_session() as page:
        messages = inbox.list_visible_messages(page)
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
    with session.open_inbox_session() as page:
        screenshot_path = config.BASE_DIR / "debug_inbox.png"
        page.screenshot(path=str(screenshot_path))
        print(f"Screenshot salvo em {screenshot_path}")

        selector, items = inbox.find_message_items(page)
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
