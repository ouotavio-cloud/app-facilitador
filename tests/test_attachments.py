"""Arquivamento das propostas: onde cada arquivo vai parar e com que nome.

O que se testa aqui é decisão, não download: quem é o fornecedor, que
arquivo vale a pena guardar, e como não sobrescrever uma proposta ao
receber a revisão dela.
"""

import pytest

from app_facilitador import attachments


class TestQueArquivoVale:
    """Uma proposta é um documento — logotipo de assinatura não é."""

    @pytest.mark.parametrize(
        "nome",
        [
            "Proposta SUP.2026-197.pdf",
            "orcamento.xlsx",
            "planilha.XLSM",
            "documentos.zip",
            "projeto.dwg",
            "carta.docx",
        ],
    )
    def test_documentos_sao_guardados(self, nome):
        assert attachments.is_document(nome)

    @pytest.mark.parametrize(
        "nome",
        [
            "logo.png",
            "assinatura.jpg",
            "image001.gif",
            "rodape.jpeg",
            "icone.svg",
            "",
            "sem-extensao",
        ],
    )
    def test_enfeite_de_email_e_ignorado(self, nome):
        """Baixar todo logotipo encheria as pastas de lixo."""
        assert not attachments.is_document(nome)


class TestQuemEOFornecedor:
    def test_usa_o_dominio_e_nao_o_nome_de_quem_escreveu(self):
        """No mês seguinte pode ser outra pessoa da mesma empresa."""
        assert (
            attachments.supplier_folder("Marcos Ribeiro", "comercial@aciotubos.com.br")
            == "Aciotubos"
        )
        assert (
            attachments.supplier_folder("Fernanda Lima", "vendas@aciotubos.com.br")
            == "Aciotubos"
        )

    def test_ignora_subdominios_e_sufixos(self):
        assert (
            attachments.supplier_folder(None, "x@comercial.hidraumax.ind.br")
            == "Hidraumax"
        )

    def test_email_pessoal_cai_no_nome_do_remetente(self):
        """gmail.com não identifica empresa nenhuma."""
        assert (
            attachments.supplier_folder("Serralheria do João", "joao123@gmail.com")
            == "Serralheria do João"
        )

    def test_sem_remetente_nenhum_ainda_devolve_uma_pasta(self):
        assert attachments.supplier_folder(None, None) == "Fornecedor"

    def test_quando_o_nome_e_o_proprio_email_extrai_do_endereco(self):
        """Do banco: 'vendas.angolini@yahoo...' virava a pasta feia com o e-mail."""
        assert (
            attachments.supplier_folder(
                "vendas.angolini@yahoo.com.br", "vendas.angolini@yahoo.com.br"
            )
            == "Angolini"
        )

    def test_sem_nome_extrai_do_local_do_email(self):
        assert (
            attachments.supplier_folder(None, "vendas.angolini@yahoo.com.br") == "Angolini"
        )


class TestNomesQueOWindowsAceita:
    def test_troca_caracteres_proibidos(self):
        assert attachments.sanitize('Obra: Lote 4/5 "Sul"') == "Obra- Lote 4-5 -Sul-"

    def test_remove_ponto_e_espaco_do_fim(self):
        """O Windows apaga esses em silêncio, e o caminho gravado deixa de
        ser o que o app pensa que gravou."""
        assert attachments.sanitize("Fornecedor Ltda. ") == "Fornecedor Ltda"

    def test_escapa_nome_reservado_pelo_windows(self):
        """Uma pasta chamada CON não pode ser criada."""
        assert attachments.sanitize("CON") == "CON-"
        assert attachments.sanitize("com1") == "com1-"

    def test_encurta_nome_gigante(self):
        resultado = attachments.sanitize("A" * 200)

        assert len(resultado) <= 60

    def test_texto_vazio_vira_o_reserva(self):
        assert attachments.sanitize("   ") == "sem-nome"
        assert attachments.sanitize("///") == "sem-nome"

    def test_a_extensao_do_arquivo_e_preservada(self):
        """É o que faz o Windows abrir o PDF no leitor certo."""
        assert (
            attachments.file_name_for("Proposta: revisão 2.pdf")
            == "Proposta- revisão 2.pdf"
        )

    def test_arquivo_sem_nome_util_ainda_abre(self):
        assert attachments.file_name_for(".pdf") == "proposta.pdf"


