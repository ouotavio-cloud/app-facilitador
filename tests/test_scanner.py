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
    assert "Com código de processo: 3" in lines
    assert "  SUP.2026-197: 2 e-mail(s)" in lines


def test_summary_lines_omits_code_section_when_nothing_found():
    lines = scanner.ScanResult(scanned=10).summary_lines()

    assert not any("Códigos encontrados" in line for line in lines)


def test_summary_lines_reports_errors():
    result = scanner.ScanResult(scanned=5, errors=["Assunto X: erro de leitura"])

    lines = result.summary_lines()

    assert "Itens com erro (ignorados): 1" in lines
    assert "  Assunto X: erro de leitura" in lines
