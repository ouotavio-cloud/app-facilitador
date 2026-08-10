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


# Termos que denunciam um documento que NÃO é proposta de fornecedor:
# nota fiscal, ordem de compra, contrato, e a papelada de habilitação
# (certidões, CNPJ, Simples Nacional…). Aparecem muito nas threads de
# cotação — o fornecedor manda a proposta e, depois, nota/contrato/certidões
# —, mas o que interessa arquivar é a proposta. Casados por palavra para não
# pegar no meio de outra (ex.: "nfe" dentro de um nome qualquer).
_NAO_PROPOSTA = re.compile(
    r"\b("
    r"danfe|nota fiscal|nf-?e|boleto|fatura|"
    r"certid\w*|cnd|cnpj|simples nacional|inscri\w+ (estadual|municipal)|"
    r"cadesp|enquadramento|improbidade|feitos trabalhistas|alvar\w*|"
    r"ordem de compra|pedido de compra|purchase order"
    r")\b"
)


def is_probably_not_proposal(text: str) -> bool:
    """True quando o texto (assunto ou nome de arquivo) é claramente de um
    documento que não é proposta — nota fiscal, contrato, habilitação.

    Conservador de propósito: só termos que praticamente nunca aparecem no
    nome de uma proposta comercial, para não descartar uma proposta de
    verdade por engano.
    """
    return bool(_NAO_PROPOSTA.search(normalize_for_comparison(text or "")))


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


# Marcadores do tipo de proposta no nome do arquivo. Comercial é a que tem
# preço — o foco de quem compra. "PT"/"PC" são a convenção da empresa do
# usuário; as palavras por extenso cobrem outros fornecedores.
_MARCADORES_COMERCIAL = ["proposta comercial", "comercial", "pc"]
_MARCADORES_TECNICA = ["proposta tecnica", "tecnica", "pt"]

# Todos os marcadores de tipo, para achar onde o nome do fornecedor começa
# (a convenção é "... - PT - FORNECEDOR - R00").
_MARCADORES_TIPO = _MARCADORES_COMERCIAL + _MARCADORES_TECNICA


def _segmentos(nome_sem_extensao: str) -> list[str]:
    """Quebra o nome do arquivo nos pedaços separados por ' - ' ou '_'."""
    return [p.strip() for p in re.split(r"\s-\s|_", nome_sem_extensao) if p.strip()]


# Palavras que marcam o tipo, casadas por palavra inteira para "pt"/"pc"
# não pegarem no meio de outra palavra ("ptar", "pcte").
_RE_COMERCIAL = re.compile(r"\b(pc|comercial)\b")
_RE_TECNICA = re.compile(r"\b(pt|tecnica)\b")


def classify_proposal(filename: str) -> str | None:
    """Diz se o arquivo é a proposta "comercial", a "tecnica", ou None.

    O comprador quer a comercial (com preço); a técnica costuma vir junto e
    vira ruído. A comercial ganha do empate: se o nome indica comercial, é
    comercial, mesmo que "tecnica" também apareça.
    """
    # Separadores viram espaço para "pt"/"pc" ficarem palavras isoladas,
    # tanto em "... - PT - ..." quanto em "..._PC_...".
    texto = re.sub(r"[-_]", " ", normalize_for_comparison(Path(filename or "").stem))
    if _RE_COMERCIAL.search(texto):
        return "comercial"
    if _RE_TECNICA.search(texto):
        return "tecnica"
    return None


def supplier_from_filename(filename: str) -> str | None:
    """Nome do fornecedor tirado do próprio arquivo, se a convenção permitir.

    Vale quando um e-mail traz propostas de vários fornecedores (comum em
    e-mail interno de consolidação): o remetente é o mesmo, mas cada arquivo
    é de uma empresa. A convenção da empresa é "... - PT - FORNECEDOR - R00",
    então o fornecedor é o pedaço logo depois do marcador de tipo.

    Devolve None quando não há marcador — aí o fornecedor sai do domínio do
    e-mail, como antes.
    """
    segmentos = _segmentos(Path(filename or "").stem)
    for i, segmento in enumerate(segmentos[:-1]):
        if normalize_for_comparison(segmento) in _MARCADORES_TIPO:
            candidato = segmentos[i + 1].strip()
            # "R00", "REV01" e afins são revisão, não fornecedor.
            if re.fullmatch(r"(?i)r\d+|rev\s*\d+", candidato):
                continue
            # Precisa de nome de verdade: "2026", "08", "34072." não são
            # fornecedor. Exige ao menos três letras.
            if len(re.sub(r"[^A-Za-zÀ-ÿ]", "", candidato)) < 3:
                continue
            return sanitize(candidato, fallback="Fornecedor")
    return None


