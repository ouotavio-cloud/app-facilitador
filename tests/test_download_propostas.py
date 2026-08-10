"""Download da proposta: quem é aberto, onde o arquivo cai, o que é pulado.

Usa um Outlook falso — o objetivo é fixar as decisões da varredura, não
testar o Playwright. As decisões que importam:

- só e-mail que casa com processo cadastrado é aberto, porque abrir marca
  como lido na caixa do usuário;
- rodar de novo não rebaixa o que já veio;
- falha ao baixar fica registrada, em vez de o arquivo sumir em silêncio.
"""

import pytest

from app_facilitador import browser_client, config, scanner, storage


class _PaginaFalsa:
    """Finge o painel de leitura do Outlook."""

    def __init__(self, anexos_por_conversa=None, falhar_download=False):
        self._anexos = anexos_por_conversa or {}
        self._falhar = falhar_download
        self.abertas = []
        self.baixados = []
        self._aberta = None

    def abrir(self, conv_id):
        self.abertas.append(conv_id)
        self._aberta = conv_id
        return True

    def anexos(self):
        return list(self._anexos.get(self._aberta, []))

    def baixar(self, nome, destino):
        if self._falhar:
            return False
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(f"conteúdo de {nome}", encoding="utf-8")
        self.baixados.append((self._aberta, nome, destino))
        return True