class TestNomeComFornecedor:
    def test_prefixa_o_fornecedor(self):
        """O nome sozinho precisa dizer de quem é a proposta."""
        assert (
            attachments.proposal_file_name("Aciotubos", "Proposta Comercial.pdf")
            == "Aciotubos - Proposta Comercial.pdf"
        )

    def test_preserva_a_extensao(self):
        nome = attachments.proposal_file_name("Angolini", "orçamento.xlsx")
        assert nome.endswith(".xlsx")

    def test_nao_repete_o_fornecedor_ja_presente(self):
        """Evita 'Aciotubos - Aciotubos proposta.pdf'."""
        nome = attachments.proposal_file_name("Aciotubos", "Aciotubos proposta.pdf")
        assert nome == "Aciotubos proposta.pdf"

    def test_ignora_acento_e_caixa_ao_comparar(self):
        nome = attachments.proposal_file_name("Construção", "construcao final.pdf")
        assert nome == "construcao final.pdf"

    def test_fornecedor_vazio_ainda_gera_nome_valido(self):
        nome = attachments.proposal_file_name("", "proposta.pdf")
        assert nome == "Fornecedor - proposta.pdf"

    def test_nome_final_respeita_o_limite(self):
        nome = attachments.proposal_file_name("Fornecedor", "A" * 200 + ".pdf")
        # O miolo (sem extensão) não pode estourar o teto por componente.
        assert len(nome) - len(".pdf") <= 60
        assert nome.startswith("Fornecedor - ")
        assert nome.endswith(".pdf")


class TestNaoEProposta:
    """Nota fiscal, contrato e habilitação não são proposta — do log real."""

    @pytest.mark.parametrize(
        "texto",
        [
            "DANFE 1834316 - 304247678.pdf",
            "CND - MUNICIPAL - Wireflex.pdf",
            "Cartão CNPJ LCR Cabos.pdf",
            "Simples Nacional LCR Cabos.pdf",
            "Inscrição Estadual LCR Cabos.pdf",
            "Certidão de ISSQN.pdf",
            "Feitos Trabalhistas - Wireflex.pdf",
            "Nota Fiscal 12345.pdf",
        ],
    )
    def test_reconhece_nao_proposta(self, texto):
        assert attachments.is_probably_not_proposal(texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "Proposta Comercial 0018532 - ANGOLINI.pdf",
            "260722 - PT - BERMAD - R00.pdf",
            "Orçamento tubos.pdf",
            "PROPOSTA COMERCIAL CROSSFOX.xlsx",
        ],
    )
    def test_nao_marca_proposta_de_verdade(self, texto):
        assert not attachments.is_probably_not_proposal(texto)


class TestTipoDaProposta:
    def test_reconhece_a_tecnica_pela_sigla_pt(self):
        assert attachments.classify_proposal("Engeform - 260722 - PT - BERMAD - R00.pdf") == "tecnica"

    def test_reconhece_a_comercial_pela_sigla_pc(self):
        assert attachments.classify_proposal("Engeform - 260722 - PC - BERMAD - R00.pdf") == "comercial"

    def test_reconhece_por_extenso(self):
        assert attachments.classify_proposal("Proposta Comercial Saint Gobain.pdf") == "comercial"
        assert attachments.classify_proposal("proposta tecnica rts.pdf") == "tecnica"

    def test_sem_marcador_fica_indefinida(self):
        assert attachments.classify_proposal("661_SUP_VALVULAS_202607_R00.xlsx") is None

    def test_comercial_ganha_do_empate(self):
        """Se o nome cita as duas, a comercial (com preço) é o que interessa."""
        assert attachments.classify_proposal("PT e PC comercial juntas.pdf") == "comercial"


class TestFornecedorPeloArquivo:
    def test_pega_o_fornecedor_depois_do_marcador(self):
        assert (
            attachments.supplier_from_filename("Engeform - 260722 - PT - BERMAD - R00.pdf")
            == "BERMAD"
        )

    def test_fornecedor_com_espaco(self):
        assert (
            attachments.supplier_from_filename("Engeform - 260803 - PT - SAINT GOBAIN - R00.pdf")
            == "SAINT GOBAIN"
        )

    def test_sem_marcador_devolve_none(self):
        assert attachments.supplier_from_filename("proposta.pdf") is None

    def test_pula_revisao_como_fornecedor(self):
        # Se depois do marcador só vier a revisão, não é fornecedor.
        assert attachments.supplier_from_filename("obra - PC - R00.pdf") is None

    def test_ignora_candidato_so_com_numeros(self):
        """Aprendido do banco: 'Proposta Comercial - 2026_08 - ...' dava '2026'."""
        assert (
            attachments.supplier_from_filename(
                "Proposta Comercial -  2026_08 - 34072. - CONSORCIO.pdf"
            )
            is None
        )

    def test_supplier_for_prefere_o_arquivo_ao_dominio(self):
        """Num e-mail interno, o domínio é do comprador; o arquivo diz o real."""
        nome = "Engeform - 260722 - PT - BERMAD - R00.pdf"
        assert (
            attachments.supplier_for("Otávio", "otavio@engeform.com.br", nome) == "BERMAD"
        )

    def test_supplier_for_usa_dominio_quando_arquivo_nao_diz(self):
        assert (
            attachments.supplier_for("Marcos", "c@aciotubos.com.br", "proposta.pdf")
            == "Aciotubos"
        )


