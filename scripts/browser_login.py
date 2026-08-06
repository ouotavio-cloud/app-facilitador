"""Login manual único no Outlook Web — salva a sessão para reaproveitar depois.

Uso:
    python scripts/browser_login.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import browser_client

if __name__ == "__main__":
    browser_client.login_and_save_session()
