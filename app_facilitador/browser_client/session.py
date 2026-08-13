"""Abrir o navegador, fazer o login uma vez e entregar a página pronta.

Usado porque a Graph API está bloqueada por política de TI da organização
e o novo Outlook não mantém um cache local legível (ver PLANEJAMENTO.md,
seção 2). O usuário loga manualmente uma vez; a sessão fica salva
localmente para reaproveitar nas próximas execuções.
"""

import time
from collections.abc import Callable
from datetime import datetime

from playwright.sync_api import Page, sync_playwright

from app_facilitador import config, logs, paths
from app_facilitador.browser_client import inbox

_log = logs.get_logger("browser")

# Uma janela maior renderiza mais e-mails por vez, reduzindo o número de
# rodadas necessárias para percorrer uma caixa com milhares de conversas.
_VIEWPORT = {"width": 1600, "height": 1200}

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
_LOGIN_READY_SELECTORS = [*inbox.MESSAGE_ITEM_SELECTORS, '[role="treeitem"]']


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

    **`channel="chromium"`, e é isto que mantém o download menor.** A partir
    do Playwright 1.49, `headless=True` procura por padrão um segundo
    navegador — o "chrome-headless-shell", 323 MB à parte do Chromium de
    597 MB. O app roda de cara aberta (o usuário precisa ver a janela para
    logar), e o modo headless só é usado pela verificação da compilação.
    Pedir o canal `chromium` faz os dois modos usarem o MESMO binário, e
    assim a compilação pode instalar o navegador com `--no-shell` e não
    embarcar os 323 MB que nunca seriam executados.

    Devolve um contexto (não um navegador): no modo persistente o
    Playwright não expõe os dois separadamente.
    """
    paths.configure_playwright_browsers()
    config.BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        return playwright.chromium.launch_persistent_context(
            str(config.BROWSER_PROFILE_DIR),
            channel="chromium",
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
_ROUNDS_TOO_EARLY = 5


def _closed_window_message(rodada: int) -> str:
    """Explica o fechamento conforme quando ele aconteceu.

    Sumir em segundos não é a mesma coisa que desistir no meio do login, e
    a causa provável é outra: uma cópia do app ainda aberta segurando o
    mesmo perfil de navegador.
    """
    if rodada < _ROUNDS_TOO_EARLY:
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
                raise RuntimeError(_closed_window_message(rodada))

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
        config.OWA_URL, ", ".join(inbox.MESSAGE_ITEM_SELECTORS), headless
    )


def open_calendar_session(headless: bool = False) -> _BrowserSession:
    """Context manager que entrega o calendário do dia pronto para leitura."""
    _require_saved_session()
    # A grade do calendário é montada por JS; esperar por ela evita ler a
    # página antes dos compromissos existirem.
    return _BrowserSession(
        config.OWA_CALENDAR_URL, '[role="grid"], [role="main"]', headless
    )
