# Receita de empacotamento do App Facilitador (PyInstaller).
#
# Gera um único `AppFacilitador.exe` que roda sem Python instalado, sem
# `pip install` e sem `playwright install` — o pedido era poder baixar e
# usar, sem preparar nada antes.
#
# Duas coisas exigem cuidado especial aqui:
#
# 1. O Playwright não é um pacote Python puro: ele embute um driver em
#    Node.js dentro da própria pasta do pacote. `collect_all` traz esses
#    arquivos junto — sem isso o executável compila, mas quebra na
#    primeira tentativa de abrir o navegador.
#
# 2. Templates e CSS são lidos do disco em tempo de execução, então
#    precisam ser declarados como dados. O código os procura via
#    `app_facilitador/paths.py`, que sabe achá-los tanto no executável
#    quanto rodando pelo código-fonte.
#
# Nenhum navegador é embutido: o app usa o Edge já instalado no Windows
# (ver `_BROWSER_CHANNELS` em browser_client.py), o que evita somar uns
# 150 MB ao download.

from PyInstaller.utils.hooks import collect_all

playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=playwright_binaries,
    datas=[
        ("app_facilitador/web/templates", "app_facilitador/web/templates"),
        ("app_facilitador/web/static", "app_facilitador/web/static"),
        *playwright_datas,
    ],
    hiddenimports=[
        *playwright_hiddenimports,
        # O Flask carrega estes por caminho indireto; sem declarar, o
        # PyInstaller não os enxerga na análise estática.
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
    a.binaries,
    a.datas,
    [],
    name="AppFacilitador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # Com console: se algo falhar ao abrir, o usuário consegue ler o erro
    # e me mandar. Numa janela sem console a falha seria silenciosa.
    console=True,
    disable_windowed_traceback=False,
    icon="app_facilitador/web/static/icone.ico",
)
