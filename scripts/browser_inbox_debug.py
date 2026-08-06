"""Mostra a estrutura real da caixa de entrada no Outlook Web (diagnóstico).

Requer ter rodado antes: python scripts/browser_login.py

Uso:
    python scripts/browser_inbox_debug.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import browser_client

if __name__ == "__main__":
    browser_client.dump_inbox_debug()