class TestSelecaoDePropostas:
    def _nomes(self, itens):
        return [i["filename"] for i in itens]

    def test_um_email_com_varios_fornecedores(self):
        """O caso do print: três fornecedores num e-mail interno só."""
        arquivos = [
            "Engeform - 260722 - PT - BERMAD - R00.pdf",
            "Engeform - 260729 - PT - RTS - R00.pdf",
            "Engeform - 260803 - PT - SAINT GOBAIN - R00.pdf",
        ]
        itens = attachments.select_proposals(arquivos, "Otávio", "o@engeform.com.br")
        fornecedores = {i["supplier"] for i in itens}
        assert fornecedores == {"BERMAD", "RTS", "SAINT GOBAIN"}

    def test_pula_a_tecnica_quando_ha_comercial_do_mesmo_fornecedor(self):
        arquivos = [
            "Obra - PT - BERMAD - R00.pdf",
            "Obra - PC - BERMAD - R00.pdf",
        ]
        itens = attachments.select_proposals(arquivos, "Marcos", "c@bermad.com.br")
        assert self._nomes(itens) == ["Obra - PC - BERMAD - R00.pdf"]

    def test_mantem_a_tecnica_se_for_a_unica_do_fornecedor(self):
        arquivos = ["Obra - PT - BERMAD - R00.pdf"]
        itens = attachments.select_proposals(arquivos, "Marcos", "c@bermad.com.br")
        assert len(itens) == 1

    def test_keep_technical_mantem_as_duas(self):
        arquivos = [
            "Obra - PT - BERMAD - R00.pdf",
            "Obra - PC - BERMAD - R00.pdf",
        ]
        itens = attachments.select_proposals(
            arquivos, "Marcos", "c@bermad.com.br", keep_technical=True
        )
        assert len(itens) == 2

    def test_tecnica_de_um_nao_some_por_comercial_de_outro(self):
        """A comercial da BERMAD não pode apagar a técnica da RTS."""
        arquivos = [
            "Obra - PC - BERMAD - R00.pdf",
            "Obra - PT - RTS - R00.pdf",
        ]
        itens = attachments.select_proposals(arquivos, "x", "x@engeform.com.br")
        assert len(itens) == 2


class TestArvoreDePastas:
    def test_obra_processo_fornecedor(self, tmp_path):
        destino = attachments.proposal_dir(
            tmp_path, "Sabesp Lote 4", "SUP.2026-197", "Aciotubos"
        )

        assert destino == tmp_path / "Sabesp Lote 4" / "SUP.2026-197" / "Aciotubos"

    def test_processo_sem_obra_ainda_tem_onde_ficar(self, tmp_path):
        """Descartar o arquivo ou jogá-lo na raiz seria pior."""
        destino = attachments.proposal_dir(tmp_path, None, "SUP.2026-197", "Aciotubos")

        assert destino == tmp_path / "Sem obra" / "SUP.2026-197" / "Aciotubos"


class TestPropostaRevisada:
    def test_nao_sobrescreve_a_anterior(self, tmp_path):
        """Comparar a revisão com a original é parte do trabalho de cotar."""
        original = tmp_path / "Proposta.pdf"
        original.write_text("primeira versão")

        destino = attachments.unique_path(original)

        assert destino == tmp_path / "Proposta (2).pdf"
        assert original.read_text() == "primeira versão"

    def test_numera_a_partir_da_segunda_versao(self, tmp_path):
        (tmp_path / "Proposta.pdf").write_text("v1")
        (tmp_path / "Proposta (2).pdf").write_text("v2")

        assert attachments.unique_path(tmp_path / "Proposta.pdf") == (
            tmp_path / "Proposta (3).pdf"
        )

    def test_caminho_livre_e_devolvido_como_veio(self, tmp_path):
        destino = tmp_path / "Proposta.pdf"

        assert attachments.unique_path(destino) == destino


