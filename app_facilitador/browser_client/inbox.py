"""A lista de e-mails: pastas, rolagem, e abrir uma mensagem.

Tudo o que depende da ESTRUTURA da lista do Outlook Web mora aqui. Não há
API estável para nada disto — é automação de interface —, então os
seletores são calibrados contra o HTML real com
`scripts/browser_inbox_debug.py` e podem mudar quando a Microsoft
atualizar o Outlook.

As funções recebem a `page` pronta: quem a abre é `session.py`.
"""

from collections.abc import Callable, Iterator

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app_facilitador import inbox_parser, logs

_log = logs.get_logger("browser")

# Seletores candidatos para os itens da lista de e-mails na caixa de
# entrada do Outlook Web. Não há API estável para isso — é automação de
# interface, então mais de uma opção é tentada, da mais específica para a
# mais genérica, até uma encontrar elementos na tela.
MESSAGE_ITEM_SELECTORS = [
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

# Usado para detectar que a lista trocou ao mudar de pasta.
_JS_FIRST_CONV_ID = """
selector => {
    const el = document.querySelector(selector);
    return el ? el.getAttribute('data-convid') : null;
}
"""

# Pausa após trocar de pasta, dando tempo da nova lista assentar.
_FOLDER_SETTLE_MS = 1_500


def find_message_items(page: Page):
    """O primeiro seletor que encontra linhas de e-mail na tela, e o locator."""
    for selector in MESSAGE_ITEM_SELECTORS:
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

    selector, _ = find_message_items(page)
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
    selector, _ = find_message_items(page)
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
    selector, _ = find_message_items(page)
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

# Identidade do que está aberto no painel de leitura AGORA: o assunto, o
# remetente e os nomes dos anexos. Muda quando o e-mail muda.
_JS_READING_PANE_FINGERPRINT = """
() => {
    const painel = document.querySelector('[role="main"]');
    if (!painel) return '';

    // Os nomes dos anexos são a parte mais sensível: é justamente o que a
    // varredura vai ler em seguida, então é o que precisa ter trocado.
    const anexos = Array.from(painel.querySelectorAll('[role="option"][aria-label]'))
        .map(el => el.getAttribute('aria-label'))
        .join('|');

    // O texto do topo do painel cobre assunto e remetente sem depender de
    // classe de CSS gerada pelo build.
    const topo = (painel.innerText || '').slice(0, 400);

    return anexos + '###' + topo;
}
"""

# Quanto esperar o painel de leitura assumir o e-mail clicado. Generoso: um
# anexo pesado ou uma rede de obra ruim atrasam a montagem, e desistir cedo
# demais faria o app pular proposta boa.
_PANE_SWITCH_TIMEOUT_MS = 10_000
_PANE_POLL_MS = 250


def _reading_pane_fingerprint(page: Page) -> str:
    """O que está aberto no painel agora, resumido numa string comparável."""
    try:
        return page.evaluate(_JS_READING_PANE_FINGERPRINT)
    except Exception:  # noqa: BLE001 - painel navegando; trata como desconhecido
        return ""


def _reading_pane_switched(page: Page, conv_id: str, before: str) -> bool:
    """Confirma que o painel passou a mostrar ESTE e-mail, e não o anterior.

    Sem esta confirmação o app clicava na linha, esperava dois segundos
    fixos e lia o painel — desse jeito, quando o clique não pegava ou a
    montagem demorava mais que isso, ele lia os anexos do e-mail
    **anterior** e os arquivava no processo e na pasta deste. O sintoma na
    caixa do usuário era o pior possível: baixar sempre os mesmos arquivos e
    não baixar o que o resumo dizia estar baixando.

    Duas provas, e as duas precisam valer:

    1. `aria-selected="true"` na linha clicada — o Outlook marca assim a
       conversa aberta (conferido no HTML real: 1 linha de 12). É o que
       garante que estamos no e-mail **certo**.
    2. A impressão do painel mudou — é o que garante que ele terminou de
       **trocar**, e não que ainda mostra o anterior.

    Devolve False em vez de seguir na dúvida. Um e-mail pulado aparece no
    resumo; um anexo arquivado na pasta errada não aparece em lugar nenhum.
    """
    selecionado = f'[data-convid="{conv_id}"][aria-selected="true"]'
    prazo = _PANE_SWITCH_TIMEOUT_MS
    while prazo > 0:
        page.wait_for_timeout(_PANE_POLL_MS)
        prazo -= _PANE_POLL_MS

        if page.locator(selecionado).count() == 0:
            continue
        if _reading_pane_fingerprint(page) != before:
            return True

    return False


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

    antes = _reading_pane_fingerprint(page)

    try:
        linha.click(timeout=_MESSAGE_OPEN_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - linha descartada pela virtualização
        return False

    if not _reading_pane_switched(page, conv_id, antes):
        _log.warning(
            "cliquei em %s mas o painel de leitura não trocou; não vou ler os "
            "anexos para não atribuí-los ao e-mail errado", conv_id
        )
        return False

    _log.info("abriu o e-mail %s", conv_id)
    return True


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


__all__ = [
    "MESSAGE_ITEM_SELECTORS",
    "find_message_items",
    "list_folders",
    "open_folder",
    "list_visible_messages",
    "scan_inbox",
    "open_message",
    "read_message_body",
    "unpin_message",
]
