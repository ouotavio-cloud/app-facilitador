"""Parsing dos dados brutos extraídos da lista de e-mails do Outlook Web.

Separado de `browser_client` de propósito: aqui não há navegador nem
Playwright, só transformação de dicionários — o que torna esta parte
testável com dados reais capturados, sem depender de login nem de rede
(ver PLANEJAMENTO.md, seção 7).
"""

import re
from datetime import datetime

# Itens fixados ("Fixado") no topo da caixa de entrada usam um layout mais
# compacto que não expõe data nem preview como elementos separados do DOM
# — só aparecem concatenados no aria-label da linha inteira. Daí a
# necessidade de extrair a data por regex nesse caso.
_DATE_ONLY_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_FULL_DATETIME_PATTERN = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2})")


def parse_received_at(raw_date: str | None) -> datetime | None:
    """Converte a data exibida pelo Outlook Web em `datetime`.

    Aceita os dois formatos observados na interface em português:
    `"Qui, 06/08/2026 13:04"` (título completo do elemento de data) e
    `"22/05/2026"` (fallback do aria-label em itens fixados). Retorna
    `None` quando nenhum dos dois casa, para o chamador decidir o que
    fazer em vez de quebrar a varredura inteira por causa de um item.
    """
    if not raw_date:
        return None

    match = _FULL_DATETIME_PATTERN.search(raw_date)
    if match:
        day, month, year, hour, minute = (int(g) for g in match.groups())
        return datetime(year, month, day, hour, minute)

    match = _DATE_ONLY_PATTERN.search(raw_date)
    if match:
        day, month, year = (int(g) for g in match.groups())
        return datetime(year, month, day)

    return None


def parse_message_row(raw: dict) -> dict:
    """Normaliza um item bruto da lista em um dicionário de mensagem.

    `raw` vem da extração em lote feita no navegador e traz, além dos
    campos do DOM, o `aria_label` da linha inteira — que é a única fonte
    de algumas informações (flags de "Fixado"/"Tem anexos" e, em itens
    fixados, a própria data).
    """
    aria_label = raw.get("aria_label") or ""
    sender_name = raw.get("sender_name") or ""

    # As flags aparecem sempre antes do nome do remetente no aria-label;
    # limitar a busca a esse prefixo evita falso positivo quando as
    # mesmas palavras aparecem no assunto ou no preview da mensagem.
    prefix = aria_label.split(sender_name, 1)[0] if sender_name else ""

    raw_date = raw.get("date_title")
    if not raw_date:
        match = _DATE_ONLY_PATTERN.search(aria_label)
        raw_date = match.group(0) if match else None

    return {
        "conv_id": raw.get("conv_id"),
        "sender_name": sender_name,
        "sender_email": raw.get("sender_email"),
        "subject": (raw.get("subject") or "").strip(),
        "received_at_raw": raw_date,
        "received_at": parse_received_at(raw_date),
        "preview": raw.get("preview"),
        "is_pinned": "Fixado" in prefix,
        "has_attachments": "Tem anexos" in prefix,
    }


def searchable_text(message: dict) -> str:
    """Junta os campos onde faz sentido procurar o código do processo.

    Hoje só o que a lista expõe (assunto e preview). Abrir a mensagem
    completa e varrer corpo e anexos é a Fase 2 completa do roadmap.
    """
    return " ".join(part for part in (message.get("subject"), message.get("preview")) if part)
