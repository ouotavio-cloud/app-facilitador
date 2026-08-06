"""Cliente mínimo para a Microsoft Graph API (leitura de e-mails e calendário)."""

import time
from datetime import datetime, timedelta, timezone

import requests

from app_facilitador import config


def _get(url: str, token: str, params: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", "5"))
        time.sleep(retry_after)
        response = requests.get(url, headers=headers, params=params, timeout=30)

    response.raise_for_status()
    return response.json()


def list_recent_messages(token: str, top: int = 5) -> list[dict]:
    """Retorna os `top` e-mails mais recentes da caixa de entrada principal."""
    params = {
        "$top": top,
        "$orderby": "receivedDateTime desc",
        "$select": "subject,from,receivedDateTime",
    }
    data = _get(f"{config.GRAPH_BASE_URL}/me/mailFolders/inbox/messages", token, params)
    return data.get("value", [])


def list_today_events(token: str) -> list[dict]:
    """Retorna os eventos de calendário de hoje (fuso horário local)."""
    now = datetime.now(timezone.utc).astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    params = {
        "startDateTime": start.isoformat(),
        "endDateTime": end.isoformat(),
        "$select": "subject,start,end",
        "$orderby": "start/dateTime",
    }
    data = _get(f"{config.GRAPH_BASE_URL}/me/calendarView", token, params)
    return data.get("value", [])
