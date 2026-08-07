"""Mostra o que a varredura já registrou, sem precisar abrir o navegador.

Uso:
    python scripts/show_results.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import storage

if __name__ == "__main__":
    with storage.connect() as connection:
        total = storage.count_messages(connection)
        processes = storage.list_processes(connection)
        matches = storage.list_messages_with_codes(connection)

        print(f"E-mails registrados: {total}")
        print(f"Processos acompanhados: {len(processes)}")
        print(f"E-mails com processo identificado: {len(matches)}\n")

        if not processes:
            print(
                "Nenhum processo cadastrado. Rode 'python scripts/processos.py' "
                "para informar os processos que você acompanha — a busca fica "
                "muito mais precisa com eles.\n"
            )

        if not matches:
            print(
                "Nenhum e-mail identificado ainda. Vale lembrar que a detecção "
                "hoje olha só assunto e preview — se o código estiver apenas "
                "dentro do anexo, ainda não é encontrado."
            )

        for match in matches:
            identified = ", ".join(
                f"{code} (via {how})"
                for code, how in zip(match["codes"], match["matched_by"])
            )
            print(f"[{identified}] {match['received_at_raw']}")
            print(f"  De: {match['sender_name']} <{match['sender_email']}>")
            print(f"  Assunto: {match['subject']}")
            if match["has_attachments"]:
                print("  (tem anexos)")
            print()
