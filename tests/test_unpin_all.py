"""scanner.unpin_all: percorre a pasta e desafixa só o que reconhece.

Usa um Outlook falso, no mesmo espírito de `test_download_propostas.py` — o
que importa fixar aqui é a decisão (quais e-mails tentar, o que contar,
o que reportar), não o clique em si, que já é testado à parte em
`test_unpin.py` contra o `browser_client.unpin_message` real.
"""

import pytest

from app_facilitador import browser_client, scanner


class _PaginaFalsa:
    """Registra em quais conversas o app tentou desafixar e o resultado."""

    def __init__(self, resultado_por_conversa=None):
        self._resultado = resultado_por_conversa or {}
        self.tentativas = []

    def tentar_desafixar(self, conv_id):
        self.tentativas.append(conv_id)
        return self._resultado.get(conv_id, False)


@pytest.fixture
def outlook(monkeypatch):
    estado = {"mensagens": [], "pagina": _PaginaFalsa(), "pasta_aberta": None}

    class _Sessao:
        def __enter__(self_inner):
            return estado["pagina"]

        def __exit__(self_inner, *exc):
            return False

    monkeypatch.setattr(browser_client, "open_inbox_session", lambda **kw: _Sessao())
    monkeypatch.setattr(
        browser_client, "scan_inbox", lambda page, **kw: iter(estado["mensagens"])
    )
    monkeypatch.setattr(
        browser_client,
        "open_folder",
        lambda page, folder: estado.__setitem__("pasta_aberta", folder),
    )
    monkeypatch.setattr(
        browser_client, "unpin_message", lambda page, conv_id: page.tentar_desafixar(conv_id)
    )

    return estado


def _mensagem(conv_id, subject="Assunto qualquer", pinned=False):
    return {
        "conv_id": conv_id,
        "sender_name": "Fulano",
        "sender_email": "fulano@x.com",
        "subject": subject,
        "received_at": None,
        "received_at_raw": "hoje",
        "preview": None,
        "is_pinned": pinned,
        "has_attachments": False,
    }


def test_so_tenta_desafixar_mensagens_que_estao_fixadas(outlook):
    outlook["mensagens"] = [
        _mensagem("c1", pinned=False),
        _mensagem("c2", pinned=True),
        _mensagem("c3", pinned=False),
    ]
    outlook["pagina"] = _PaginaFalsa({"c2": True})

    resultado = scanner.unpin_all()

    assert outlook["pagina"].tentativas == ["c2"]
    assert resultado.scanned == 3
    assert resultado.pinned_found == 1
    assert resultado.unpinned == 1


def test_conta_sucesso_e_falha_separadamente(outlook):
    outlook["mensagens"] = [
        _mensagem("c1", "Proposta A", pinned=True),
        _mensagem("c2", "Proposta B", pinned=True),
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": True, "c2": False})

    resultado = scanner.unpin_all()

    assert resultado.pinned_found == 2
    assert resultado.unpinned == 1
    assert resultado.not_identified == ["Proposta B"]


def test_sem_nenhum_fixado_nao_tenta_nada(outlook):
    outlook["mensagens"] = [_mensagem("c1", pinned=False)]

    resultado = scanner.unpin_all()

    assert outlook["pagina"].tentativas == []
    assert resultado.pinned_found == 0
    assert resultado.unpinned == 0


def test_abre_a_pasta_informada(outlook):
    outlook["mensagens"] = []

    scanner.unpin_all(folder="Caixa real")

    assert outlook["pasta_aberta"] == "Caixa real"


def test_should_stop_interrompe_e_marca_resultado_parcial(outlook):
    outlook["mensagens"] = [
        _mensagem("c1", pinned=True),
        _mensagem("c2", pinned=True),
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": True, "c2": True})

    resultado = scanner.unpin_all(should_stop=lambda: True)

    assert resultado.stopped is True
    assert resultado.scanned == 0
    assert outlook["pagina"].tentativas == []
