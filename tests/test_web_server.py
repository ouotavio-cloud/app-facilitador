"""Testes do painel: as páginas respondem e os dados chegam à tela.

Não sobem navegador — usam o cliente de teste do Flask contra um banco
temporário.
"""

from datetime import date, timedelta

import pytest

from app_facilitador import config, storage
from app_facilitador.web import server


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "MEETINGS_CACHE_PATH", tmp_path / "meetings.json")
    monkeypatch.setattr(config, "BROWSER_STATE_PATH", tmp_path / "state.json")

    app = server.create_app()
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def _page(client) -> str:
    response = client.get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_index_loads_on_an_empty_database(client):
    """Primeira execução: nada cadastrado, nada varrido."""
    assert "App Facilitador" in _page(client)


def test_index_warns_when_login_was_never_done(client):
    """Sem sessão salva a varredura não funciona — o app precisa dizer isso."""
    assert "Login pendente" in _page(client)


def test_add_process_appears_on_the_page(client):
    client.post("/processos", data={"codigo": "SUP.2026-197", "obra": "Sabesp Lote 4"})

    page = _page(client)

    assert "SUP.2026-197" in page
    assert "Sabesp Lote 4" in page


def test_add_process_normalizes_a_loosely_typed_code(client):
    """O cadastro precisa virar o mesmo formato que a busca produz."""
    client.post("/processos", data={"codigo": "sup 2026 197", "obra": ""})

    assert "SUP.2026-197" in _page(client)


def test_add_process_ignores_unrecognizable_code(client):
    client.post("/processos", data={"codigo": "não é um código", "obra": "Obra X"})

    assert "Obra X" not in _page(client)


def test_deadline_shows_as_overdue(client):
    yesterday = (date.today() - timedelta(days=1)).strftime("%d/%m/%Y")

    client.post(
        "/processos",
        data={"codigo": "SUP.2026-197", "obra": "Atrasada", "prazo": yesterday},
    )

    page = _page(client)
    assert "Vencido" in page
    assert "venceu há 1 dia" in page


def test_deadline_shows_days_remaining(client):
    in_ten_days = (date.today() + timedelta(days=10)).strftime("%d/%m/%Y")

    client.post(
        "/processos",
        data={"codigo": "SUP.2026-198", "obra": "Tranquila", "prazo": in_ten_days},
    )

    page = _page(client)
    assert "No prazo" in page
    assert "faltam 10 dias" in page


def test_process_without_deadline_is_marked_as_such(client):
    client.post("/processos", data={"codigo": "SUP.2026-199", "obra": "Sem prazo"})

    assert "Sem prazo definido" in _page(client)


def test_remove_process(client):
    client.post("/processos", data={"codigo": "SUP.2026-197", "obra": "Some daqui"})

    client.post("/processos/SUP.2026-197/remover")

    assert "Some daqui" not in _page(client)


def test_recent_messages_are_listed(client):
    with storage.connect(config.DB_PATH) as connection:
        storage.save_message(
            connection,
            {
                "conv_id": "conv-1",
                "sender_name": "Fornecedor Exemplo",
                "sender_email": "vendas@exemplo.com.br",
                "subject": "Proposta para a obra",
                "received_at": None,
                "received_at_raw": "Qui, 06/08/2026 13:04",
                "preview": "segue anexo",
                "is_pinned": False,
                "has_attachments": True,
            },
            [],
            folder="caixa real",
        )

    page = _page(client)
    assert "Fornecedor Exemplo" in page
    assert "Proposta para a obra" in page


def test_identified_proposal_shows_which_clue_matched(client):
    """Saber se veio pelo código ou pela obra muda a confiança no resultado."""
    with storage.connect(config.DB_PATH) as connection:
        storage.add_process(connection, "SUP.2026-197", "Sabesp Lote 4")
        storage.save_message(
            connection,
            {
                "conv_id": "conv-2",
                "sender_name": "Fornecedor",
                "sender_email": "f@exemplo.com",
                "subject": "Proposta SUP.2026-197",
                "received_at": None,
                "received_at_raw": "06/08/2026",
                "preview": None,
                "is_pinned": False,
                "has_attachments": True,
            },
            ["SUP.2026-197"],
            matched_by={"SUP.2026-197": "código, obra"},
            folder="Caixa de Entrada",
        )

    page = _page(client)
    assert "código, obra" in page


