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
    """Finge o painel de leitura do Outlook.

    `corpo_por_conversa` e `texto_pdf` deixam um teste simular um código que
    só aparece no corpo do e-mail ou dentro do anexo — o que a leitura de
    conteúdo e a varredura profunda existem para pegar.
    """

    def __init__(
        self,
        anexos_por_conversa=None,
        falhar_download=False,
        corpo_por_conversa=None,
        texto_pdf=None,
    ):
        self._anexos = anexos_por_conversa or {}
        self._falhar = falhar_download
        self._corpo = corpo_por_conversa or {}
        self._texto_pdf = texto_pdf or {}
        self.abertas = []
        self.baixados = []
        self._aberta = None

    def abrir(self, conv_id):
        self.abertas.append(conv_id)
        self._aberta = conv_id
        return True

    def anexos(self):
        return list(self._anexos.get(self._aberta, []))

    def corpo(self):
        return self._corpo.get(self._aberta, "")

    def baixar(self, nome, destino):
        if self._falhar:
            return False
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Grava como conteúdo o texto de PDF configurado, para o extrator
        # (trocado no fixture por leitura direta do arquivo) achá-lo.
        destino.write_text(self._texto_pdf.get(nome, f"conteúdo de {nome}"), encoding="utf-8")
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
    # Corpo do e-mail vem do fake; o "texto do PDF" é o próprio conteúdo que
    # o fake gravou no arquivo — assim um teste controla o que está dentro.
    monkeypatch.setattr(
        browser_client, "read_message_body", lambda page: page.corpo()
    )
    from app_facilitador import pdf_text

    monkeypatch.setattr(
        pdf_text,
        "extract_text",
        lambda caminho, **kw: __import__("pathlib").Path(caminho).read_text(encoding="utf-8"),
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


def test_baixa_mesmo_sem_o_flag_de_anexo_na_lista(outlook, tmp_path):
    """O caso real: resposta de fornecedor a CARTA CONVITE sem o flag na linha.

    O flag "Tem anexos" sai do rótulo da linha, que o Outlook nem sempre
    monta. No banco do usuário ele barrava 11 dos 18 e-mails que casaram com
    processo cadastrado — todos propostas de verdade. Quem sabe se há anexo é
    o painel aberto, não a lista.
    """
    _cadastrar("SUP.2026-185", "661")
    outlook["mensagens"] = [
        _mensagem(
            "c1",
            "RES: SUP.2026-185 | CARTA CONVITE | 661-TAIAÇUPEBA | TUBOS EM FERRO FUNDIDO",
            email="daniel@dhlsaneamento.com.br",
            anexo=False,  # a lista não avisou
        )
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": ["PROPOSTA DHL - ENGEFORM.pdf"]})

    resultado = scanner.scan()

    assert outlook["pagina"].abertas == ["c1"]
    assert resultado.downloaded == 1
    assert (
        tmp_path / "Propostas" / "661" / "SUP.2026-185" / "Dhlsaneamento"
    ).is_dir()


def test_sem_anexo_de_verdade_o_email_casado_nao_vira_erro(outlook):
    """Abrir e não achar proposta é o filtro funcionando, não uma falha."""
    _cadastrar("SUP.2026-185")
    outlook["mensagens"] = [
        _mensagem("c1", "RES: SUP.2026-185 | CARTA CONVITE", anexo=False)
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": []})

    resultado = scanner.scan()

    assert outlook["pagina"].abertas == ["c1"]
    assert resultado.downloaded == 0
    assert resultado.download_failures == 0
    assert resultado.errors == []


def test_varredura_profunda_ainda_exige_o_flag_de_anexo(outlook):
    """Sem código casado, o flag é a única pista — sem ele a profunda abriria tudo.

    Abrir marca como lido no Outlook do usuário: o afrouxamento vale para o
    e-mail que já casou por código, não para a caixa inteira.
    """
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [
        _mensagem("c1", "Assunto sem código nenhum", anexo=False),
        _mensagem("c2", "Outro assunto sem código", anexo=True),
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": ["x.pdf"], "c2": ["y.pdf"]})

    scanner.scan(deep_scan=True)

    assert outlook["pagina"].abertas == ["c2"]


def _cadastrar_fornecedor(contato, nome=None):
    with storage.connect(config.DB_PATH) as conexao:
        storage.add_supplier(conexao, contato, nome)


def test_fornecedor_cadastrado_e_aberto_mesmo_sem_codigo_no_assunto(outlook, tmp_path):
    """O caso da DHL: proposta que a varredura por assunto não tinha como achar.

    O fornecedor respondeu na thread e o assunto que sobrou na lista não
    traz o código. Sem o cadastro não há o que casar; com ele, o e-mail é
    aberto, o corpo revela o processo e a proposta é arquivada.
    """
    _cadastrar("SUP.2026-185", "661")
    _cadastrar_fornecedor("dhlsaneamento.com.br", "DHL Saneamento")
    outlook["mensagens"] = [
        _mensagem("c1", "Re: Carta convite", email="daniel@dhlsaneamento.com.br",
                  anexo=False)
    ]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["PROPOSTA DHL - ENGEFORM.pdf"]},
        corpo_por_conversa={"c1": "Conforme solicitado segue proposta da SUP.2026-185"},
    )

    resultado = scanner.scan()

    assert outlook["pagina"].abertas == ["c1"]
    assert resultado.opened_by_supplier == 1
    assert resultado.downloaded == 1
    # E a pasta usa o nome cadastrado, não o palpite do domínio.
    assert (
        tmp_path / "Propostas" / "661" / "SUP.2026-185" / "DHL Saneamento"
    ).is_dir()


def test_fornecedor_cadastrado_com_email_pessoal_nomeia_a_pasta(outlook, tmp_path):
    """`molivetto2@gmail.com` virava a pasta "Molivetto2"."""
    _cadastrar("SUP.2026-185", "661")
    _cadastrar_fornecedor("molivetto2@gmail.com", "Molivetto Tubos")
    outlook["mensagens"] = [
        _mensagem("c1", "RES: SUP.2026-185 | CARTA CONVITE",
                  remetente="Marcio", email="molivetto2@gmail.com")
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Proposta Comercial 2026.pdf"]})

    scanner.scan()

    assert (
        tmp_path / "Propostas" / "661" / "SUP.2026-185" / "Molivetto Tubos"
    ).is_dir()


def test_sem_fornecedor_cadastrado_nada_muda(outlook):
    """A tabela vazia é o padrão — quem não usa não pode notar diferença."""
    outlook["mensagens"] = [
        _mensagem("c1", "Assunto sem código", email="daniel@dhlsaneamento.com.br")
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Proposta.pdf"]})

    resultado = scanner.scan()

    assert outlook["pagina"].abertas == []
    assert resultado.opened_by_supplier == 0


def test_fornecedor_cadastrado_sem_processo_no_corpo_nao_arquiva(outlook, tmp_path):
    """Abrir é barato; arquivar sem saber o processo criaria lixo."""
    _cadastrar("SUP.2026-185", "661")
    _cadastrar_fornecedor("dhlsaneamento.com.br")
    outlook["mensagens"] = [
        _mensagem("c1", "Bom dia", email="daniel@dhlsaneamento.com.br")
    ]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Catalogo.pdf"]}, corpo_por_conversa={"c1": "Segue nosso catálogo."}
    )

    resultado = scanner.scan()

    assert outlook["pagina"].abertas == ["c1"]
    assert resultado.downloaded == 0
    assert not (tmp_path / "Propostas" / "661").exists()


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


def test_falha_no_download_nao_deixa_pasta_vazia(outlook, tmp_path):
    """Foi o que o usuário viu: a árvore da proposta montada e vazia.

    Uma pasta `Obra/Processo/Fornecedor` sem nada dentro afirma que a
    proposta chegou. Quando o download falha, o certo é não haver pasta —
    a pendência aparece no resumo e no registro de anexos.
    """
    _cadastrar("SUP.2026-186", "661")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-186")]
    outlook["pagina"] = _PaginaFalsa({"c1": ["Orçamento.pdf"]}, falhar_download=True)

    resultado = scanner.scan()

    assert resultado.download_failures == 1
    assert not (tmp_path / "Propostas" / "661").exists()


def test_varredura_recolhe_pastas_vazias_que_ja_existiam(outlook, tmp_path):
    """Faxina do estrago das versões anteriores, sem tocar no que tem arquivo."""
    propostas = tmp_path / "Propostas"
    (propostas / "661" / "SUP.2026-186" / "Engeform").mkdir(parents=True)
    guardada = propostas / "657" / "SUP.2026-197" / "Molivetto2"
    guardada.mkdir(parents=True)
    (guardada / "Molivetto2 - Proposta.pdf").write_text("proposta de verdade")

    resultado = scanner.scan()

    assert not (propostas / "661").exists()
    assert (guardada / "Molivetto2 - Proposta.pdf").exists()
    assert resultado.empty_dirs_removed == 3


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


# ---------- leitura de corpo e PDF ----------


def test_corpo_confirma_o_codigo_com_a_pista_conteudo(outlook):
    """Casou pela obra; ler o corpo confirma o código e some a pista 'conteúdo'."""
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    # Assunto tem a obra (casa por obra), mas não o código. O código está no corpo.
    outlook["mensagens"] = [_mensagem("c1", "Proposta obra Sabesp Lote 4")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Orçamento.pdf"]},
        corpo_por_conversa={"c1": "Segue nossa proposta referente à SUP.2026-197."},
    )

    scanner.scan()

    with storage.connect(config.DB_PATH) as conexao:
        proposta = storage.list_messages_with_codes(conexao)[0]
    idx = proposta["codes"].index("SUP.2026-197")
    assert "conteúdo" in proposta["matched_by"][idx]


def test_pdf_confirma_o_codigo_com_a_pista_conteudo(outlook):
    """O código também é lido de dentro do anexo, não só do corpo."""
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    outlook["mensagens"] = [_mensagem("c1", "Proposta obra Sabesp Lote 4")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Orçamento.pdf"]},
        texto_pdf={"Orçamento.pdf": "PROPOSTA COMERCIAL - Processo SUP.2026-197"},
    )

    scanner.scan()

    with storage.connect(config.DB_PATH) as conexao:
        proposta = storage.list_messages_with_codes(conexao)[0]
    idx = proposta["codes"].index("SUP.2026-197")
    assert "conteúdo" in proposta["matched_by"][idx]


def test_conteudo_revela_processo_adicional(outlook):
    """Um e-mail pode tratar de mais de um processo; o corpo revela o segundo."""
    _cadastrar("SUP.2026-197")
    _cadastrar("SUP.2026-198")
    # Assunto casa só o 197 (pelo código); o 198 aparece apenas no corpo.
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-197")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Orçamento.pdf"]},
        corpo_por_conversa={"c1": "Aproveito e envio também a SUP.2026-198."},
    )

    resultado = scanner.scan()

    assert resultado.codes_in_content == 1  # o 198, novo, veio do corpo
    with storage.connect(config.DB_PATH) as conexao:
        proposta = storage.list_messages_with_codes(conexao)[0]
    assert "SUP.2026-198" in proposta["codes"]


