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

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "folder": self.folder,
            "scanned": self.scanned,
            "started_at": self.started_at.strftime("%H:%M:%S") if self.started_at else None,
            "finished_at": self.finished_at.strftime("%H:%M:%S") if self.finished_at else None,
            "error": self.error,
            "summary": self.summary,
        }


class ScanJob:
    """Guarda a varredura em andamento e o resultado da última execução."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = JobState()
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> JobState:
        with self._lock:
            return self._state

    def is_running(self) -> bool:
        with self._lock:
            return self._state.running

    def start(self, folder: str | None = None, max_messages: int | None = None) -> bool:
        """Dispara a varredura. Devolve False se já houver uma em andamento.

        Recusar em vez de enfileirar é proposital: duas varreduras
        simultâneas abririam dois navegadores disputando a mesma sessão
        do Outlook.
        """
        with self._lock:
            if self._state.running:
                return False
            self._state = JobState(running=True, folder=folder, started_at=datetime.now())

        self._thread = threading.Thread(
            target=self._run, args=(folder, max_messages), daemon=True
        )
        self._thread.start()
        return True

    def _run(self, folder: str | None, max_messages: int | None) -> None:
        try:
            result = scanner.scan(
                folder=folder,
                max_messages=max_messages,
                on_progress=self._update_progress,
            )
            summary = result.summary_lines()
            error = None
        except Exception as exc:  # noqa: BLE001 - a falha precisa chegar à tela, não ao console
            summary = []
            error = str(exc)

        with self._lock:
            self._state.running = False
            self._state.finished_at = datetime.now()
            self._state.summary = summary
            self._state.error = error

    def _update_progress(self, scanned: int) -> None:
        with self._lock:
            self._state.scanned = scanned
