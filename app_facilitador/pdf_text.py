"""Extração do texto de um PDF, para achar o código do processo dentro dele.

O código de uma cotação às vezes só aparece dentro da proposta, não no
assunto nem no corpo do e-mail. Ler o texto do PDF fecha esse buraco.

É melhor-esforço de propósito: PDF escaneado (imagem sem camada de texto)
devolve vazio, e um PDF corrompido ou protegido não pode derrubar a
varredura. Em qualquer erro, devolvemos o que já deu — nunca uma exceção.

OCR (ler texto de PDF que é só imagem) fica de fora: exigiria um motor
pesado no bundle, e a maioria das propostas é PDF com texto de verdade.
"""

from pathlib import Path

# Teto de páginas lidas. O código do processo, quando está no PDF, fica na
# capa ou no cabeçalho — ler o documento inteiro (que pode ter dezenas de
# páginas de desenho técnico) gastaria tempo à toa.
_MAX_PAGES = 15


def extract_text(path: str | Path, max_pages: int = _MAX_PAGES) -> str:
    """Texto das primeiras páginas do PDF, ou "" se não der para ler.

    Só lê `.pdf`: os outros formatos de proposta (planilha, Word) pedem
    bibliotecas próprias e ficam para depois, se fizerem falta.
    """
    caminho = Path(path)
    if caminho.suffix.lower() != ".pdf" or not caminho.exists():
        return ""

    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001 - sem a lib, seguimos sem ler PDF
        return ""

    try:
        reader = PdfReader(str(caminho))
        paginas = reader.pages[:max_pages]
        partes = []
        for pagina in paginas:
            try:
                partes.append(pagina.extract_text() or "")
            except Exception:  # noqa: BLE001 - uma página ruim não perde as outras
                continue
        return "\n".join(partes).strip()
    except Exception:  # noqa: BLE001 - PDF protegido/corrompido: melhor vazio que quebrar
        return ""
