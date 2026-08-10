"""Extração de texto de PDF — o que faz achar o código dentro da proposta.

Monta um PDF mínimo válido na mão (sem depender de reportlab) só para ter
um texto real para extrair. Os casos que mais importam são os de borda: PDF
que não existe, arquivo que não é PDF, PDF quebrado — nenhum pode levantar
exceção, senão derrubaria a varredura.
"""

from app_facilitador import pdf_text


def _pdf_com_texto(texto: str) -> bytes:
    """Um PDF de uma página com `texto`, com xref e offsets corretos."""
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        None,
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    fluxo = b"BT /F1 18 Tf 20 100 Td (" + texto.encode("latin-1") + b") Tj ET"
    objs[3] = b"<</Length " + str(len(fluxo)).encode() + b">>stream\n" + fluxo + b"\nendstream"

    out = b"%PDF-1.4\n"
    offsets = []
    for i, corpo in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj" + corpo + b"endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += b"trailer<</Root 1 0 R/Size " + str(len(objs) + 1).encode() + b">>\n"
    out += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return out


def test_extrai_o_texto_de_um_pdf(tmp_path):
    arquivo = tmp_path / "proposta.pdf"
    arquivo.write_bytes(_pdf_com_texto("Proposta SUP.2026-197"))

    assert "SUP.2026-197" in pdf_text.extract_text(arquivo)


def test_arquivo_inexistente_devolve_vazio(tmp_path):
    assert pdf_text.extract_text(tmp_path / "não existe.pdf") == ""


def test_nao_pdf_devolve_vazio(tmp_path):
    planilha = tmp_path / "orcamento.xlsx"
    planilha.write_bytes(b"conteudo qualquer")

    assert pdf_text.extract_text(planilha) == ""


def test_pdf_corrompido_nao_levanta(tmp_path):
    quebrado = tmp_path / "quebrado.pdf"
    quebrado.write_bytes(b"%PDF-1.4 isto nao e um pdf de verdade")

    assert pdf_text.extract_text(quebrado) == ""
