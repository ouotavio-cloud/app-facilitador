# Receita de empacotamento do App Facilitador (PyInstaller).
#
# Gera uma pasta `AppFacilitador` com o `AppFacilitador.exe` dentro, que
# roda sem Python instalado, sem `pip install` e sem `playwright install`
# — o pedido era poder baixar e usar, sem preparar nada antes.
#
# **Pasta, e não arquivo único.** O Chromium vai junto e sozinho pesa uns
# 150 MB. No modo arquivo único o PyInstaller descompacta tudo numa pasta
# temporária a cada abertura: seriam uns 15 segundos de espera toda vez
# que o usuário abrisse o app, todos os dias. A pasta abre na hora.
#
# Três coisas exigem cuidado especial aqui:
#
# 1. O Playwright não é um pacote Python puro: ele embute um driver em
#    Node.js dentro da própria pasta do pacote. `collect_all` traz esses
#    arquivos junto — sem isso o executável compila, mas quebra na
#    primeira tentativa de abrir o navegador.
#
# 2. O Chromium em si é baixado à parte, para `pw-browsers/`, pelo
#    `playwright install` que a compilação roda antes. Ele entra como
#    dado e é encontrado em tempo de execução via a variável
#    PLAYWRIGHT_BROWSERS_PATH (ver `paths.configure_playwright_browsers`).
#    Usamos o Chromium, e não o Edge do Windows, porque o Edge não
#    preservava a conta entre execuções na máquina do usuário.
#
# 3. Templates e CSS são lidos do disco em tempo de execução, então
#    precisam ser declarados como dados. O código os procura via
#    `app_facilitador/paths.py`, que sabe achá-los tanto no executável
#    quanto rodando pelo código-fonte.

import os

from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")

# O Chromium só existe aqui depois de:
#     PLAYWRIGHT_BROWSERS_PATH=./pw-browsers playwright install chromium
# Sem ele a compilação ainda funciona, mas gera um app que abre o painel e
# falha ao conectar no Outlook. Avisamos alto em vez de falhar: quem está
# testando só a interface não precisa baixar 150 MB.
navegador_datas = []
if os.path.isdir("pw-browsers"):
    navegador_datas.append(("pw-browsers", "playwright-browsers"))
else:
    print(
        "\n*** AVISO: pw-browsers/ não existe — o app sairá SEM navegador. "
        "Rode `playwright install chromium` com PLAYWRIGHT_BROWSERS_PATH "
        "apontando para ./pw-browsers antes de compilar para distribuir. ***\n"
    )

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=playwright_binaries,
    datas=[
        ("app_facilitador/web/templates", "app_facilitador/web/templates"),
        ("app_facilitador/web/static", "app_facilitador/web/static"),
        *navegador_datas,
        *playwright_datas,
    ],
    hiddenimports=[
        *playwright_hiddenimports,
        # O Flask carrega este por caminho indireto; sem declarar, o
        # PyInstaller não o enxerga na análise estática.
        "jinja2.ext",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Peso morto: o app não abre janela nativa nem roda testes.
        # `unittest` fica de fora da lista de propósito — bibliotecas o
        # importam por caminhos indiretos, e economizar esses KB não
        # compensa arriscar um executável que quebra só em produção.
        "tkinter",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AppFacilitador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Com console: se algo falhar ao abrir, o usuário consegue ler o erro
    # e me mandar. Numa janela sem console a falha seria silenciosa.
    console=True,
    disable_windowed_traceback=False,
    icon="app_facilitador/web/static/icone.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AppFacilitador",
)
