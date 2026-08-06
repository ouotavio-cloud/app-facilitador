"""Configuração de autenticação com a Microsoft Graph API.

Não usamos um App Registration próprio: o tenant do usuário bloqueia
usuários comuns de criar registros no Azure AD (ver PLANEJAMENTO.md,
seção 2). Em vez disso, usamos o client_id público do "Microsoft Graph
Command Line Tools", um app oficial da Microsoft presente em qualquer
tenant, que só exige consentimento comum do próprio usuário.
"""

from pathlib import Path

CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read", "Calendars.Read"]

BASE_DIR = Path(__file__).resolve().parent.parent
TOKEN_CACHE_PATH = BASE_DIR / ".token_cache.bin"

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Automação do Outlook Web (usada quando a Graph API está bloqueada por
# política de TI e não há cache local legível do novo Outlook).
OWA_URL = "https://outlook.office.com/mail/"
BROWSER_STATE_PATH = BASE_DIR / ".browser_state.json"

# Padrões de regex para o código do processo de cotação (ex.: SUP.2026-197).
# Lista configurável (ver PLANEJAMENTO.md, seção 3) em vez de um formato
# fixo, pois a formatação varia conforme o fornecedor cita o código na
# resposta (com/sem ponto, com/sem hífen, com/sem espaço).
PROPOSAL_CODE_PATTERNS = [
    r"SUP\.?\s*(?P<year>\d{4})\s*-?\s*(?P<seq>\d{3})",
]
