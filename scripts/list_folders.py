"""Lista as pastas de e-mail disponíveis, com o nome exato a usar em --pasta.

Requer ter rodado antes: python scripts/browser_login.py

Uso:
    python scripts/list_folders.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import browser_client

if __name__ == "__main__":
    with browser_client.open_inbox_session() as page:
        folders = browser_client.list_folders(page)
        if not folders:
            print(
                "Nenhuma pasta encontrada no painel de navegação. "
                "Rode scripts/browser_inbox_debug.py para inspecionar a tela."
            )
        else:
            print(f"{len(folders)} pastas encontradas:\n")
            for name in folders:
                print(f'  --pasta "{name}"')
