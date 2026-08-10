from app_facilitador import scanner


def test_summary_lines_reports_counts():
    result = scanner.ScanResult(
        scanned=120,
        new_messages=8,
        messages_with_codes=3,
        codes_found={"SUP.2026-197": 2, "SUP.2026-198": 1},
    )

    lines = result.summary_lines()

    assert "E-mails percorridos: 120" in lines
    assert "Novos (ainda não registrados): 8" in lines
    assert "Com processo identificado: 3" in lines
    assert "  SUP.2026-197: 2 e-mail(s)" in lines


def test_summary_lines_separates_unknown_codes():
    """Um código não cadastrado é pendência do usuário, não um resultado."""
    result = scanner.ScanResult(
        scanned=50,
        codes_found={"SUP.2026-197": 1},
        unknown_codes={"SUP.2026-500": 2},
    )

    lines = result.summary_lines()

    assert "Códigos vistos mas NÃO cadastrados (vale conferir):" in lines
    assert "  SUP.2026-500: 2 e-mail(s)" in lines


def test_summary_lines_reports_how_many_processes_are_tracked():
    lines = scanner.ScanResult(scanned=10, processes_tracked=4).summary_lines()

    assert "Processos acompanhados: 4" in lines


def test_summary_lines_omits_code_section_when_nothing_found():
    lines = scanner.ScanResult(scanned=10).summary_lines()

    assert not any("Códigos encontrados" in line for line in lines)


def test_summary_lines_names_the_scanned_folder():
    lines = scanner.ScanResult(scanned=10, folder="caixa real").summary_lines()

    assert "Pasta: caixa real" in lines


def test_summary_lines_defaults_to_inbox_when_no_folder_given():
    lines = scanner.ScanResult(scanned=10).summary_lines()

    assert "Pasta: Caixa de Entrada" in lines


def test_summary_lines_reports_errors():
    result = scanner.ScanResult(scanned=5, errors=["Assunto X: erro de leitura"])

    lines = result.summary_lines()

    assert "Itens com erro (ignorados): 1" in lines
    assert "  Assunto X: erro de leitura" in lines


def test_summary_lines_flags_a_stopped_scan():
    """Parar não é falha: o resultado parcial vale, mas o usuário precisa saber."""
    result = scanner.ScanResult(scanned=42, stopped=True)

    lines = result.summary_lines()

    assert lines[0].startswith("Varredura interrompida por você")
    assert "E-mails percorridos: 42" in lines


class TestUnpinResult:
    """Resumo da busca de e-mails fixados (ver `scanner.unpin_all`)."""

    def test_reports_counts(self):
        lines = scanner.UnpinResult(
            scanned=30, pinned_found=4, unpinned=3
        ).summary_lines()

        assert "E-mails percorridos: 30" in lines
        assert "Fixados encontrados: 4" in lines
        assert "Desafixados: 3" in lines

    def test_lists_the_ones_it_could_not_identify(self):
        lines = scanner.UnpinResult(
            pinned_found=2, unpinned=1, not_identified=["Proposta X"]
        ).summary_lines()

        assert any("1 e-mail(s)" in line for line in lines)
        assert "  Proposta X" in lines

    def test_says_nothing_was_left_unidentified(self):
        """Sem sobra, o usuário não precisa ir conferir nada à mão."""
        lines = scanner.UnpinResult(pinned_found=2, unpinned=2).summary_lines()

        assert "Nenhum e-mail fixado sobrou por identificar." in lines

    def test_omits_that_line_when_nothing_was_pinned(self):
        """Sem nenhum fixado, dizer 'nada sobrou' seria ruído, não notícia."""
        lines = scanner.UnpinResult(scanned=10).summary_lines()

        assert "Nenhum e-mail fixado sobrou por identificar." not in lines

    def test_flags_a_stopped_search(self):
        lines = scanner.UnpinResult(scanned=10, stopped=True).summary_lines()

        assert lines[0].startswith("Busca interrompida por você")
