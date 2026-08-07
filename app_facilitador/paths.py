"""Onde ficam os arquivos do app — em código-fonte e no executável.

Rodando pelo código-fonte, tudo mora na pasta do projeto e é prático.
Dentro do `.exe` gerado pelo PyInstaller isso não funciona: o modo
"arquivo único" descompacta o programa numa pasta temporária que o
Windows apaga ao fechar. Se o banco e a sessão do Outlook fossem
gravados lá, o usuário perderia o login e todos os processos cadastrados
a cada vez que fechasse o app.

Por isso separamos duas coisas que costumam ser confundidas:

- **recursos** (templates, CSS, ícone): vêm empacotados junto do
  programa, são somente leitura e mudam a cada nova versão;
- **dados** (banco, sessão, cache): pertencem ao usuário, precisam
  sobreviver a atualizações e por isso vão para a pasta de dados da
  conta no Windows.
"""

import os
import sys
from pathlib import Path

APP_FOLDER_NAME = "AppFacilitador"


def is_frozen() -> bool:
    """True quando rodando de dentro do executável gerado pelo PyInstaller."""
    return getattr(sys, "frozen", False)


def resource_dir() -> Path:
    """Pasta dos arquivos que acompanham o programa (templates, estáticos).

    No executável, o PyInstaller descompacta tudo em `sys._MEIPASS`.
    """
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Pasta onde o app grava o que é do usuário, criada se não existir.

    A variável `APP_FACILITADOR_DATA` tem precedência para permitir testes
    e uso em pendrive sem tocar no perfil do Windows.
    """
    override = os.environ.get("APP_FACILITADOR_DATA")
    if override:
        directory = Path(override)
    elif is_frozen():
        directory = _user_data_root() / APP_FOLDER_NAME
    else:
        # Pelo código-fonte, na própria pasta do projeto: quem está
        # desenvolvendo espera ver o banco ao lado do código.
        directory = Path(__file__).resolve().parent.parent

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _user_data_root() -> Path:
    """Raiz dos dados de aplicativo do usuário, conforme o sistema."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data)
    # Linux/Mac (e Windows sem a variável, que não deveria acontecer).
    return Path.home() / ".local" / "share"
