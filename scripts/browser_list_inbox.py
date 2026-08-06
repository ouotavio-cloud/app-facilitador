"""Lista os e-mails visíveis da caixa de entrada já com os campos extraídos.

Requer ter rodado antes: python scripts/browser_login.py

Uso:
    python scripts/browser_list_inbox.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import browser_client

if __name__ == "__main__":
    browser_client.print_visible_messages()
