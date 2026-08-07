"""Cálculo do tempo restante até o vencimento de um processo de cotação.

Atende o item 2.3 do pedido: um indicativo de quanto falta para vencer
cada cotação em andamento, com destaque visual por urgência.

A contagem é em **dias corridos**, não úteis: o prazo dado a um
fornecedor é uma data de calendário, e tratar sábado como "dia que não
conta" faria o app dizer que ainda há prazo quando o cliente já cobra.
"""

from dataclasses import dataclass
from datetime import date, datetime

# Faixas do semáforo, em dias restantes.
_CRITICAL_DAYS = 2
_WARNING_DAYS = 7

STATUS_LABELS = {
    "vencido": "Vencido",
    "critico": "Vence já",
    "atencao": "Atenção",
    "ok": "No prazo",
    "sem_prazo": "Sem prazo definido",
}


@dataclass
class DeadlineStatus:
    """Situação de prazo de um processo, pronta para exibição."""

    days_remaining: int | None
    status: str

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def description(self) -> str:
        if self.days_remaining is None:
            return "sem prazo definido"
        if self.days_remaining < 0:
            days = abs(self.days_remaining)
            return f"venceu há {days} dia{'s' if days != 1 else ''}"
        if self.days_remaining == 0:
            return "vence hoje"
        return f"faltam {self.days_remaining} dia{'s' if self.days_remaining != 1 else ''}"


def parse_deadline(raw: str | None) -> date | None:
    """Lê uma data digitada pelo usuário nos formatos DD/MM/AAAA ou AAAA-MM-DD."""
    if not raw:
        return None

    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def status_for(deadline: date | None, today: date | None = None) -> DeadlineStatus:
    """Classifica quanto tempo resta até `deadline`."""
    if deadline is None:
        return DeadlineStatus(days_remaining=None, status="sem_prazo")

    today = today if today is not None else date.today()
    days_remaining = (deadline - today).days

    if days_remaining < 0:
        status = "vencido"
    elif days_remaining <= _CRITICAL_DAYS:
        status = "critico"
    elif days_remaining <= _WARNING_DAYS:
        status = "atencao"
    else:
        status = "ok"

    return DeadlineStatus(days_remaining=days_remaining, status=status)