# ---------- varredura profunda ----------


def test_varredura_profunda_acha_proposta_pelo_corpo(outlook, tmp_path):
    """E-mail sem pista no assunto, mas com o código no corpo, é encontrado."""
    _cadastrar("SUP.2026-197", "Sabesp Lote 4")
    # Assunto genérico: não casa por assunto/obra.
    outlook["mensagens"] = [_mensagem("c1", "Boa tarde, segue anexo")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Orçamento.pdf"]},
        corpo_por_conversa={"c1": "Referente ao processo SUP.2026-197, segue proposta."},
    )

    resultado = scanner.scan(deep_scan=True)

    assert resultado.deep_matches == 1
    assert resultado.downloaded == 1
    assert (
        tmp_path / "Propostas" / "Sabesp Lote 4" / "SUP.2026-197" / "Aciotubos"
        / "Aciotubos - Orçamento.pdf"
    ).exists()


def test_varredura_profunda_nao_arquiva_o_que_nao_casa(outlook, tmp_path):
    """E-mail com anexo mas sem processo cadastrado: abre, lê, e descarta."""
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Newsletter do fornecedor")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["catalogo.pdf"]},
        corpo_por_conversa={"c1": "Confira nossos lançamentos deste mês."},
        texto_pdf={"catalogo.pdf": "catálogo de produtos, sem código nenhum"},
    )

    resultado = scanner.scan(deep_scan=True)

    assert resultado.deep_matches == 0
    assert resultado.downloaded == 0
    assert not (tmp_path / "Propostas").exists()