@pytest.fixture
def outlook(tmp_path, monkeypatch):
    """Substitui a varredura inteira: navegador, lista de e-mails e anexos."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "DEFAULT_PROPOSALS_DIR", tmp_path / "Propostas")

    estado = {"mensagens": [], "pagina": _PaginaFalsa()}

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
        browser_client, "open_message", lambda page, conv_id: page.abrir(conv_id)
    )
    monkeypatch.setattr(
        browser_client, "find_attachments", lambda page, extensoes: page.anexos()
    )
    monkeypatch.setattr(
        browser_client,
        "download_attachment",
        lambda page, nome, destino: page.baixar(nome, destino),
    )
    # O diagnóstico salva o HTML do painel numa falha; aqui só registramos
    # que foi chamado, sem tocar em navegador.
    monkeypatch.setattr(
        browser_client,
        "dump_message_debug",
        lambda page, destino: destino.write_text("<html>painel</html>", encoding="utf-8"),
    )

    return estado


def _mensagem(conv_id, assunto, remetente="Marcos", email="c@aciotubos.com.br", anexo=True):
    return {
        "conv_id": conv_id,
        "sender_name": remetente,
        "sender_email": email,
        "subject": assunto,
        "received_at": None,
        "received_at_raw": "07/08/2026",
        "preview": None,
        "is_pinned": False,
        "has_attachments": anexo,
    }


def _cadastrar(code, obra=None):
    with storage.connect(config.DB_PATH) as conexao:
        storage.add_process(conexao, code, obra)


def test_baixa_a_proposta_na_arvore_obra_processo_fornecedor(outlook, tmp_path):
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})

    resultado = scanner.scan()

    esperado = (
        tmp_path / "Propostas" / "Sabesp Lote 4" / "SUP.2026-197" / "Aciotubos"
        / "Aciotubos - Orçamento.pdf"
    )
    assert esperado.exists()
    assert resultado.downloaded == 1


def test_registra_o_fornecedor_junto_do_arquivo(outlook):
    """Saber de quem é a proposta é metade do valor de tê-la."""
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})

    scanner.scan()

    with storage.connect(config.DB_PATH) as conexao:
        anexos = storage.list_attachments(conexao)

    assert len(anexos) == 1
    assert anexos[0]["supplier"] == "Aciotubos"
    assert anexos[0]["code"] == "SUP.2026-197"
    assert anexos[0]["sender_email"] == "c@aciotubos.com.br"


def test_email_sem_processo_cadastrado_nao_e_aberto(outlook):
    """Abrir marca como lido: não dá para fazer isso com a caixa inteira."""
    outlook["mensagens"] = [_mensagem("c1", "Newsletter qualquer")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["catalogo.pdf"]})

    scanner.scan()

    assert outlook["pagina"].abertas == []


def test_anexo_que_e_so_assinatura_nao_vira_arquivo(outlook, tmp_path):
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["logo.png", "assinatura.jpg"]})

    resultado = scanner.scan()

    assert resultado.downloaded == 0
    assert not (tmp_path / "Propostas").exists()


def test_varrer_de_novo_nao_rebaixa_o_que_ja_veio(outlook):
    """Reabrir o e-mail custa segundos e não traz nada de novo."""
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    scanner.scan()

    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    resultado = scanner.scan()

    assert outlook["pagina"].abertas == []
    assert resultado.downloaded == 0


def test_apagar_o_arquivo_faz_baixar_de_novo(outlook, tmp_path):
    """A pasta manda: se a proposta sumiu do disco, a varredura a traz de volta."""
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    scanner.scan()

    baixado = (
        tmp_path / "Propostas" / "Sabesp Lote 4" / "SUP.2026-197" / "Aciotubos"
        / "Aciotubos - Orçamento.pdf"
    )
    assert baixado.exists()
    baixado.unlink()  # o usuário apagou a proposta da pasta

    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    resultado = scanner.scan()

    assert resultado.downloaded == 1
    assert baixado.exists()


def test_proposta_revisada_nao_apaga_a_anterior(outlook, tmp_path):
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    scanner.scan()

    # A revisão chega noutro e-mail, com o mesmo nome de arquivo.
    outlook["mensagens"] = [_mensagem("c2", "RE: Proposta SUP.2026-197 revisada")]
    outlook["pagina"] = _PaginaFalsa({"c2": ["Orçamento.pdf"]})
    scanner.scan()

    pasta = tmp_path / "Propostas" / "Sabesp Lote 4" / "SUP.2026-197" / "Aciotubos"
    assert (pasta / "Aciotubos - Orçamento.pdf").exists()
    assert (pasta / "Aciotubos - Orçamento (2).pdf").exists()


def test_falha_no_download_fica_registrada(outlook):
    """Sem registro, o arquivo simplesmente não existiria e ninguém veria."""
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]}, falhar_download=True)

    resultado = scanner.scan()

    assert resultado.download_failures == 1
    with storage.connect(config.DB_PATH) as conexao:
        anexos = storage.list_attachments(conexao)
    assert anexos[0]["error"]
    assert anexos[0]["path"] is None


def test_falha_no_download_salva_html_para_diagnostico(outlook):
    """Sem o HTML real do painel, calibrar o download é adivinhação."""
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]}, falhar_download=True)

    resultado = scanner.scan()

    assert resultado.debug_dump is not None
    from pathlib import Path

    assert Path(resultado.debug_dump).exists()


def test_falha_permite_nova_tentativa_na_proxima_varredura(outlook):
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]}, falhar_download=True)
    scanner.scan()

    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    resultado = scanner.scan()

    assert resultado.downloaded == 1


def test_download_desligado_nao_abre_nenhum_email(outlook):
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})

    scanner.scan(download_attachments=False)

    assert outlook["pagina"].abertas == []


def test_processo_sem_obra_ainda_arquiva(outlook, tmp_path):
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})

    scanner.scan()

    assert (
        tmp_path / "Propostas" / "Sem obra" / "SUP.2026-197" / "Aciotubos"
        / "Aciotubos - Orçamento.pdf"
    ).exists()


def test_pasta_escolhida_pelo_usuario_e_respeitada(outlook, tmp_path):
    _cadastrar("SUP.2026-197")
    escolhida = tmp_path / "OneDrive" / "Cotações"
    with storage.connect(config.DB_PATH) as conexao:
        storage.set_setting(conexao, config.PROPOSALS_DIR_SETTING, str(escolhida))

    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]})
    scanner.scan()

    assert (
        escolhida / "Sem obra" / "SUP.2026-197" / "Aciotubos" / "Aciotubos - Orçamento.pdf"
    ).exists()
