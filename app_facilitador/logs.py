"""Registro do que o app faz, num arquivo que o usuário pode me mandar.

Quando o download falha (ou qualquer coisa dá errado), o print da tela nem
sempre diz o suficiente. Um log com cada passo — abriu o e-mail, achou N
anexos, tentou baixar por tal caminho, deu certo/errado — mostra exatamente
onde travou, sem o usuário precisar reproduzir nada.

Grava na pasta de dados (`%LOCALAPPDATA%\\AppFacilitador\\app.log`), com
rotação para não crescer sem limite, e também ecoa no console do app.
"""

import logging
import logging.handlers

from app_facilitador import config

LOG_PATH = config.BASE_DIR / "app.log"

_configurado = False


def setup(verbose: bool = False) -> None:
    """Liga o log em arquivo + console. Idempotente: chamar duas vezes não
    duplica as linhas.
    """
    global _configurado
    if _configurado:
        return

    config.BASE_DIR.mkdir(parents=True, exist_ok=True)

    raiz = logging.getLogger("app_facilitador")
    raiz.setLevel(logging.DEBUG if verbose else logging.INFO)
    raiz.propagate = False

    formato = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S"
    )

    arquivo = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    arquivo.setFormatter(formato)
    raiz.addHandler(arquivo)

    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz.addHandler(console)

    _configurado = True
    raiz.info("Log iniciado em %s", LOG_PATH)


def get_logger(nome: str) -> logging.Logger:
    """Logger de um módulo, sob a árvore `app_facilitador`.

    Não chama `setup()` sozinho: se o log ainda não foi ligado (por exemplo
    num teste), as mensagens simplesmente não vão a lugar nenhum, sem erro.
    """
    return logging.getLogger(f"app_facilitador.{nome}")