def test_um_email_interno_arquiva_por_fornecedor_do_nome(outlook, tmp_path):
    """O caso do print: e-mail do próprio domínio com propostas de 3 empresas."""
    _cadastrar("SUP.2026-186", "661")
    outlook["mensagens"] = [
        _mensagem("c1", "Propostas SUP.2026-186", remetente="Otávio", email="o@engeform.com.br")
    ]
    outlook["pagina"] = _PaginaFalsa(
        {
            "c1": [
                "Engeform - 260722 - PC - BERMAD - R00.pdf",
                "Engeform - 260729 - PC - RTS - R00.pdf",
                "Engeform - 260803 - PC - SAINT GOBAIN - R00.pdf",
            ]
        }
    )

    scanner.scan()

    base = tmp_path / "Propostas" / "661" / "SUP.2026-186"
    assert (base / "BERMAD").is_dir()
    assert (base / "RTS").is_dir()
    assert (base / "SAINT GOBAIN").is_dir()
    # E nunca sob o próprio comprador.
    assert not (base / "Engeform").exists()


def test_pula_a_tecnica_quando_vem_com_a_comercial(outlook, tmp_path):
    _cadastrar("SUP.2026-186", "661")
    outlook["mensagens"] = [
        _mensagem("c1", "Propostas SUP.2026-186", email="o@engeform.com.br")
    ]
    outlook["pagina"] = _PaginaFalsa(
        {
            "c1": [
                "Engeform - PT - BERMAD - R00.pdf",
                "Engeform - PC - BERMAD - R00.pdf",
            ]
        }
    )

    resultado = scanner.scan()

    pasta = tmp_path / "Propostas" / "661" / "SUP.2026-186" / "BERMAD"
    arquivos = [p.name for p in pasta.iterdir()]
    assert any("PC" in a for a in arquivos)
    assert not any("PT" in a for a in arquivos)
    assert resultado.downloaded == 1


