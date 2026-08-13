"""Cadastro de fornecedores: reconhecer o remetente e nomear a pasta.

Opcional por natureza — a varredura casa pelo código no assunto e funciona
com a tabela vazia. O cadastro existe para os dois casos em que o código não
basta:

- o fornecedor responde sem repetir o código (nada para casar no assunto);
- o e-mail é pessoal e o domínio não diz que empresa é
  (`molivetto2@gmail.com` virava a pasta "Molivetto2").
"""

from app_facilitador import attachments, config, storage


class TestNormalizacao:
    """O usuário digita de três jeitos; todos precisam casar com o mesmo."""

    def test_aceita_arroba_na_frente_do_dominio(self):
        assert storage.normalize_supplier_match("@dhl.com.br") == "dhl.com.br"

    def test_ignora_caixa_e_espacos(self):
        assert storage.normalize_supplier_match("  Daniel@DHL.com.br ") == "daniel@dhl.com.br"

    def test_dominio_puro_fica_como_esta(self):
        assert storage.normalize_supplier_match("dhl.com.br") == "dhl.com.br"


class TestCadastro:
    def _conexao(self, tmp_path):
        return storage.connect(tmp_path / "t.db")

    def test_cadastra_e_lista(self, tmp_path):
        with self._conexao(tmp_path) as c:
            assert storage.add_supplier(c, "dhl.com.br", "DHL Saneamento") is True
            listado = storage.list_suppliers(c)

        assert len(listado) == 1
        assert listado[0]["match"] == "dhl.com.br"
        assert listado[0]["name"] == "DHL Saneamento"

    def test_recadastrar_corrige_o_nome_sem_duplicar(self, tmp_path):
        with self._conexao(tmp_path) as c:
            storage.add_supplier(c, "dhl.com.br", "Nome errado")
            storage.add_supplier(c, "dhl.com.br", "DHL Saneamento")
            listado = storage.list_suppliers(c)

        assert len(listado) == 1
        assert listado[0]["name"] == "DHL Saneamento"

    def test_remove(self, tmp_path):
        with self._conexao(tmp_path) as c:
            storage.add_supplier(c, "dhl.com.br")
            assert storage.remove_supplier(c, "@dhl.com.br") is True
            assert storage.list_suppliers(c) == []

    def test_contato_vazio_nao_vira_cadastro(self, tmp_path):
        with self._conexao(tmp_path) as c:
            assert storage.add_supplier(c, "   ") is False
            assert storage.list_suppliers(c) == []

    def test_registry_devolve_dicionario_para_a_varredura(self, tmp_path):
        with self._conexao(tmp_path) as c:
            storage.add_supplier(c, "dhl.com.br", "DHL")
            storage.add_supplier(c, "molivetto2@gmail.com", "Molivetto Tubos")
            assert storage.supplier_registry(c) == {
                "dhl.com.br": "DHL",
                "molivetto2@gmail.com": "Molivetto Tubos",
            }


class TestReconhecerRemetente:
    """`is_registered_supplier` é o segundo critério da varredura."""

    CADASTRO = {"dhlsaneamento.com.br": "DHL", "molivetto2@gmail.com": "Molivetto"}

    def test_casa_pelo_dominio(self):
        assert attachments.is_registered_supplier(
            "daniel@dhlsaneamento.com.br", self.CADASTRO
        )

    def test_casa_pelo_endereco_inteiro(self):
        assert attachments.is_registered_supplier("molivetto2@gmail.com", self.CADASTRO)

    def test_nao_casa_o_gmail_de_outra_pessoa(self):
        """Cadastrar um gmail não pode transformar o gmail inteiro em fornecedor."""
        assert not attachments.is_registered_supplier("outro@gmail.com", self.CADASTRO)

    def test_desconhecido_nao_casa(self):
        assert not attachments.is_registered_supplier("x@acme.com", self.CADASTRO)

    def test_sem_cadastro_nada_casa(self):
        """Tabela vazia é o padrão: o app tem que se comportar como antes."""
        assert not attachments.is_registered_supplier("daniel@dhl.com.br", {})
        assert not attachments.is_registered_supplier("daniel@dhl.com.br", None)

    def test_remetente_ausente_nao_quebra(self):
        assert not attachments.is_registered_supplier(None, self.CADASTRO)
        assert not attachments.is_registered_supplier("sem-arroba", self.CADASTRO)


class TestNomeDaPasta:
    def test_cadastro_batiza_o_email_pessoal(self):
        """O caso que motivou tudo: gmail não diz que empresa é."""
        nome = attachments.supplier_for(
            "Marcio", "molivetto2@gmail.com", None,
            {"molivetto2@gmail.com": "Molivetto Tubos"},
        )

        assert nome == "Molivetto Tubos"

    def test_endereco_inteiro_ganha_do_dominio(self):
        """Tratar uma exceção dentro da empresa é um uso legítimo do cadastro."""
        nome = attachments.supplier_for(
            "Daniel", "daniel@acme.com.br", None,
            {"acme.com.br": "Acme", "daniel@acme.com.br": "Acme Divisão Tubos"},
        )

        assert nome == "Acme Divisão Tubos"

    def test_nome_do_arquivo_ainda_ganha_do_cadastro(self):
        """Num e-mail com propostas de três empresas, só o arquivo diz de quem é."""
        nome = attachments.supplier_for(
            "Emanuel", "emanuel@engeform.com.br",
            "260722 - PT - BERMAD - R00.pdf",
            {"engeform.com.br": "Engeform"},
        )

        assert nome == "BERMAD"

    def test_cadastro_sem_nome_cai_na_heuristica(self):
        """Cadastrar só para reconhecer é válido; o nome continua opcional."""
        nome = attachments.supplier_for(
            "Daniel", "daniel@dhlsaneamento.com.br", None,
            {"dhlsaneamento.com.br": None},
        )

        assert nome == "Dhlsaneamento"

    def test_sem_cadastro_o_comportamento_e_o_de_antes(self):
        assert attachments.supplier_for("Marcos", "c@aciotubos.com.br") == "Aciotubos"


def test_o_banco_antigo_ganha_a_tabela_sem_perder_dados(tmp_path):
    """Quem já usa o app atualiza sem recomeçar do zero."""
    caminho = tmp_path / "antigo.db"
    with storage.connect(caminho) as c:
        storage.add_process(c, "SUP.2026-185", "661")
    # Simula o banco de uma versão anterior, sem a tabela nova.
    with storage.connect(caminho) as c:
        c.execute("DROP TABLE suppliers")

    with storage.connect(caminho) as c:
        assert storage.list_suppliers(c) == []
        assert len(storage.list_processes(c)) == 1
