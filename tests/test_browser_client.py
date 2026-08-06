from app_facilitador import browser_client

# Casos reais capturados via scripts/browser_inbox_debug.py contra a
# caixa de entrada de produção, usados como fixture de regressão para o
# parser (ver PLANEJAMENTO.md, seção 7 — regressão com dados reais).

PINNED_ROW_ARIA_LABEL = (
    "Tem anexos Fixado Wellington Vandreis Toledo ENC: Modelos - Contratações l 666 - "
    "Sabesp - Lote 4 22/05/2026 PSC \" Assunto: Modelos - Contratações l 666 - Sabesp - "
    "Lote 4 Olá, pessoal. Seguem os modelos de contrato a serem utilizados nas "
    "contratações da obra, já atualizados e adaptados de acordo com o contrato com o "
    "cliente, contemplando o conflito no… Nenhum item selecionado"
)
PINNED_RAW = {
    "sender_name": "Wellington Vandreis Toledo",
    "sender_email": "wellington.toledo@engeform.com.br",
    "subject": "ENC: Modelos - Contratações l 666 - Sabesp - Lote 4",
    "date_title": None,
    "preview": None,
}

REGULAR_ROW_ARIA_LABEL = (
    "Tem anexos joaoevaristo generalerepresentacoes.com.br Apresentação - TE Connectivity "
    "13:04 Prezados(a), Estou com uma nova representada, a TE CONNECTIVITY, fabricante de "
    "acessórios para Cabos de Energia de Alta, Média e Baixa tensão, segue anexo "
    "apresentação. Muito obrigado pela oportunidade, e ficamos à disposição para "
    "ajudá-los nos seus…"
)
REGULAR_RAW = {
    "sender_name": "joaoevaristo generalerepresentacoes.com.br",
    "sender_email": "joaoevaristo@generalerepresentacoes.com.br",
    "subject": "Apresentação - TE Connectivity",
    "date_title": "Qui, 06/08/2026 13:04",
    "preview": (
        "Prezados(a), Estou com uma nova representada, a TE CONNECTIVITY, fabricante de "
        "acessórios para Cabos de Energia de Alta, Média e Baixa tensão, segue anexo "
        "apresentação. Muito obrigado pela oportunidade, e ficamos à disposição para "
        "ajudá-los nos seus…"
    ),
}

NO_FLAGS_ROW_ARIA_LABEL = (
    "Guilherme da Prevision CAIXA: documentos para financiamento 12:31 Some people who "
    "received this message don't often get email from marketing@prevision.com.br."
)
NO_FLAGS_RAW = {
    "sender_name": "Guilherme da Prevision",
    "sender_email": "marketing@prevision.com.br",
    "subject": "CAIXA: documentos para financiamento",
    "date_title": "Qui, 06/08/2026 12:31",
    "preview": "Some people who received this message don't often get email from marketing@prevision.com.br.",
}


def test_parse_regular_message_uses_dom_fields_directly():
    result = browser_client._parse_message_row(REGULAR_RAW, REGULAR_ROW_ARIA_LABEL)

    assert result["sender_name"] == "joaoevaristo generalerepresentacoes.com.br"
    assert result["sender_email"] == "joaoevaristo@generalerepresentacoes.com.br"
    assert result["subject"] == "Apresentação - TE Connectivity"
    assert result["received_at"] == "Qui, 06/08/2026 13:04"
    assert result["preview"].startswith("Prezados(a)")
    assert result["is_pinned"] is False
    assert result["has_attachments"] is True


def test_parse_pinned_message_falls_back_to_aria_label_for_date():
    result = browser_client._parse_message_row(PINNED_RAW, PINNED_ROW_ARIA_LABEL)

    assert result["sender_name"] == "Wellington Vandreis Toledo"
    assert result["subject"] == "ENC: Modelos - Contratações l 666 - Sabesp - Lote 4"
    assert result["received_at"] == "22/05/2026"
    assert result["preview"] is None
    assert result["is_pinned"] is True
    assert result["has_attachments"] is True


def test_parse_message_without_flags():
    result = browser_client._parse_message_row(NO_FLAGS_RAW, NO_FLAGS_ROW_ARIA_LABEL)

    assert result["is_pinned"] is False
    assert result["has_attachments"] is False
