"""Ponto de entrada do App Facilitador.

Rodando pelo código-fonte: `python app.py`.
Compilado: é o que o `AppFacilitador.exe` executa.
"""

import sys


def _verificar() -> int:
    """Confere que o app consegue subir e renderizar o painel.

    Existe para a compilação testar o `.exe` gerado antes de publicá-lo:
    um executável que compila mas não acha os templates só falharia na
    máquina do usuário, que é o pior lugar para descobrir isso.
    """
    from app_facilitador.web import server

    app = server.create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        resposta = client.get("/")

    if resposta.status_code != 200:
        print(f"FALHA: o painel respondeu {resposta.status_code}")
        return 1

    if "App Facilitador" not in resposta.get_data(as_text=True):
        print("FALHA: o painel respondeu, mas sem o conteúdo esperado")
        return 1

    print("OK: o painel sobe e renderiza.")
    return 0


def _verificar_navegador() -> int:
    """Confere que o Chromium empacotado abre a partir do executável.

    Separado da verificação do painel porque falha por outros motivos: o
    driver do Playwright é um binário em Node.js, e o Chromium é uma pasta
    de ~150 MB — os dois precisam ter sido empacotados junto. Um executável
    que mostra o painel mas não abre o navegador só quebraria na hora de
    conectar ao Outlook, tarde demais.
    """
    from playwright.sync_api import sync_playwright

    from app_facilitador import browser_client

    try:
        with sync_playwright() as playwright:
            contexto = browser_client.open_browser_context(playwright, headless=True)
            pagina = browser_client.first_page(contexto)
            pagina.goto("about:blank")
            contexto.close()
    except Exception as erro:  # noqa: BLE001 - qualquer falha aqui reprova o build
        print(f"FALHA ao abrir o navegador: {erro}")
        return 1

    print("OK: o Chromium empacotado abre a partir do executável.")
    return 0


def main() -> int:
    if "--verificar-navegador" in sys.argv:
        return _verificar_navegador()

    if "--verificar" in sys.argv:
        return _verificar()

    from app_facilitador.web import server

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
