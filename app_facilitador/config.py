"""Configuração de autenticação com a Microsoft Graph API.

Não usamos um App Registration próprio: o tenant do usuário bloqueia
usuários comuns de criar registros no Azure AD (ver PLANEJAMENTO.md,
seção 2). Em vez disso, usamos o client_id público do "Microsoft Graph
Command Line Tools", um app oficial da Microsoft presente em qualquer
tenant, que só exige consentimento comum do próprio usuário.
"""

from pathlib import Path

from app_facilitador import paths

CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read", "Calendars.Read"]

# Tudo que o app grava vai para a pasta de dados do usuário — que, no
# executável, é diferente da pasta do programa (ver app_facilitador/paths.py).
BASE_DIR = paths.data_dir()
TOKEN_CACHE_PATH = BASE_DIR / ".token_cache.bin"

# Banco de estado local: mensagens já processadas e códigos de processo
# encontrados. Arquivo único, sem servidor (ver PLANEJAMENTO.md, seção 4).
DB_PATH = BASE_DIR / "app_facilitador.db"

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Onde as propostas baixadas são arquivadas, na árvore
# `Obra / Processo / Fornecedor / arquivo`.
#
# Em Documentos, e não na pasta escondida de dados do app: são arquivos de
# trabalho, que o usuário vai abrir, anexar em e-mail e mostrar para
# outras pessoas. Em máquina corporativa a pasta Documentos costuma estar
# sincronizada com o OneDrive, então o time enxerga junto sem configurar
# nada. O caminho é editável no painel — este é só o palpite inicial.
DEFAULT_PROPOSALS_DIR = Path.home() / "Documents" / "App Facilitador" / "Propostas"

# Chave da preferência que guarda a escolha do usuário (tabela settings).
PROPOSALS_DIR_SETTING = "pasta_propostas"

# Automação do Outlook Web (usada quando a Graph API está bloqueada por
# política de TI e não há cache local legível do novo Outlook).
OWA_URL = "https://outlook.office.com/mail/"
OWA_CALENDAR_URL = "https://outlook.office.com/calendar/view/day"

# Perfil do navegador, guardado como o de um navegador comum.
#
# Antes salvávamos só um `storage_state.json` (cookies e localStorage), e
# a conta parava de valer depois de pouco tempo: o login da Microsoft
# guarda parte do que precisa em IndexedDB, que aquele arquivo não
# captura. Um perfil de verdade preserva tudo, e a sessão dura o mesmo
# que duraria num navegador normal.
BROWSER_PROFILE_DIR = BASE_DIR / "navegador"

# Marca que o login já foi feito. É um arquivo separado do perfil porque
# a pasta do perfil passa a existir assim que o navegador abre uma vez,
# mesmo que ninguém tenha logado.
LOGIN_MARKER_PATH = BASE_DIR / ".conectado"

# Reuniões lidas do calendário, guardadas para o painel abrir sem esperar
# um navegador subir a cada carregamento da página.
MEETINGS_CACHE_PATH = BASE_DIR / ".meetings_cache.json"

# Padrões de regex para o código do processo de cotação (ex.: SUP.2026-197).
# Lista configurável (ver PLANEJAMENTO.md, seção 3) em vez de um formato
# fixo, pois a formatação varia conforme o fornecedor cita o código na
# resposta (com/sem ponto, com/sem hífen, com/sem espaço).
PROPOSAL_CODE_PATTERNS = [
    r"SUP\.?\s*(?P<year>\d{4})\s*-?\s*(?P<seq>\d{3})",
]
