"""Execução da varredura em segundo plano, com progresso consultável.

A varredura leva minutos numa caixa grande, então não pode acontecer
dentro do ciclo de uma requisição HTTP — a tela ficaria pendurada até o
fim. Aqui ela roda numa thread e a interface consulta o andamento.

Uma thread (e não asyncio) porque o Playwright que lê o Outlook é
síncrono: cada thread abre a sua própria instância, sem disputar um laço
de eventos compartilhado.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime

from app_facilitador import scanner


@dataclass
class JobState:
    """Situação da varredura, do ponto de vista de quem está olhando a tela."""

    running: bool = False
    folder: str | None = None
    scanned: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    summary: list[str] = field(default_factory=list)
    # Sinalizado quando o usuário pediu para parar mas a varredura ainda
    # não chegou ao próximo ponto de parada — deixa a tela dizer "parando…"
    # em vez de parecer travada no clique.
    stopping: bool = False

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "folder": self.folder,
            "scanned": self.scanned,
            "started_at": self.started_at.strftime("%H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%H:%M:%S") if self.finished_at else None,
            "error": self.error,
            "summary": self.summary,
            "stopping": self.stopping,
        }


class ScanJob:
    """Guarda a varredura em andamento e o resultado da última execução."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = JobState()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    def is_running(self) -> bool:
        with self._lock:
            return self._state.running

    def start(
        self,
        folder: str | None = None,
        max_messages: int | None = None,
        download_attachments: bool = True,
    ) -> bool:
        """Dispara a varredura. Devolve False se já houver uma em andamento.

        Recusar em vez de enfileirar é proposital: duas varreduras
        simultâneas abririam dois navegadores disputando a mesma sessão
        do Outlook.
        """
        with self._lock:
            if self._state.running:
                return False
            self._state = JobState(running=True, folder=folder, started_at=datetime.now())

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, args=(folder, max_messages, download_attachments), daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Pede para a varredura parar no próximo ponto seguro.

        A parada é cooperativa: a thread verifica o sinal entre um bloco de
        e-mails e o próximo, então pode levar alguns segundos até um passo
        em andamento (abrir um e-mail, baixar um anexo) terminar. Por isso
        a tela mostra "parando…" em vez de dar como parado na hora.
        """
        with self._lock:
            if self._state.running:
                self._state.stopping = True
        self._stop.set()

    def _run(
        self, folder: str | None, max_messages: int | None, download_attachments: bool
    ) -> None:
        try:
            result = scanner.scan(
                folder=folder,
                max_messages=max_messages,
                on_progress=self._update_progress,
                should_stop=self._stop.is_set,
                download_attachments=download_attachments,
            )
            summary = result.summary_lines()
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
            "finished_at": self.finished_at.strftime("%H:%M:%S") if self.finished_at else None,
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
