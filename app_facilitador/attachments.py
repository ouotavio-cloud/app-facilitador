"""Onde cada proposta é arquivada e com que nome.

Atende os itens 1.2 e 1.3 do pedido: guardar o arquivo que o fornecedor
manda, na árvore `Obra / Processo / Fornecedor / Proposta`.

Módulo puro, sem navegador e sem disco além do estritamente necessário —
a parte difícil aqui é decidir nomes, não baixar arquivos, e decidir
nomes é o que dá para testar de verdade.
"""

import re
import unicodedata
from pathlib import Path

# Extensões que valem como proposta. É uma lista de permissão, e não de
# bloqueio, por causa das imagens: quase todo e-mail corporativo traz
# logotipo e assinatura em .png ou .jpg, e baixá-los encheria as pastas
# de lixo que ninguém pediu. Uma proposta é um documento.
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc", ".docx", ".odt", ".rtf",
    ".xls", ".xlsx", ".xlsm", ".ods", ".csv",
    ".ppt", ".pptx",
    ".zip", ".rar", ".7z",
    ".dwg", ".dxf",
    ".txt",
}

# Domínios de e-mail pessoal: não identificam empresa nenhuma, então para
# eles o nome do remetente é a melhor pista de quem é o fornecedor.
_GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "yahoo.com", "yahoo.com.br", "terra.com.br", "uol.com.br", "bol.com.br",
    "ig.com.br", "globo.com", "icloud.com", "me.com", "protonmail.com",
}

# Caracteres proibidos em nomes de arquivo e pasta no Windows.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Nomes que o Windows reserva para dispositivos: uma pasta chamada "CON"
# simplesmente não pode ser criada.
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Limite por componente do caminho. O Windows tem um teto de 260
# caracteres para o caminho inteiro, e a árvore aqui tem quatro níveis.
_MAX_COMPONENT = 60

_SEM_OBRA = "Sem obra"


def is_document(filename: str) -> bool:
    """True se o arquivo parece uma proposta, e não enfeite de e-mail."""
    if not filename:
        return False
    return Path(filename).suffix.lower() in DOCUMENT_EXTENSIONS


def sanitize(name: str, fallback: str = "sem-nome") -> str:
    """Transforma um texto qualquer num nome de pasta ou arquivo válido.

    Nomes vêm de assunto de e-mail e de nome de fornecedor, que contêm de
    tudo — barras, dois-pontos, aspas. Um caminho inválido faria o
    download falhar no fim de tudo, depois do trabalho já feito.
    """
    limpo = _ILLEGAL_CHARS.sub("-", name or "").strip()
    # O Windows não guarda nomes terminados em ponto ou espaço: ele os
    # remove em silêncio, e o caminho gravado deixa de bater com o
    # esperado.
    limpo = limpo.rstrip(". ")
    limpo = " ".join(limpo.split())

    # Um nome que virou só traços ("///" → "---") não identifica nada.
    # Exigir ao menos uma letra ou número evita pastas indecifráveis.
    if not any(c.isalnum() for c in limpo):
        return fallback

    if limpo.upper() in _RESERVED_NAMES:
        limpo = f"{limpo}-"

    if len(limpo) > _MAX_COMPONENT:
        limpo = limpo[:_MAX_COMPONENT].rstrip(". ")

    return limpo or fallback


def supplier_folder(sender_name: str | None, sender_email: str | None) -> str:
    """Nome da pasta do fornecedor, a partir do remetente do e-mail.

    Usa o domínio, não o nome da pessoa: quem manda a proposta é "Marcos
    Ribeiro", mas o fornecedor é a Aciotubos, e no mês seguinte pode ser
    a Fernanda quem responde pela mesma empresa. Agrupar por domínio
    mantém as propostas do mesmo fornecedor juntas.

    Em e-mail pessoal (gmail e afins) o domínio não diz nada, e aí o nome
    do remetente é a única pista de quem é o fornecedor.
    """
    dominio = _domain_of(sender_email)

    if dominio and dominio not in _GENERIC_EMAIL_DOMAINS:
        return sanitize(_company_from_domain(dominio), fallback="Fornecedor")

    return sanitize(sender_name or dominio or "", fallback="Fornecedor")


def _domain_of(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    dominio = email.rsplit("@", 1)[1].strip().lower()
    return dominio or None


def _company_from_domain(dominio: str) -> str:
    """"comercial.aciotubos.com.br" -> "Aciotubos".

    Descarta os sufixos de país e de tipo (com, br, ind, net) e fica com
    a parte que nomeia a empresa.
    """
    descartaveis = {"com", "br", "net", "org", "gov", "ind", "eng", "co", "www"}
    partes = [p for p in dominio.split(".") if p and p not in descartaveis]
    if not partes:
        return dominio

    # A última parte que sobra é a mais próxima do nome da empresa:
    # em "comercial.aciotubos.com.br" sobra ["comercial", "aciotubos"].
    nome = partes[-1]
    return nome.capitalize() if nome.islower() else nome


def normalize_for_comparison(text: str) -> str:
    """Versão sem acento e em minúsculas, para comparar pastas existentes."""
    sem_acento = unicodedata.normalize("NFKD", text or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def proposal_dir(base: Path, obra: str | None, code: str, supplier: str) -> Path:
    """A pasta `Obra / Processo / Fornecedor` onde a proposta será guardada.

    Sem obra cadastrada o processo ainda precisa de um lugar: uma pasta
    "Sem obra" mantém o arquivo achável em vez de descartá-lo ou de
    espalhar processos soltos na raiz.
    """
    return (
        base
        / sanitize(obra or _SEM_OBRA, fallback=_SEM_OBRA)
        / sanitize(code, fallback="Sem processo")
        / sanitize(supplier, fallback="Fornecedor")
    )


def unique_path(destino: Path) -> Path:
    """Caminho livre para gravar, sem nunca sobrescrever o que já existe.

    Proposta revisada não substitui a anterior: comparar a versão nova com
    a antiga é parte do trabalho de quem cota, e um arquivo sobrescrito
    não volta. A revisão vira "Proposta (2).pdf" ao lado da original.
    """
    if not destino.exists():
        return destino

    raiz, extensao = destino.stem, destino.suffix
    for versao in range(2, 1000):
        candidato = destino.with_name(f"{raiz} ({versao}){extensao}")
        if not candidato.exists():
            return candidato

    raise RuntimeError(f"Já existem 999 versões de {destino.name}.")


def file_name_for(filename: str) -> str:
    """Nome final do arquivo, preservando a extensão original.

    A extensão é sagrada — é o que faz o Windows abrir o PDF no leitor
    certo —, então ela é separada antes da limpeza e recolada depois.
    """
    bruto = (filename or "").strip()

    # ".pdf" é um caso à parte: o Python o lê como arquivo oculto sem
    # extensão, e o resultado seria um arquivo chamado ".pdf" que o
    # Windows esconde do usuário. Aqui o ponto inicial marca a extensão.
    if bruto.startswith(".") and bruto.count(".") == 1:
        return f"proposta{bruto}"

    caminho = Path(bruto)
    return f"{sanitize(caminho.stem, fallback='proposta')}{caminho.suffix}"
