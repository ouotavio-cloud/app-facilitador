"""Leitura das reuniões do dia no calendário do Outlook Web.

Atende o item 2.2 do pedido: conferir se há reuniões e seus horários.

Como no restante do projeto, é leitura de tela — a Graph API está
bloqueada pela TI. O resultado fica em cache num arquivo JSON para que o
painel abra instantaneamente, sem precisar subir um navegador a cada vez
que a página é carregada.
"""

import json
import re
from datetime import date, datetime

from app_facilitador import config

# Seletores candidatos para os compromissos na grade do calendário. Como
# na caixa de entrada, não há API estável: tentamos do mais específico ao
# mais genérico até algum encontrar elementos.
_EVENT_SELECTORS = [
    'div[role="button"][aria-label*=":"]',
    '[role="gridcell"] [role="button"]',
    'div[data-automationid="calendarItem"]',
]

# Horário no começo do rótulo do compromisso ("14:00 - 15:00 Reunião...").
_TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def _parse_event_label(label: str) -> dict | None:
    """Extrai horário e título do rótulo de um compromisso.

    Devolve `None` quando não há horário reconhecível: a grade do
    calendário tem muitos botões que não são compromissos, e o horário é
    o que distingue um evento real do resto da interface.
    """
    times = _TIME_PATTERN.findall(label)
    if not times:
        return None

    start = f"{int(times[0][0]):02d}:{times[0][1]}"
    end = f"{int(times[1][0]):02d}:{times[1][1]}" if len(times) > 1 else None

    # O título é o que sobra depois de tirar os horários do rótulo.
    title = _TIME_PATTERN.sub("", label)
    title = title.strip(" -–—\t\n")

    return {"start": start, "end": end, "title": title or "(sem título)"}


def parse_event_labels(labels: list[str]) -> list[dict]:
    """Converte os rótulos lidos da tela em compromissos ordenados por horário."""
    events = []
    seen = set()
    for label in labels:
        event = _parse_event_label(label)
        if event is None:
            continue
        key = (event["start"], event["title"])
        if key in seen:
            continue
        seen.add(key)
        events.append(event)

    return sorted(events, key=lambda event: event["start"])


def cached_meetings() -> dict:
    """Reuniões guardadas da última consulta, sem abrir o navegador.

    O painel usa isto para carregar rápido. Se o cache for de outro dia, é
    sinalizado como desatualizado em vez de mostrar reuniões de ontem como
    se fossem de hoje.
    """
    if not config.MEETINGS_CACHE_PATH.exists():
        return {"events": [], "updated_at": None, "stale": True}

    try:
        data = json.loads(config.MEETINGS_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"events": [], "updated_at": None, "stale": True}

    data["stale"] = data.get("day") != date.today().isoformat()
    return data


def refresh_meetings() -> dict:
    """Abre o calendário no navegador, lê as reuniões de hoje e guarda em cache."""
    from app_facilitador import browser_client

    with browser_client.open_calendar_session() as page:
        labels = page.evaluate(
            """
            selectors => {
                for (const selector of selectors) {
                    const found = Array.from(document.querySelectorAll(selector))
                        .map(el => (el.getAttribute('aria-label') || el.textContent || '').trim())
                        .filter(text => text.length > 0);
                    if (found.length > 0) return found;
                }
                return [];
            }
            """,
            _EVENT_SELECTORS,
        )

    data = {
        "events": parse_event_labels(labels),
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "day": date.today().isoformat(),
    }
    config.MEETINGS_CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    data["stale"] = False
    return data
