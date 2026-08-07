"""Varredura da caixa de entrada: percorre, detecta propostas e persiste.

Junta as peças — navegador (`browser_client`), detecção do código do
processo (`proposal_detector`) e estado local (`storage`) — e produz o
resumo do que foi encontrado (PLANEJAMENTO.md, Fase 4).
"""

from dataclasses import dataclass, field

from app_facilitador import browser_client, inbox_parser, proposal_detector, storage


@dataclass
class ScanResult:
    """Resumo de uma varredura, usado para o relatório final."""

    scanned: int = 0
    new_messages: int = 0
    messages_with_codes: int = 0
    codes_found: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [
            f"E-mails percorridos: {self.scanned}",
            f"Novos (ainda não registrados): {self.new_messages}",
            f"Com código de processo: {self.messages_with_codes}",
        ]
        if self.codes_found:
            lines.append("Códigos encontrados:")
            for code, count in sorted(self.codes_found.items()):
                lines.append(f"  {code}: {count} e-mail(s)")
        if self.errors:
            lines.append(f"Itens com erro (ignorados): {len(self.errors)}")
            for error in self.errors[:5]:
                lines.append(f"  {error}")
        return lines


def scan(
    max_messages: int | None = None,
    progress_every: int = 100,
    headless: bool = False,
) -> ScanResult:
    """Percorre a caixa de entrada e registra o que encontrar.

    `max_messages` limita a varredura (útil para testar sem esperar a
    caixa inteira). Um erro em um item não interrompe a varredura: é
    registrado em `ScanResult.errors` e o processamento segue (Fase 6 —
    um item problemático não pode derrubar a execução inteira).
    """
    result = ScanResult()
    last_reported = 0

    def report_progress(count: int) -> None:
        # Comparar com o último valor impresso, e não testar `count %
        # progress_every`: cada scroll traz vários e-mails de uma vez, então
        # o contador pula números e um teste de múltiplo exato quase nunca
        # dispararia.
        nonlocal last_reported
        if count - last_reported >= progress_every:
            last_reported = count
            print(f"  ... {count} e-mails percorridos")

    with storage.connect() as connection:
        with browser_client.open_inbox_session(headless=headless) as page:
            for message in browser_client.scan_inbox(
                page, max_messages=max_messages, on_progress=report_progress
            ):
                result.scanned += 1
                try:
                    codes = proposal_detector.find_proposal_codes(
                        inbox_parser.searchable_text(message)
                    )
                    if storage.save_message(connection, message, codes):
                        result.new_messages += 1
                    if codes:
                        result.messages_with_codes += 1
                        for code in codes:
                            result.codes_found[code] = result.codes_found.get(code, 0) + 1
                except Exception as error:  # noqa: BLE001 - um item ruim não pode parar a varredura
                    result.errors.append(f"{message.get('subject', '(sem assunto)')}: {error}")

    return result


def run_and_report(max_messages: int | None = None, headless: bool = False) -> ScanResult:
    """Executa a varredura e imprime o relatório final."""
    print("Abrindo a caixa de entrada...")
    result = scan(max_messages=max_messages, headless=headless)

    print("\n=== Resumo da varredura ===")
    for line in result.summary_lines():
        print(line)

    return result