class TestDocumentoDoComprador:
    """Nomes reais tirados do banco do usuário — os que estavam na pasta
    do fornecedor sem serem proposta dele."""

    @pytest.mark.parametrize(
        "arquivo",
        [
            "661_SUP_VALVULAS_202607_R00.xlsx",
            "661_SUP_TUBOS_CONEXOES_AC_202707_R00.xlsx",
            "656_SUP_PLANILHA Painéis Elétricos.xlsx",
            "Requisição Sistema hardware para SVP (rev B1) SWITCHs e PSVP.xlsx",
            "Mapa de Cotação - TUBOS E CONEXOES EM FERRO FUNDIDO.xlsx",
            "CARTA CONVITE N° SUP 2026-171 - PPP FASE 2.pdf",
            "Minuta padrão de Fornecimento.docx",
            "QC SUP.171 - PAINÉIS ELÉTRICOS - FASE 2.pdf",
            "260807-RESUMO EXECUTIVO PPPs F2 - INSTAL ELE+HID+PCI.pdf",
            "Ficha cadastral ETE São Miguel.pdf",
        ],
    )
    def test_documento_do_comprador_e_reconhecido(self, arquivo):
        assert attachments.is_buyer_document(arquivo)

    @pytest.mark.parametrize(
        "arquivo",
        [
            "Proposta Comercial 0018532-2026 - ANGOLINI 07.08.2026.pdf",
            "260722 - PT - BERMAD - R00.pdf",
            "PC 05358 - NIT 3320 - 5 - CONSORCIO EES ETA ITABIRA.pdf",
            "PC-0336352-R3MSS.pdf",
            "41675-COM.PDF",
            "PTC 285_26 - ENGEFORM.pdf",
            "57336-4 - Proposta Comercial - Proposta 3 - NOBREAK SINGELO.pdf",
            "PROPOSTA COMERCIAL CROSSFOX - SOLICITAÇÃO DE COTAÇÃO - ENGEFORM.xlsx",
        ],
    )
    def test_proposta_de_verdade_passa(self, arquivo):
        """O filtro não pode custar nenhuma proposta — é o que ele existe para achar."""
        assert not attachments.is_buyer_document(arquivo)

    def test_nao_se_aplica_ao_assunto_do_email(self):
        """Quase todo assunto de proposta responde a uma carta convite.

        Se esta regra valesse para o assunto, ela descartaria justamente as
        propostas — daí ela ser separada de `is_probably_not_proposal`.
        """
        assunto = "RES: SUP.2026-185 | CARTA CONVITE | 661-TAIAÇUPEBA | TUBOS"

        assert not attachments.is_probably_not_proposal(assunto)


class TestPastasVazias:
    """Faxina das árvores que sobraram de quando a pasta nascia antes do
    download — o usuário abria `Propostas` e via a estrutura montada, sem
    um arquivo dentro."""

    def test_leva_a_arvore_vazia_inteira(self, tmp_path):
        (tmp_path / "661" / "SUP.2026-186" / "Engeform").mkdir(parents=True)

        removidas = attachments.remove_empty_dirs(tmp_path)

        assert removidas == 3
        assert not (tmp_path / "661").exists()

    def test_preserva_o_ramo_que_tem_proposta(self, tmp_path):
        cheia = tmp_path / "661" / "SUP.2026-186" / "Angolini"
        cheia.mkdir(parents=True)
        (cheia / "Angolini - Proposta.pdf").write_text("proposta")
        (tmp_path / "661" / "SUP.2026-186" / "Engeform").mkdir()

        removidas = attachments.remove_empty_dirs(tmp_path)

        assert removidas == 1
        assert (cheia / "Angolini - Proposta.pdf").read_text() == "proposta"
        assert not (tmp_path / "661" / "SUP.2026-186" / "Engeform").exists()

    def test_nao_apaga_a_pasta_escolhida_pelo_usuario(self, tmp_path):
        """`Propostas` é a pasta que o painel abre; ela fica, mesmo vazia."""
        base = tmp_path / "Propostas"
        base.mkdir()

        assert attachments.remove_empty_dirs(base) == 0
        assert base.is_dir()

    def test_pasta_inexistente_nao_quebra(self, tmp_path):
        assert attachments.remove_empty_dirs(tmp_path / "nao-existe") == 0
