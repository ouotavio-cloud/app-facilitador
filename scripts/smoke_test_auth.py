"""Teste manual da Fase 0: login + lista os 5 e-mails e as reuniões de hoje.

Uso:
    python scripts/smoke_test_auth.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import auth, graph_client


def main() -> None:
    print("Autenticando...")
    token = auth.get_access_token()
    print("Login OK.\n")

    print("Últimos 5 e-mails da caixa de entrada:")
    for msg in graph_client.list_recent_messages(token, top=5):
        remetente = msg.get("from", {}).get("emailAddress", {}).get("address", "?")
        print(f"  - [{msg['receivedDateTime']}] {msg['subject']} (de: {remetente})")

    print("\nReuniões de hoje:")
    events = graph_client.list_today_events(token)
    if not events:
        print("  (nenhuma reunião hoje)")
    for event in events:
        inicio = event.get("start", {}).get("dateTime", "?")
        print(f"  - [{inicio}] {event['subject']}")


if __name__ == "__main__":
    main()
