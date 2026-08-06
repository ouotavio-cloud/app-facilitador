"""Teste de diagnóstico: o tenant permite login IMAP com usuário/senha?

A Microsoft desativou por padrão o "Basic Auth" (usuário/senha) em contas
corporativas do Microsoft 365 desde 2022 — este script só confirma se essa
sua conta é uma exceção. Não salva nem envia a senha a lugar nenhum além
do servidor da própria Microsoft (conexão IMAP com TLS).

Uso:
    python scripts/test_imap.py
"""

import getpass
import imaplib

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993


def main() -> None:
    email = input("Seu e-mail: ").strip()
    senha = getpass.getpass("Sua senha: ")

    print(f"Conectando em {IMAP_HOST}:{IMAP_PORT}...")
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        conn.login(email, senha)
    except imaplib.IMAP4.error as exc:
        print("\nFALHOU. O servidor recusou o login IMAP:")
        print(f"  {exc}")
        print(
            "\nIsso confirma que a Microsoft bloqueou login usuário/senha "
            "(Basic Auth) nesse tenant. IMAP não é um caminho viável aqui."
        )
        return
    except OSError as exc:
        print(f"\nFalha de conexão de rede: {exc}")
        return

    print("\nSUCESSO! Login IMAP funcionou. Pastas disponíveis:")
    status, folders = conn.list()
    for folder in folders:
        print(f"  {folder.decode(errors='replace')}")
    conn.logout()


if __name__ == "__main__":
    main()
