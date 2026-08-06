from datetime import datetime

import pytest

from app_facilitador import storage


@pytest.fixture
def connection(tmp_path):
    with storage.connect(tmp_path / "test.db") as conn:
        yield conn


def _message(conv_id: str = "conv-1", **overrides) -> dict:
    message = {
        "conv_id": conv_id,
        "sender_name": "Fornecedor Exemplo",
        "sender_email": "vendas@exemplo.com.br",
        "subject": "Proposta SUP.2026-197",
        "received_at": datetime(2026, 8, 6, 13, 4),
        "received_at_raw": "Qui, 06/08/2026 13:04",
        "preview": "Segue nossa proposta em anexo",
        "is_pinned": False,
        "has_attachments": True,
    }
    return {**message, **overrides}


def test_save_message_reports_new_message(connection):
    assert storage.save_message(connection, _message(), ["SUP.2026-197"]) is True
    assert storage.count_messages(connection) == 1


def test_save_message_is_idempotent(connection):
    storage.save_message(connection, _message(), ["SUP.2026-197"])

    assert storage.save_message(connection, _message(), ["SUP.2026-197"]) is False
    assert storage.count_messages(connection) == 1


def test_save_message_without_codes(connection):
    storage.save_message(connection, _message(), [])

    assert storage.count_messages(connection) == 1
    assert storage.list_messages_with_codes(connection) == []


def test_list_messages_with_codes_returns_only_matches(connection):
    storage.save_message(connection, _message("conv-1"), ["SUP.2026-197"])
    storage.save_message(connection, _message("conv-2", subject="Boletim"), [])

    matches = storage.list_messages_with_codes(connection)

    assert len(matches) == 1
    assert matches[0]["conv_id"] == "conv-1"
    assert matches[0]["codes"] == ["SUP.2026-197"]


def test_list_messages_with_codes_groups_multiple_codes(connection):
    storage.save_message(connection, _message(), ["SUP.2026-197", "SUP.2026-198"])

    matches = storage.list_messages_with_codes(connection)

    assert sorted(matches[0]["codes"]) == ["SUP.2026-197", "SUP.2026-198"]


def test_message_without_parsed_date_is_still_saved(connection):
    storage.save_message(connection, _message(received_at=None, received_at_raw="ontem"), [])

    assert storage.count_messages(connection) == 1