def test_email_de_nota_fiscal_nao_e_aberto(outlook):
    """Do log real: e-mails de DANFE/contrato citam o código mas não são
    proposta — não podem ser abertos (marca como lido) nem baixados."""
    _cadastrar("SUP.2026-185")
    outlook["mensagens"] = [
        _mensagem("c1", "DANFE 1834316 referente à SUP.2026-185")
    ]
    outlook["pagina"] = _PaginaFalsa({"c1": ["DANFE 1834316.pdf"]})

    resultado = scanner.scan()

    assert outlook["pagina"].abertas == []
    assert resultado.downloaded == 0
    assert resultado.skipped_non_proposal == 1


def test_habilitacao_junto_da_proposta_nao_e_baixada(outlook, tmp_path):
    """No mesmo e-mail vêm a proposta e a papelada; só a proposta é guardada."""
    _cadastrar("SUP.2026-185", "Obra X")
    outlook["mensagens"] = [_mensagem("c1", "Proposta SUP.2026-185")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Proposta Comercial - ANGOLINI.pdf", "Cartão CNPJ Angolini.pdf",
                "Certidão CND Angolini.pdf"]}
    )

    resultado = scanner.scan()

    assert resultado.downloaded == 1  # só a proposta


def test_sem_varredura_profunda_email_nao_identificado_nao_e_aberto(outlook):
    """Sem deep scan, e-mail que não casou por assunto não é aberto (não marca lido)."""
    _cadastrar("SUP.2026-197")
    outlook["mensagens"] = [_mensagem("c1", "Boa tarde, segue anexo")]
    outlook["pagina"] = _PaginaFalsa(
        {"c1": ["Orçamento.pdf"]},
        corpo_por_conversa={"c1": "Referente ao SUP.2026-197."},
    )

    scanner.scan(deep_scan=False)

    assert outlook["pagina"].abertas == []
