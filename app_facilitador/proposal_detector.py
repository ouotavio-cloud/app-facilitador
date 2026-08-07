"""Detecção do código de processo de cotação (ex.: `SUP.2026-197`) em texto livre.

O padrão de código pode variar na formatação usada pelo fornecedor ao
responder (com/sem ponto, com/sem espaço, com/sem hífen), então os padrões
são regex configuráveis (ver PLANEJAMENTO.md, seção 3) em vez de um único
formato fixo no código.
"""

import re
import unicodedata

from app_facilitador import config

# Nomes de obra muito curtos casariam com qualquer coisa ("SP" aparece em
# qualquer texto). Abaixo deste tamanho, o nome da obra é ignorado como
# pista e só o código vale.
_MIN_OBRA_LENGTH = 4


def find_proposal_codes(text: str, patterns: list[str] | None = None) -> list[str]:
    """Retorna os códigos de processo encontrados em `text`, sem duplicatas.

    Cada código é normalizado para o formato canônico `SUP.AAAA-NNN`,
    independentemente de como apareceu no texto original.
    """
    patterns = patterns if patterns is not None else config.PROPOSAL_CODE_PATTERNS

    codes = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            code = f"SUP.{match.group('year')}-{match.group('seq')}"
            if code not in codes:
                codes.append(code)
    return codes


def contains_proposal_code(text: str, patterns: list[str] | None = None) -> bool:
    """Atalho para saber se `text` cita algum código de processo."""
    return bool(find_proposal_codes(text, patterns))


def _normalize(text: str) -> str:
    """Minúsculas e sem acentos, para comparar nomes de obra com tolerância.

    O nome da obra é digitado por pessoas diferentes em contextos
    diferentes — "Itaim" e "ITAIM", "Sabesp" e "SABESP" devem casar.
    """
    without_accents = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in without_accents if not unicodedata.combining(c))
    return " ".join(without_accents.lower().split())


def match_known_processes(text: str, processes: list[dict]) -> list[dict]:
    """Casa o texto contra os processos que o usuário cadastrou.

    Cada processo é procurado de duas formas — pelo código e pelo nome da
    obra — porque uma reforça a outra: quando o fornecedor escreve o
    código de um jeito inesperado, o nome da obra no assunto ainda
    identifica o processo, e vice-versa.

    Devolve, para cada processo encontrado, o código e por qual pista ele
    foi identificado, para que o usuário possa julgar a confiança de cada
    resultado em vez de receber um "encontrado" opaco.
    """
    codes_in_text = set(find_proposal_codes(text))
    normalized_text = _normalize(text)

    matches = []
    for process in processes:
        matched_by = []

        if process["code"] in codes_in_text:
            matched_by.append("código")

        obra = (process.get("obra") or "").strip()
        if len(obra) >= _MIN_OBRA_LENGTH and _normalize(obra) in normalized_text:
            matched_by.append("obra")

        if matched_by:
            matches.append({"code": process["code"], "matched_by": matched_by})

    return matches


def find_unknown_codes(text: str, processes: list[dict]) -> list[str]:
    """Códigos que aparecem no texto mas não estão cadastrados.

    Serve para não perder de vista uma cotação que o usuário esqueceu de
    cadastrar: em vez de sumir do relatório, ela aparece como pendência.
    """
    known = {process["code"] for process in processes}
    return [code for code in find_proposal_codes(text) if code not in known]
