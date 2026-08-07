"""Varre uma pasta de e-mail procurando propostas e registra o que encontrar.

Requer ter rodado antes: python scripts/browser_login.py

Uso:
    python scripts/scan_inbox.py                      # Caixa de Entrada inteira
    python scripts/scan_inbox.py --limite 50          # para depois de 50 e-mails
    python scripts/scan_inbox.py --pasta "caixa real" # varre outra pasta
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import scanner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Máximo de e-mails a percorrer (padrão: a caixa inteira)",
    )
    parser.add_argument(
        "--pasta",
        default=None,
        help='Pasta a varrer, ex.: --pasta "caixa real" (padrão: Caixa de Entrada). '
        "Use scripts/list_folders.py para ver os nomes disponíveis",
    )
    parser.add_argument(
        "--sem-janela",
        action="store_true",
        help="Roda sem abrir a janela do navegador",
    )
    args = parser.parse_args()

    scanner.run_and_report(
        max_messages=args.limite, headless=args.sem_janela, folder=args.pasta
    )


if __name__ == "__main__":
    main()
