"""Localização da pasta real da obra/RFQ/fornecedor no OneDrive.

Usa pastas de verdade em `tmp_path`, montadas do jeito que o usuário
mantém na prática: `__14. OBRAS / <NN.NNN - NNN NOME> / 04. RFQs /
<SUP.AAAA-NNN - ASSUNTO> / 3. PROPOSTAS TÉCNICA E COMERCIAL / FORNECEDOR`.
"""

from app_facilitador import obra_folders


def _montar_arvore(base, numero_obra="659", nome_obra="ETA ITABIRA", codigo="SUP.2026-049",
                    assunto="CABOS", fornecedores=("CABELAUTO", "COPERCABOS")):
    obra = base / f"25.001 - {numero_obra} {nome_obra}"
    rfqs = obra / "04. RFQs"
    rfq = rfqs / f"{codigo} - {assunto}"
    propostas = rfq / "3. PROPOSTAS TÉCNICA E COMERCIAL"
    for fornecedor in fornecedores:
        (propostas / fornecedor).mkdir(parents=True)
    return obra, rfq, propostas


def test_find_obra_dir_pelo_numero(tmp_path):
    obra, _, _ = _montar_arvore(tmp_path)
    (tmp_path / "20.004 - 610 UR Pirajussara").mkdir()

    assert obra_folders.find_obra_dir(tmp_path, "659") == obra


def test_find_obra_dir_nao_casa_numero_dentro_de_outro(tmp_path):
    """"659" não pode casar com uma pasta "6590" ou "25.659"."""
    (tmp_path / "25.659 - 6590 OUTRA OBRA").mkdir()

    assert obra_folders.find_obra_dir(tmp_path, "659") is None


def test_find_obra_dir_sem_pasta_correspondente(tmp_path):
    (tmp_path / "20.004 - 610 UR Pirajussara").mkdir()

    assert obra_folders.find_obra_dir(tmp_path, "659") is None


def test_find_rfq_dir_pelo_codigo(tmp_path):
    obra, rfq, _ = _montar_arvore(tmp_path)

    assert obra_folders.find_rfq_dir(obra, "SUP.2026-049") == rfq


def test_find_rfq_dir_ignora_caixa_e_acha_pelo_comeco_do_nome(tmp_path):
    obra, rfq, _ = _montar_arvore(tmp_path, codigo="SUP.2026-049", assunto="CABOS DE MEDIA TENSAO")

    assert obra_folders.find_rfq_dir(obra, "sup.2026-049") == rfq


def test_find_rfq_dir_sem_rfq_correspondente(tmp_path):
    obra, _, _ = _montar_arvore(tmp_path, codigo="SUP.2026-049")

    assert obra_folders.find_rfq_dir(obra, "SUP.2026-999") is None


def test_find_supplier_dir_usa_pasta_existente_ignorando_caixa(tmp_path):
    _, _, propostas = _montar_arvore(tmp_path, fornecedores=("CABELAUTO",))

    achado = obra_folders.find_supplier_dir(propostas.parent, "Cabelauto")

    assert achado == propostas / "CABELAUTO"


def test_find_supplier_dir_sem_pasta_existente_propoe_uma_nova(tmp_path):
    _, rfq, propostas = _montar_arvore(tmp_path, fornecedores=("CABELAUTO",))

    achado = obra_folders.find_supplier_dir(rfq, "Fornecedor Novo")

    assert achado == propostas / "Fornecedor Novo"
    assert not achado.exists()  # a pasta não é criada por esta função


def test_resolve_destination_caminho_completo(tmp_path):
    _montar_arvore(tmp_path, fornecedores=("CABELAUTO",))

    destino = obra_folders.resolve_destination(tmp_path, "659", "SUP.2026-049", "CABELAUTO")

    assert destino == tmp_path / "25.001 - 659 ETA ITABIRA" / "04. RFQs" / "SUP.2026-049 - CABOS" / "3. PROPOSTAS TÉCNICA E COMERCIAL" / "CABELAUTO"


def test_resolve_destination_sem_base_configurada():
    assert obra_folders.resolve_destination(None, "659", "SUP.2026-049", "CABELAUTO") is None


def test_resolve_destination_sem_numero_de_obra(tmp_path):
    _montar_arvore(tmp_path)

    assert obra_folders.resolve_destination(tmp_path, None, "SUP.2026-049", "CABELAUTO") is None


def test_resolve_destination_obra_nao_encontrada(tmp_path):
    _montar_arvore(tmp_path)

    assert obra_folders.resolve_destination(tmp_path, "999", "SUP.2026-049", "CABELAUTO") is None


def test_resolve_destination_rfq_nao_encontrado(tmp_path):
    _montar_arvore(tmp_path)

    assert obra_folders.resolve_destination(tmp_path, "659", "SUP.2026-999", "CABELAUTO") is None
