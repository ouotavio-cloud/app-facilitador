"""Cadastra os processos de cotação que você está acompanhando.

A varredura procura cada processo de duas formas — pelo código e pelo
nome da obra — então informar os dois aumenta a chance de encontrar o
e-mail mesmo quando o fornecedor escreve o código de forma inesperada.

Uso:
    python scripts/processos.py                    # modo interativo
    python scripts/processos.py --listar
    python scripts/processos.py --remover SUP.2026-197
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_facilitador import proposal_detector, storage


def _print_processes(connection) -> None:
    processes = storage.list_processes(connection)
    if not processes:
        print("Nenhum processo cadastrado ainda.")
        return

    print(f"{len(processes)} processo(s) acompanhado(s):\n")
    for process in processes:
        obra = process["obra"] or "(sem obra informada)"
        print(f"  {process['code']} — {obra}")


def _prompt_new_processes(connection) -> None:
    print("Cadastro de processos de cotação (Enter vazio para terminar).\n")

    added = 0
    while True:
        code_input = input("Código do processo (ex.: SUP.2026-197): ").strip()
        if not code_input:
            break

        # Normaliza o que foi digitado para o mesmo formato que a busca usa,
        # senão um cadastro escrito "sup 2026 197" nunca casaria com o
        # código encontrado no e-mail.
        codes = proposal_detector.find_proposal_codes(code_input)
        if not codes:
            print(
                "  Não reconheci esse código. Use o formato SUP.AAAA-NNN "
                "(ex.: SUP.2026-197).\n"
            )
            continue

        code = codes[0]
        obra = input(f"Nome da obra de {code} (opcional): ").strip() or None

        storage.add_process(connection, code, obra)
        added += 1
        print(f"  Cadastrado: {code} — {obra or '(sem obra)'}\n")

    if added:
        print(f"{added} processo(s) cadastrado(s).\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listar", action="store_true", help="Só lista os processos")
    parser.add_argument("--remover", metavar="CODIGO", help="Remove um processo")
    args = parser.parse_args()

    with storage.connect() as connection:
        if args.remover:
            if storage.remove_process(connection, args.remover):
                print(f"Removido: {args.remover}")
            else:
                print(f"Não encontrei o processo {args.remover}.")
            return

        if args.listar:
            _print_processes(connection)
            return

        _print_processes(connection)
        print()
        _prompt_new_processes(connection)
        _print_processes(connection)


if __name__ == "__main__":
    main()
