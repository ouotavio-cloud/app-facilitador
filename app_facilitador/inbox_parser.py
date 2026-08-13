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


# As marcas que o Outlook empilha no COMEÇO do rótulo da linha, antes do
# remetente. Só "Tem anexos" e "Fixado" são lidas pelo app; as outras estão
# aqui para serem consumidas quando vierem na frente delas.
_ROW_FLAGS = (
    "Tem anexos", "Fixado", "Importante", "Não lida", "Não lido",
    "Sinalizada", "Sinalizado", "Respondida", "Encaminhada",
)


def _leading_flags(aria_label: str) -> str:
    """As flags do começo do rótulo, e nada além delas.

    Consome uma sequência de marcas conhecidas a partir do início e para na
    primeira palavra que não é uma — que é o remetente, ou o assunto quando
    não há remetente. Ancorar no começo é o que separa a flag de verdade da
    mesma palavra escrita no assunto.
    """
    resto = aria_label.lstrip()
    encontradas = []
    while True:
        for flag in _ROW_FLAGS:
            if resto.startswith(flag):
                encontradas.append(flag)
                resto = resto[len(flag):].lstrip()
                break
        else:
            return " ".join(encontradas)


def _flag_zone(aria_label: str, sender_name: str) -> str:
    """O trecho do aria-label onde as flags da linha podem aparecer.

    As flags vêm antes do nome do remetente, então o nome é a melhor baliza
    — quando ele existe E aparece no rótulo. Fora disso era preciso outro
    limite, e a falta dele estragava a leitura nos dois sentidos:

    - **sem `sender_name`**, o prefixo saía vazio e "Tem anexos" nunca era
      encontrado. No banco real do usuário isso valia para 235 dos 1115
      e-mails — um quinto da caixa com o flag falso por construção;
    - **com `sender_name` ausente do rótulo**, `split` devolve o rótulo
      inteiro, e aí qualquer "Fixado" escrito no assunto virava flag.

    Sem a baliza do remetente, sobra ler as flags do começo (`_leading_flags`).
    """
    if sender_name and sender_name in aria_label:
        return aria_label.split(sender_name, 1)[0]
    return _leading_flags(aria_label)


def parse_message_row(raw: dict) -> dict:
    """Normaliza um item bruto da lista em um dicionário de mensagem.

    `raw` vem da extração em lote feita no navegador e traz, além dos
    campos do DOM, o `aria_label` da linha inteira — que é a única fonte
    de algumas informações (flags de "Fixado"/"Tem anexos" e, em itens
    fixados, a própria data).
    """
    aria_label = raw.get("aria_label") or ""
    sender_name = raw.get("sender_name") or ""

    prefix = _flag_zone(aria_label, sender_name)

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


# O Outlook anexa a contagem de itens ao rótulo de cada pasta no painel
# de navegação: "caixa real - 4.410 itens (2 não lidos)". Esse sufixo muda
# a cada e-mail que chega, então precisa sair antes de comparar nomes.
_FOLDER_COUNT_SUFFIX = re.compile(r"\s+-\s+[\d.,]+\s+ite(?:m|ns)\b.*$", re.IGNORECASE)


def clean_folder_name(raw_name: str) -> str:
    """Remove a contagem de itens do rótulo de uma pasta."""
    return _FOLDER_COUNT_SUFFIX.sub("", raw_name.strip()).strip()


def normalize_folder_name(name: str) -> str:
    """Forma canônica para comparar nomes de pasta digitados pelo usuário.

    Case-insensitive e com espaços colapsados, para que "Caixa Real" e
    "caixa  real" encontrem a pasta "caixa real".
    """
    return " ".join(name.lower().split())


def searchable_text(message: dict) -> str:
    """Junta os campos onde faz sentido procurar o código do processo.

    Hoje só o que a lista expõe (assunto e preview). Abrir a mensagem
    completa e varrer corpo e anexos é a Fase 2 completa do roadmap.
    """
    return " ".join(part for part in (message.get("subject"), message.get("preview")) if part)
