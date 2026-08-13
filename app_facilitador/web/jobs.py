"""Operações longas rodando em segundo plano, com progresso consultável.

A varredura leva minutos numa caixa grande, então não pode acontecer
dentro do ciclo de uma requisição HTTP — a tela ficaria pendurada até o
fim. Aqui ela roda numa thread e a interface consulta o andamento.

Uma thread (e não asyncio) porque o Playwright que lê o Outlook é
síncrono: cada thread abre a sua própria instância, sem disputar um laço
de eventos compartilhado.

São quatro operações, e elas se dividem em duas formas:

- **as que percorrem uma pasta** (varrer, desafixar) — demoradas, com
  contagem de progresso e botão de parar. Compartilham `_StoppableJob`;
  o que muda entre elas é só qual função do `scanner` chamar.
- **as que só vão e voltam** (conectar, ler o calendário) — sem contagem
  e sem parada, cada uma com o seu estado próprio.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime

from app_facilitador import scanner


def _hora(momento: datetime | None) -> str | None:
    """Só a hora, que é o que a tela mostra. None continua None."""
    return momento.strftime("%H:%M:%S") if momento else None


@dataclass
class JobState:
    """Situação de uma operação de pasta, do ponto de vista de quem olha a tela.

    Serve tanto à varredura quanto à busca de fixados: as duas percorrem
    uma pasta contando e-mails e terminam num resumo.
    """

    running: bool = False
    folder: str | None = None
    scanned: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    summary: list[str] = field(default_factory=list)
    # Sinalizado quando o usuário pediu para parar mas a operação ainda
    # não chegou ao próximo ponto de parada — deixa a tela dizer "parando…"
    # em vez de parecer travada no clique.
    stopping: bool = False

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "folder": self.folder,
            "scanned": self.scanned,
            "started_at": _hora(self.started_at),
            "finished_at": _hora(self.finished_at),
            "error": self.error,
            "summary": self.summary,
            "stopping": self.stopping,
        }


class _StoppableJob:
    """Percorre uma pasta numa thread, com progresso e parada cooperativa.

    A subclasse diz **o que** rodar (`_operate`); esta classe cuida do
    resto — thread, trava, estado consultável, sinal de parada e captura
    do erro para que ele chegue à tela em vez de morrer no console.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = JobState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def _operate(self, **opcoes):
        """A operação em si. A subclasse implementa.

        Recebe, além das opções da tela, `on_progress` e `should_stop` —
        e devolve um resultado com `summary_lines()`.
        """
        raise NotImplementedError

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    def start(self, **opcoes) -> bool:
        """Dispara a operação. Devolve False se já houver uma em andamento.

        Recusar em vez de enfileirar é proposital: duas operações
        simultâneas abririam dois navegadores disputando a mesma sessão
        do Outlook.
        """
        with self._lock:
            if self._state.running:
                return False
            self._state = JobState(
                running=True, folder=opcoes.get("folder"), started_at=datetime.now()
            )

        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(opcoes,), daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Pede para a operação parar no próximo ponto seguro.

        A parada é cooperativa: a thread verifica o sinal entre um bloco de
        e-mails e o próximo, então pode levar alguns segundos até um passo
        em andamento (abrir um e-mail, baixar um anexo) terminar. Por isso
        a tela mostra "parando…" em vez de dar como parado na hora.
        """
        with self._lock:
            if self._state.running:
                self._state.stopping = True
        self._stop.set()

    def _run(self, opcoes: dict) -> None:
        try:
            resultado = self._operate(
                on_progress=self._update_progress,
                should_stop=self._stop.is_set,
                **opcoes,
            )
            summary = resultado.summary_lines()
            error = None
        except Exception as exc:  # noqa: BLE001 - a falha precisa chegar à tela, não ao console
            summary = []
            error = str(exc)

        with self._lock:
            self._state.running = False
            self._state.stopping = False
            self._state.finished_at = datetime.now()
            self._state.summary = summary
            self._state.error = error

    def _update_progress(self, scanned: int) -> None:
        with self._lock:
            self._state.scanned = scanned


class ScanJob(_StoppableJob):
    """A varredura: percorre a pasta, identifica propostas e baixa anexos."""

    def _operate(self, **opcoes):
        return scanner.scan(**opcoes)


class UnpinJob(_StoppableJob):
    """A busca de e-mails fixados por engano por uma versão antiga do app.

    Mesma mecânica da varredura — percorrer a pasta abrindo e clicando em
    cada e-mail —, só que decidindo desafixar em vez de baixar.
    """

    def _operate(self, **opcoes):
        return scanner.unpin_all(**opcoes)


@dataclass
class LoginState:
    """Situação da conexão com o Outlook, para a tela acompanhar."""

    running: bool = False
    message: str | None = None
    error: str | None = None
    connected: bool = False

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "message": self.message,
            "error": self.error,
            "connected": self.connected,
        }


class LoginJob:
    """Conecta o app ao Outlook numa thread separada.

    Precisa ser em segundo plano porque o login manual pode levar
    minutos (senha, dois fatores) e a requisição HTTP que o disparou não
    pode ficar pendurada esperando.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = LoginState()
        self._thread: threading.Thread | None = None
        self._confirmed = threading.Event()

    @property
    def state(self) -> LoginState:
        with self._lock:
            return self._state

    def start(self) -> bool:
        """Dispara a conexão. Devolve False se já houver uma em andamento."""
        with self._lock:
            if self._state.running:
                return False
            self._state = LoginState(running=True, message="Abrindo o navegador…")

        self._confirmed.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def confirm(self) -> None:
        """O usuário afirma que já entrou; salva o acesso sem mais esperar.

        A detecção automática cobre o caso normal, mas quando ela não
        reconhece a caixa de entrada o usuário ficaria preso numa espera
        que nunca acaba. Aqui ele decide.
        """
        self._confirmed.set()

    def _run(self) -> None:
        # Importado aqui, e não no topo, para o painel abrir mesmo numa
        # instalação em que o Playwright falhe ao carregar: sem acesso ao
        # Outlook o app ainda mostra o que já foi coletado antes.
        from app_facilitador import browser_client

        try:
            browser_client.login_and_save_session(
                on_status=self._announce,
                should_finish=self._confirmed.is_set,
            )
            error = None
            connected = True
        except Exception as exc:  # noqa: BLE001 - a falha precisa chegar à tela
            error = str(exc)
            connected = False

        with self._lock:
            self._state.running = False
            self._state.error = error
            self._state.connected = connected

    def _announce(self, message: str) -> None:
        with self._lock:
            self._state.message = message


@dataclass
class MeetingsState:
    """Situação da leitura do calendário."""

    running: bool = False
    error: str | None = None
    finished_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "error": self.error,
            "finished_at": _hora(self.finished_at),
        }


class MeetingsJob:
    """Lê as reuniões do dia numa thread separada.

    Também abre um navegador, e por isso demora dezenas de segundos. Na
    versão anterior isso acontecia dentro da requisição: a tela ficava
    pendurada até terminar, e quando falhava — por não haver acesso ao
    Outlook ainda — o erro era engolido e o clique simplesmente não fazia
    nada visível.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state = MeetingsState()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> MeetingsState:
        with self._lock:
            return self._state

    def start(self) -> bool:
        with self._lock:
            if self._state.running:
                return False
            self._state = MeetingsState(running=True)

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        from app_facilitador import calendar_client

        try:
            calendar_client.refresh_meetings()
            error = None
        except Exception as exc:  # noqa: BLE001 - a falha precisa chegar à tela
            error = str(exc)

        with self._lock:
            self._state.running = False
            self._state.error = error
            self._state.finished_at = datetime.now()
