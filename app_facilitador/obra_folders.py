"""Localiza, dentro da árvore de obras já existente no OneDrive, a pasta
onde uma proposta deve ser arquivada.

O usuário já mantém uma estrutura própria por obra — criada manualmente,
muito antes deste app existir:

    __14. OBRAS / <NN.NNN - NNN NOME DA OBRA> / 04. RFQs /
        <SUP.AAAA-NNN - ASSUNTO> / 3. PROPOSTAS TÉCNICA E COMERCIAL /
            <FORNECEDOR> / arquivo

Quando essa raiz está configurada (`config.OBRAS_DIR_SETTING`), a proposta
é arquivada ali, e não na árvore própria do app (`Obra/Processo/Fornecedor`
sob `pasta_propostas`, ver `attachments.proposal_dir`). Sem a raiz
configurada, ou sem achar a obra ou o RFQ dentro dela, quem chama volta
para essa árvore própria — o app nunca inventa pasta de obra ou de RFQ na
estrutura da empresa, só a de fornecedor (que já nasce vazia em todo RFQ,
esperando quem responder ao convite).
"""

import re
from pathlib import Path

from app_facilitador.attachments import normalize_for_comparison, sanitize

# Palavras que identificam as pastas fixas da árvore, casadas por
# substring normalizada (sem acento/maiúscula) em vez de texto exato: o
# número que prefixa cada uma ("04.", "3.") é o tipo de detalhe que varia
# de obra para obra ou muda numa reorganização manual de pastas.
_RFQS_KEYWORDS = ("rfq",)
_PROPOSTAS_KEYWORDS = ("proposta", "tecnica", "comercial")

# Nome usado só quando a pasta de propostas ainda não existe dentro do RFQ
# (RFQ criado à mão, sem a subpasta de propostas montada ainda).
_PROPOSTAS_FALLBACK_NAME = "3. PROPOSTAS TÉCNICA E COMERCIAL"


def _find_child_by_keywords(parent: Path, keywords: tuple[str, ...]) -> Path | None:
    """Subpasta de `parent` cujo nome contém todas as `keywords`."""
    if not parent.is_dir():
        return None
    for item in sorted(parent.iterdir()):
        if item.is_dir() and all(
            chave in normalize_for_comparison(item.name) for chave in keywords
        ):
            return item
    return None


def find_obra_dir(base: Path, numero_obra: str) -> Path | None:
    """Pasta da obra dentro de `base`, achada pelo número que a identifica.

    O número (ex. "659") aparece no meio do nome da pasta
    ("25.001 - 659 ETA ITABIRA") ao lado de outros números que não são
    ele — o registro sequencial da pasta ("25.001"). As bordas excluem
    dígito **e** ponto, para "659" não casar dentro de "6590" nem do
    "25.659" de um registro sequencial que termine com os mesmos dígitos.
    """
    numero = (numero_obra or "").strip()
    if not numero or not base.is_dir():
        return None

    padrao = re.compile(rf"(?<![\w.]){re.escape(numero)}(?![\w.])")
    for item in sorted(base.iterdir()):
        if item.is_dir() and padrao.search(item.name):
            return item
    return None


def find_rfq_dir(obra_dir: Path, codigo: str) -> Path | None:
    """Pasta do RFQ (ex. "SUP.2026-049 - CABOS") dentro de "04. RFQs".

    O nome da pasta começa com o código e segue com o que o usuário
    quiser (o assunto da cotação) — daí conferir só o começo.
    """
    rfqs_dir = _find_child_by_keywords(obra_dir, _RFQS_KEYWORDS)
    if rfqs_dir is None:
        return None

    alvo = normalize_for_comparison(codigo)
    for item in sorted(rfqs_dir.iterdir()):
        if item.is_dir() and normalize_for_comparison(item.name).startswith(alvo):
            return item
    return None


def find_supplier_dir(rfq_dir: Path, fornecedor: str) -> Path:
    """Pasta do fornecedor dentro de "3. PROPOSTAS TÉCNICA E COMERCIAL".

    Os fornecedores convidados já têm pasta própria, criada à mão ao
    montar o convite (CABELAUTO, COPERCABOS...). Usar a pasta existente
    evita duplicar "Cabelauto" ao lado de "CABELAUTO" só por causa da
    caixa; sem pasta existente (fornecedor que respondeu sem ser
    convidado), o nome sai da mesma sanitização usada na árvore própria
    do app.
    """
    propostas_dir = _find_child_by_keywords(rfq_dir, _PROPOSTAS_KEYWORDS)
    if propostas_dir is None:
        propostas_dir = rfq_dir / _PROPOSTAS_FALLBACK_NAME

    alvo = normalize_for_comparison(fornecedor)
    if propostas_dir.is_dir():
        for item in sorted(propostas_dir.iterdir()):
            if item.is_dir() and normalize_for_comparison(item.name) == alvo:
                return item

    return propostas_dir / sanitize(fornecedor, fallback="Fornecedor")


def resolve_destination(
    base: Path | None, numero_obra: str | None, codigo: str, fornecedor: str
) -> Path | None:
    """Pasta do fornecedor na árvore real do OneDrive, ou None se não achar.

    None cobre os dois motivos de não ter para onde ir: a pasta raiz não
    está configurada, ou a obra/o RFQ não existe dentro dela (processo
    cadastrado com o número errado, ou pasta do RFQ ainda não criada pelo
    time). Quem chama trata None caindo para a árvore própria do app.
    """
    if base is None or not numero_obra:
        return None

    obra_dir = find_obra_dir(base, numero_obra)
    if obra_dir is None:
        return None

    rfq_dir = find_rfq_dir(obra_dir, codigo)
    if rfq_dir is None:
        return None

    return find_supplier_dir(rfq_dir, fornecedor)
