from datetime import datetime

import pytest

from app_facilitador import inbox_parser

# Casos reais capturados via scripts/browser_inbox_debug.py contra a caixa
# de entrada de produção, usados como fixture de regressão para o parser
# (ver PLANEJAMENTO.md, seção 7).

PINNED_ITEM = {
    "conv_id": "AAQkAGIwNWUzNWI2LQAQACsOqXMIaUpzijJ1dU8XkXc=",
    "aria_label": (
        "Tem anexos Fixado Wellington Vandreis Toledo ENC: Modelos - Contratações l 666 - "
        "Sabesp - Lote 4 22/05/2026 PSC \" Assunto: Modelos - Contratações l 666 - Sabesp - "
        "Lote 4 Olá, pessoal. Seguem os modelos de contrato… Nenhum item selecionado"
    ),
    "sender_name": "Wellington Vandreis Toledo",
    "sender_email": "wellington.toledo@engeform.com.br",
    "subject": "ENC: Modelos - Contratações l 666 - Sabesp - Lote 4",
    "date_title": None,
    "preview": None,
}

REGULAR_ITEM = {
    "conv_id": "AAQkAGIwNWUzNWI2LQAQADhBdYc2zUbYp6lXB5DPpI0=",
    "aria_label": (
        "Tem anexos joaoevaristo generalerepresentacoes.com.br Apresentação - TE "
        "Connectivity 13:04 Prezados(a), Estou com uma nova representada…"
    ),
    "sender_name": "joaoevaristo generalerepresentacoes.com.br",
    "sender_email": "joaoevaristo@generalerepresentacoes.com.br",
    "subject": "Apresentação - TE Connectivity",
    "date_title": "Qui, 06/08/2026 13:04",
    "preview": "Prezados(a), Estou com uma nova representada, a TE CONNECTIVITY…",
}

NO_FLAGS_ITEM = {
    "conv_id": "AAQkAGIwNWUzNWI2LQAQAPe6A7RaTk1CihSarerqeUg=",
    "aria_label": (
        "Guilherme da Prevision CAIXA: documentos para financiamento 12:31 Some people "
        "who received this message don't often get email from marketing@prevision.com.br."
    ),
    "sender_name": "Guilherme da Prevision",
    "sender_email": "marketing@prevision.com.br",
    "subject": "CAIXA: documentos para financiamento",
    "date_title": "Qui, 06/08/2026 12:31",
    "preview": "Some people who received this message don't often get email…",
}


def test_parse_regular_item_uses_dom_fields():
    result = inbox_parser.parse_message_row(REGULAR_ITEM)

    assert result["sender_name"] == "joaoevaristo generalerepresentacoes.com.br"
    assert result["sender_email"] == "joaoevaristo@generalerepresentacoes.com.br"
    assert result["subject"] == "Apresentação - TE Connectivity"
    assert result["received_at"] == datetime(2026, 8, 6, 13, 4)
    assert result["is_pinned"] is False
    assert result["has_attachments"] is True


def test_parse_pinned_item_falls_back_to_aria_label_for_date():
    result = inbox_parser.parse_message_row(PINNED_ITEM)

    assert result["received_at"] == datetime(2026, 5, 22)
    assert result["preview"] is None
    assert result["is_pinned"] is True
    assert result["has_attachments"] is True


def test_parse_item_without_flags():
    result = inbox_parser.parse_message_row(NO_FLAGS_ITEM)

    assert result["is_pinned"] is False
    assert result["has_attachments"] is False


def test_flags_are_not_matched_in_subject_or_preview():
    """As flags só valem antes do remetente — o assunto pode citar as mesmas palavras."""
    item = {
        "conv_id": "x",
        "aria_label": "Fulano de Tal Fixado o preço, tem anexos na próxima 01/01/2026",
        "sender_name": "Fulano de Tal",
        "sender_email": "fulano@example.com",
        "subject": "Fixado o preço, tem anexos na próxima",
        "date_title": "Qui, 01/01/2026 08:00",
        "preview": None,
    }

    result = inbox_parser.parse_message_row(item)

    assert result["is_pinned"] is False
    assert result["has_attachments"] is False


def test_flags_are_read_even_without_a_sender_name():
    """Sem remetente extraído, o flag era falso por construção.

    O prefixo saía vazio (`if sender_name else ""`) e "Tem anexos" nunca
    era encontrado. No banco real do usuário isso valia para 235 dos 1115
    e-mails — e o scanner usava esse flag para decidir o que abrir.
    """
    item = {
        "conv_id": "x",
        "aria_label": "Tem anexos RES: SUP.2026-185 | CARTA CONVITE | 661-TAIAÇUPEBA",
        "sender_name": None,
        "sender_email": None,
        "subject": "RES: SUP.2026-185 | CARTA CONVITE | 661-TAIAÇUPEBA",
        "date_title": "Ter, 28/07/2026 18:17",
        "preview": None,
    }

    result = inbox_parser.parse_message_row(item)

    assert result["has_attachments"] is True


def test_flags_are_not_matched_when_the_sender_is_absent_from_the_label():
    """`split` num nome que não está no rótulo devolve o rótulo INTEIRO.

    O outro lado do mesmo defeito: em vez de nunca achar a flag, passava a
    achá-la em qualquer lugar — inclusive no assunto.
    """
    item = {
        "conv_id": "x",
        "aria_label": "Outro Remetente Assunto citando Fixado e tem anexos no fim",
        "sender_name": "Nome Que Não Está No Rótulo",
        "sender_email": "fulano@example.com",
        "subject": "Assunto citando Fixado e tem anexos no fim",
        "date_title": "Qui, 01/01/2026 08:00",
        "preview": None,
    }

    result = inbox_parser.parse_message_row(item)

    assert result["is_pinned"] is False
    assert result["has_attachments"] is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Qui, 06/08/2026 13:04", datetime(2026, 8, 6, 13, 4)),
        ("22/05/2026", datetime(2026, 5, 22)),
        ("", None),
        (None, None),
        ("ontem", None),
    ],
)
def test_parse_received_at(raw, expected):
    assert inbox_parser.parse_received_at(raw) == expected


def test_searchable_text_joins_subject_and_preview():
    message = {"subject": "Proposta SUP.2026-197", "preview": "segue anexo"}

    assert inbox_parser.searchable_text(message) == "Proposta SUP.2026-197 segue anexo"


def test_searchable_text_skips_missing_fields():
    message = {"subject": "Proposta SUP.2026-197", "preview": None}

    assert inbox_parser.searchable_text(message) == "Proposta SUP.2026-197"