def supplier_for(
    sender_name: str | None, sender_email: str | None, filename: str | None = None
) -> str:
    """Fornecedor de um anexo: do nome do arquivo se der, senão do domínio.

    O nome do arquivo vence porque é mais específico — num e-mail com
    propostas de três fornecedores, o domínio do remetente é o mesmo para
    todos, mas o nome de cada arquivo diz de quem ele é.
    """
    if filename:
        do_arquivo = supplier_from_filename(filename)
        if do_arquivo:
            return do_arquivo
    return supplier_folder(sender_name, sender_email)


def select_proposals(
    filenames: list[str],
    sender_name: str | None,
    sender_email: str | None,
    keep_technical: bool = False,
) -> list[dict]:
    """Decide, para os anexos de um e-mail, quais baixar e de quem são.

    Cada item devolvido traz `filename`, `supplier` e `tipo`. Quando
    `keep_technical` é falso (padrão), a proposta técnica é descartada se o
    mesmo fornecedor mandou também a comercial no mesmo e-mail — o foco é a
    comercial, que tem preço. Se o fornecedor mandou só a técnica, ela é
    mantida: melhor ter a técnica que não ter nada.
    """
    itens = [
        {
            "filename": nome,
            "supplier": supplier_for(sender_name, sender_email, nome),
            "tipo": classify_proposal(nome),
        }
        for nome in filenames
    ]
    if keep_technical:
        return itens

    tem_comercial = {
        item["supplier"] for item in itens if item["tipo"] == "comercial"
    }
    return [
        item
        for item in itens
        if not (item["tipo"] == "tecnica" and item["supplier"] in tem_comercial)
    ]


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

    return _supplier_from_person(sender_name, sender_email)


def _supplier_from_person(sender_name: str | None, sender_email: str | None) -> str:
    """Fornecedor a partir da pessoa, para e-mail pessoal (gmail e afins).

    Se há um nome de verdade, é ele. Se o "nome" é o próprio endereço (ou
    está vazio), tira do trecho antes do @ a parte mais parecida com um nome
    — "vendas.angolini@..." vira "Angolini", não a pasta feia com o e-mail
    inteiro que apareceu no banco.
    """
    nome = (sender_name or "").strip()
    if nome and "@" not in nome:
        return sanitize(nome, fallback="Fornecedor")

    local = (sender_email or "").split("@")[0]
    partes = [p for p in re.split(r"[._\-]", local) if p and not p.isdigit()]
    escolha = partes[-1] if partes else local
    if escolha.islower():
        escolha = escolha.capitalize()
    return sanitize(escolha, fallback="Fornecedor")


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


def proposal_file_name(supplier: str, filename: str) -> str:
    """Nome da proposta prefixado com o fornecedor.

    O arquivo já vai numa pasta com o nome do fornecedor, mas o nome
    também precisa carregá-lo: uma proposta acaba saindo da pasta — anexada
    de volta num e-mail, jogada numa planilha de comparação, mandada para o
    engenheiro — e aí o nome sozinho tem que dizer de quem é. "Proposta.pdf"
    solto não identifica ninguém; "Aciotubos - Proposta.pdf" sim.

    Não repete o fornecedor quando o próprio arquivo já começa com ele, para
    não gerar "Aciotubos - Aciotubos proposta.pdf".
    """
    limpo = file_name_for(filename)
    caminho = Path(limpo)
    miolo, extensao = caminho.stem, caminho.suffix

    prefixo = sanitize(supplier, fallback="Fornecedor")

    # Não prefixa se o fornecedor já aparece no nome — muitas convenções
    # (a da empresa do usuário, inclusive) já embutem o fornecedor no
    # arquivo. Separadores viram espaço para o nome casar em "..._BERMAD_..."
    # e em "... - BERMAD - ...".
    miolo_norm = re.sub(r"[-_]", " ", normalize_for_comparison(miolo))
    if re.sub(r"[-_]", " ", normalize_for_comparison(prefixo)) in miolo_norm:
        return limpo

    nome = f"{prefixo} - {miolo}"
    if len(nome) > _MAX_COMPONENT:
        # Corta o miolo, nunca o fornecedor: é ele que dá sentido ao nome.
        espaco = _MAX_COMPONENT - len(prefixo) - 3  # 3 = " - "
        miolo_curto = miolo[:espaco].rstrip(". ") if espaco > 0 else ""
        nome = f"{prefixo} - {miolo_curto}".rstrip(" -") if miolo_curto else prefixo[:_MAX_COMPONENT]

    return f"{nome}{extensao}"
