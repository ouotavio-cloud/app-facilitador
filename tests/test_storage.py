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


def test_add_and_list_processes(connection):
    storage.add_process(connection, "SUP.2026-197", "Sabesp Lote 4")
    storage.add_process(connection, "SUP.2026-198", None)

    processes = storage.list_processes(connection)

    assert [p["code"] for p in processes] == ["SUP.2026-197", "SUP.2026-198"]
    assert processes[0]["obra"] == "Sabesp Lote 4"
    assert processes[1]["obra"] is None


def test_readding_process_updates_the_obra(connection):
    """Permite corrigir um cadastro sem apagar e recriar."""
    storage.add_process(connection, "SUP.2026-197", "nome errado")
    storage.add_process(connection, "SUP.2026-197", "Sabesp Lote 4")

    processes = storage.list_processes(connection)

    assert len(processes) == 1
    assert processes[0]["obra"] == "Sabesp Lote 4"


def test_remove_process(connection):
    storage.add_process(connection, "SUP.2026-197", "Sabesp Lote 4")

    assert storage.remove_process(connection, "SUP.2026-197") is True
    assert storage.list_processes(connection) == []


def test_remove_unknown_process_reports_false(connection):
    assert storage.remove_process(connection, "SUP.2026-999") is False


def test_matched_by_is_persisted(connection):
    storage.save_message(
        connection,
        _message(),
        ["SUP.2026-197"],
        matched_by={"SUP.2026-197": "código, obra"},
    )

    match = storage.list_messages_with_codes(connection)[0]

    assert match["matched_by"] == ["código, obra"]


def test_multiple_codes_stay_aligned_with_their_clues(connection):
    """As pistas contêm vírgula, então agrupá-las por vírgula desalinharia tudo."""
    storage.save_message(
        connection,
        _message(),
        ["SUP.2026-197", "SUP.2026-198"],
        matched_by={"SUP.2026-197": "código, obra", "SUP.2026-198": "obra"},
    )

    match = storage.list_messages_with_codes(connection)[0]

    assert dict(zip(match["codes"], match["matched_by"])) == {
        "SUP.2026-197": "código, obra",
        "SUP.2026-198": "obra",
    }


def test_code_without_matched_by_is_labelled_as_unregistered(connection):
    storage.save_message(connection, _message(), ["SUP.2026-888"])

    match = storage.list_messages_with_codes(connection)[0]

    assert match["matched_by"] == ["não cadastrado"]


def test_message_without_parsed_date_is_still_saved(connection):
    storage.save_message(connection, _message(received_at=None, received_at_raw="ontem"), [])

    assert storage.count_messages(connection) == 1


def _registra_anexo(connection, conv_id, path, error=None):
    storage.save_message(connection, _message(conv_id=conv_id), [])
    storage.record_attachment(
        connection,
        conv_id=conv_id,
        filename="Proposta.pdf",
        path=str(path) if path else None,
        code="SUP.2026-197",
        supplier="Aciotubos",
        error=error,
    )


def test_downloaded_on_disk_counts_only_files_that_still_exist(connection, tmp_path):
    """A conversa só conta como baixada se o arquivo continua na pasta."""
    presente = tmp_path / "presente.pdf"
    presente.write_text("x", encoding="utf-8")
    _registra_anexo(connection, "conv-presente", presente)

    ausente = tmp_path / "apagado.pdf"  # nunca criado: simula arquivo apagado
    _registra_anexo(connection, "conv-apagado", ausente)

    na_pasta = storage.downloaded_conversations_on_disk(connection)

    assert "conv-presente" in na_pasta
    assert "conv-apagado" not in na_pasta


def test_downloaded_on_disk_ignores_failed_downloads(connection, tmp_path):
    _registra_anexo(connection, "conv-falha", None, error="não deu")

    assert storage.downloaded_conversations_on_disk(connection) == set()