def test_unregistered_code_is_flagged_not_shown_as_identified(client):
    """Um código que apareceu mas não é acompanhado não pode passar por resultado."""
    with storage.connect(config.DB_PATH) as connection:
        storage.save_message(
            connection,
            {
                "conv_id": "conv-3",
                "sender_name": "Documentação",
                "sender_email": "doc@engeform.com.br",
                "subject": "ENC: Nota Fiscal SUP.2026-888",
                "received_at": None,
                "received_at_raw": "06/08/2026",
                "preview": None,
                "is_pinned": False,
                "has_attachments": False,
            },
            ["SUP.2026-888"],
            folder="Caixa de Entrada",
        )

    page = _page(client)

    assert "não cadastrado" in page
    assert "cadastrar" in page


def test_login_button_is_offered_when_there_is_no_session(client):
    """O app compilado não tem terminal: conectar precisa ser um botão."""
    assert "Conectar ao Outlook" in _page(client)


def test_no_login_warning_once_the_session_exists(client):
    config.BROWSER_STATE_PATH.write_text("{}", encoding="utf-8")

    page = _page(client)

    assert "Login pendente" not in page
    assert "Outlook conectado" in page


def test_login_status_reflects_a_session_saved_in_a_previous_run(client):
    """Quem conectou ontem continua conectado hoje, sem clicar em nada."""
    config.BROWSER_STATE_PATH.write_text("{}", encoding="utf-8")

    assert client.get("/login/status").get_json()["connected"] is True


def test_login_status_reports_disconnected_without_a_session(client):
    assert client.get("/login/status").get_json()["connected"] is False


def test_shutdown_says_goodbye_before_killing_the_process(client, monkeypatch):
    chamadas = []
    monkeypatch.setattr(server, "_schedule_shutdown", lambda: chamadas.append(True))

    response = client.post("/encerrar")

    assert response.status_code == 200
    assert "App encerrado" in response.get_data(as_text=True)
    assert chamadas == [True]


def test_summary_counts_what_needs_attention_today():
    """Os números do topo respondem "o que preciso olhar agora?"."""
    processes = [
        {"status": "vencido"},
        {"status": "critico"},
        {"status": "ok"},
        {"status": "sem_prazo"},
    ]
    proposals = [
        {"codes": ["SUP.2026-197"], "matched_by": ["código"]},
        {"codes": ["SUP.2026-888"], "matched_by": ["não cadastrado"]},
        # O mesmo código desconhecido em dois e-mails é uma pendência só.
        {"codes": ["SUP.2026-888"], "matched_by": ["não cadastrado"]},
    ]

    resumo = server._daily_summary(
        processes, proposals, {"events": [{}, {}], "stale": False}, total_messages=42
    )

    assert resumo["urgentes"] == 2
    assert resumo["processos"] == 4
    assert resumo["propostas"] == 3
    assert resumo["nao_cadastrados"] == 1
    assert resumo["reunioes"] == 2
    assert resumo["emails"] == 42


def test_summary_hides_the_meeting_count_when_the_cache_is_from_another_day():
    """Mostrar as reuniões de ontem como se fossem de hoje seria pior que
    não mostrar número nenhum."""
    resumo = server._daily_summary([], [], {"events": [{}, {}], "stale": True}, 0)

    assert resumo["reunioes"] is None


def test_scan_status_endpoint_reports_idle_state(client):
    status = client.get("/varredura/status").get_json()

    assert status["running"] is False
    assert status["scanned"] == 0


def test_folder_filter_narrows_the_recent_list(client):
    with storage.connect(config.DB_PATH) as connection:
        for index, folder in enumerate(["caixa real", "Caixa de Entrada"]):
            storage.save_message(
                connection,
                {
                    "conv_id": f"conv-{index}",
                    "sender_name": f"Remetente {folder}",
                    "sender_email": "x@y.com",
                    "subject": f"Assunto {index}",
                    "received_at": None,
                    "received_at_raw": "06/08/2026",
                    "preview": None,
                    "is_pinned": False,
                    "has_attachments": False,
                },
                [],
                folder=folder,
            )

    response = client.get("/?pasta=caixa+real")
    page = response.get_data(as_text=True)

    assert "Remetente caixa real" in page
    assert "Remetente Caixa de Entrada" not in page
