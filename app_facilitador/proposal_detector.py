"""Detecção do código de processo de cotação (ex.: `SUP.2026-197`) em texto livre.

O padrão de código pode variar na formatação usada pelo fornecedor ao
responder (com/sem ponto, com/sem espaço, com/sem hífen), então os padrões
são regex configuráveis (ver PLANEJAMENTO.md, seção 3) em vez de um único
formato fixo no código.
"""

import re

from app_facilitador import config


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
