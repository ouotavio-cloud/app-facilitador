"""Varredura da caixa de entrada: percorre, detecta propostas e persiste.

Junta as peças — navegador (`browser_client`), detecção do código do
processo (`proposal_detector`) e estado local (`storage`) — e produz o
resumo do que foi encontrado (PLANEJAMENTO.md, Fase 4).
"""

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app_facilitador import attachments, browser_client, config, inbox_parser
from app_facilitador import pdf_text, proposal_detector, storage

# Extensões procuradas nos anexos, na forma que o JavaScript da busca
# espera. Vem de `attachments` para não haver duas listas divergindo.
_EXTENSIONS = attachments.DOCUMENT_EXTENSIONS

# Nome gravado para os e-mails varridos sem pasta explícita — o Outlook
# abre na Caixa de Entrada. Guardar o nome, em vez de deixar nulo, permite
# filtrar por pasta no painel sem tratar o caso padrão como exceção.
DEFAULT_FOLDER_NAME = "Caixa de Entrada"


@dataclass
class ScanResult:
    """Resumo de uma varredura, usado para o relatório final."""

    scanned: int = 0
    new_messages: int = 0
    messages_with_codes: int = 0
    codes_found: dict[str, int] = field(default_factory=dict)
    unknown_codes: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    folder: str | None = None
    processes_tracked: int = 0
    downloaded: int = 0
    download_failures: int = 0
    # Códigos descobertos lendo o corpo do e-mail ou o texto do PDF, que não
    # apareciam no assunto/preview. É o ganho da leitura de conteúdo.
    codes_in_content: int = 0
    # Propostas achadas pela varredura profunda: e-mails que não casavam por
    # assunto/obra, mas cujo corpo/anexo revelou um processo cadastrado.
    deep_matches: int = 0
    stopped: bool = False
    # Caminho de um HTML do painel de leitura salvo quando um download
    # falha — é o que permite calibrar os seletores sem outra compilação.
    debug_dump: str | None = None

    def summary_lines(self) -> list[str]:
        lines = []
        if self.stopped:
            lines.append("Varredura interrompida por você — resultado parcial:")
        lines.append(f"Pasta: {self.folder or 'Caixa de Entrada'}")
        lines += [
            f"Processos acompanhados: {self.processes_tracked}",
            f"E-mails percorridos: {self.scanned}",
            f"Novos (ainda não registrados): {self.new_messages}",
            f"Com processo identificado: {self.messages_with_codes}",
            f"Propostas baixadas: {self.downloaded}",
        ]
        if self.deep_matches:
            lines.append(
                f"Propostas achadas pela leitura de corpo/anexo: {self.deep_matches}"
            )
        if self.codes_in_content:
            lines.append(
                f"Códigos que só apareciam no corpo/anexo: {self.codes_in_content}"
            )
        if self.download_failures:
            lines.append(f"Anexos que não deu para baixar: {self.download_failures}")
            if self.debug_dump:
                lines.append(
                    "Para eu consertar o download, me envie este arquivo: "
                    f"{self.debug_dump}"
                )
        if self.codes_found:
            lines.append("Processos encontrados:")
            for code, count in sorted(self.codes_found.items()):
                lines.append(f"  {code}: {count} e-mail(s)")
        if self.unknown_codes:
            lines.append("Códigos vistos mas NÃO cadastrados (vale conferir):")
            for code, count in sorted(self.unknown_codes.items()):
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
    folder: str | None = None,
    on_progress: Callable[[int], None] | None = None,
    download_attachments: bool = True,
    should_stop: Callable[[], bool] | None = None,
    deep_scan: bool = False,
) -> ScanResult:
    """Percorre uma pasta de e-mail e registra o que encontrar.

    `folder` escolhe a pasta a varrer (padrão: a Caixa de Entrada). Vale
    tanto para pastas do Outlook quanto para pastas criadas pelo usuário.
    `max_messages` limita a varredura (útil para testar sem esperar a
    caixa inteira). `on_progress` recebe a contagem a cada rodada — o app
    usa isso para mostrar o andamento na tela; sem ele, o progresso vai
    para o terminal. Um erro em um item não interrompe a varredura: é
    registrado em `ScanResult.errors` e o processamento segue (Fase 6 —
    um item problemático não pode derrubar a execução inteira).

    `download_attachments` baixa a proposta anexada dos e-mails que casam
    com um processo cadastrado. Fica ligado por padrão porque é o que o
    usuário pediu, mas é desligável: baixar exige **abrir** cada e-mail,
    e abrir o marca como lido no Outlook.

    `should_stop`, quando devolve True, encerra a varredura de forma limpa
    e devolve o resultado parcial (`ScanResult.stopped`). É o que o botão
    "Parar" da tela usa para o usuário abortar sem fechar o app.

    `deep_scan` liga a varredura profunda: e-mails com anexo que não casaram
    pelo assunto/obra são abertos para ler o corpo e o texto do anexo,
    caçando o código escrito só ali. Fica desligado por padrão porque abrir
    marca como lido no Outlook — com ele ligado, muitos e-mails são abertos,
    não só os já identificados.
    """
    result = ScanResult(folder=folder)
    last_reported = 0

    def print_progress(count: int) -> None:
        # Comparar com o último valor impresso, e não testar `count %
        # progress_every`: cada scroll traz vários e-mails de uma vez, então
        # o contador pula números e um teste de múltiplo exato quase nunca
        # dispararia.
        nonlocal last_reported
        if count - last_reported >= progress_every:
            last_reported = count
            print(f"  ... {count} e-mails percorridos")

    report_progress = on_progress if on_progress is not None else print_progress

    with storage.connect() as connection:
        processes = storage.list_processes(connection)
        result.processes_tracked = len(processes)
        # Ciente do disco: se o usuário apagou uma proposta da pasta, ela
        # não conta como baixada e a varredura a traz de volta.
        ja_baixados = storage.downloaded_conversations_on_disk(connection)
        pasta_propostas = proposals_dir(connection)

        with browser_client.open_inbox_session(headless=headless) as page:
            if folder is not None:
                browser_client.open_folder(page, folder)

            for message in browser_client.scan_inbox(
                page,
                max_messages=max_messages,
                on_progress=report_progress,
                should_stop=should_stop,
            ):
                if should_stop is not None and should_stop():
                    result.stopped = True
                    break
                result.scanned += 1
                try:
                    matches = _process_message(
                        connection, message, processes, result, folder
                    )
                except Exception as error:  # noqa: BLE001 - um item ruim não pode parar a varredura
                    result.errors.append(f"{message.get('subject', '(sem assunto)')}: {error}")
                    continue

                if not (download_attachments or deep_scan):
                    continue
                if message["conv_id"] in ja_baixados:
                    continue
                if not message.get("has_attachments"):
                    continue

                try:
                    if matches and download_attachments:
                        _download_proposal(
                            page, connection, message, matches, processes,
                            pasta_propostas, result,
                        )
                    elif deep_scan and not matches:
                        _deep_scan_message(
                            page, connection, message, processes,
                            pasta_propostas, result,
                        )
                except Exception as error:  # noqa: BLE001 - idem: não derruba a varredura
                    result.errors.append(
                        f"anexo de {message.get('subject', '(sem assunto)')}: {error}"
                    )

    return result


def proposals_dir(connection) -> Path:
    """Pasta escolhida pelo usuário para arquivar as propostas."""
    escolhida = storage.get_setting(connection, config.PROPOSALS_DIR_SETTING)
    return Path(escolhida) if escolhida else config.DEFAULT_PROPOSALS_DIR


def _process_message(
    connection,
    message: dict,
    processes: list[dict],
    result: ScanResult,
    folder: str | None,
) -> list[dict]:
    """Grava a mensagem e devolve os processos cadastrados que ela cita."""
    text = inbox_parser.searchable_text(message)

    matches = proposal_detector.match_known_processes(text, processes)
    unknown = proposal_detector.find_unknown_codes(text, processes)

    matched_by = {match["code"]: ", ".join(match["matched_by"]) for match in matches}
    codes = list(matched_by) + unknown

    if storage.save_message(
        connection,
        message,
        codes,
        matched_by=matched_by,
        folder=folder or DEFAULT_FOLDER_NAME,
    ):
        result.new_messages += 1

    if matches:
        result.messages_with_codes += 1
        for match in matches:
            code = match["code"]
            result.codes_found[code] = result.codes_found.get(code, 0) + 1

    for code in unknown:
        result.unknown_codes[code] = result.unknown_codes.get(code, 0) + 1

    return matches


def _download_proposal(
    page,
    connection,
    message: dict,
    matches: list[dict],
    processes: list[dict],
    base_dir: Path,
    result: ScanResult,
) -> None:
    """Abre um e-mail identificado como proposta, baixa os anexos e enriquece.

    Abrir marca a mensagem como lida no Outlook — por isso só e-mails já
    casados com um processo cadastrado chegam aqui (a varredura profunda,
    que abre mais, é opt-in).
    """
    if not browser_client.open_message(page, message["conv_id"]):
        result.errors.append(
            f"não consegui abrir o e-mail de {message.get('sender_name')} "
            f"para pegar o anexo"
        )
        return

    codigo = matches[0]["code"]
    obra = next((p["obra"] for p in processes if p["code"] == codigo), None)
    fornecedor = attachments.supplier_folder(
        message.get("sender_name"), message.get("sender_email")
    )

    baixados = _baixar_anexos_abertos(
        page, connection, message, codigo, obra, fornecedor, base_dir, result
    )
    # Depois de baixar, lê o corpo e o texto dos PDFs para achar códigos que
    # não estavam no assunto — reforça a confiança e pega processos citados
    # só no conteúdo.
    _enriquecer_pelo_conteudo(page, connection, message, processes, baixados, result)


def _baixar_anexos_abertos(
    page,
    connection,
    message: dict,
    codigo: str,
    obra: str | None,
    fornecedor: str,
    base_dir: Path,
    result: ScanResult,
) -> list[Path]:
    """Baixa e arquiva os anexos-documento do e-mail já aberto.

    Devolve os caminhos gravados, para o enriquecimento ler o texto deles.
    """
    arquivos = [
        nome
        for nome in browser_client.find_attachments(page, sorted(_EXTENSIONS))
        if attachments.is_document(nome)
    ]
    if not arquivos:
        # O e-mail dizia ter anexo, mas nenhum é documento — assinatura ou
        # imagem embutida. Não é erro, é o filtro funcionando.
        return []

    destino_dir = attachments.proposal_dir(base_dir, obra, codigo, fornecedor)
    destino_dir.mkdir(parents=True, exist_ok=True)

    gravados: list[Path] = []
    for nome in arquivos:
        destino = attachments.unique_path(
            destino_dir / attachments.proposal_file_name(fornecedor, nome)
        )
        baixou = browser_client.download_attachment(page, nome, destino)

        storage.record_attachment(
            connection,
            conv_id=message["conv_id"],
            filename=nome,
            path=str(destino) if baixou else None,
            code=codigo,
            supplier=fornecedor,
            error=None if baixou else "não foi possível baixar pelo Outlook",
        )

        if baixou:
            result.downloaded += 1
            gravados.append(destino)
        else:
            result.download_failures += 1
            _salvar_diagnostico(page, result)

    return gravados


def _enriquecer_pelo_conteudo(
    page,
    connection,
    message: dict,
    processes: list[dict],
    pdf_paths: list[Path],
    result: ScanResult,
) -> None:
    """Lê corpo do e-mail + texto dos PDFs e adiciona os códigos achados ali.

    Fecha o buraco do código que não aparece no assunto: o fornecedor
    escreve "segue proposta da SUP.2026-197" no corpo, ou o código só está
    dentro do PDF. Os códigos novos entram na mensagem com a pista
    "conteúdo", e os desconhecidos viram pendência como qualquer outro.
    """
    textos = [browser_client.read_message_body(page)]
    textos += [pdf_text.extract_text(caminho) for caminho in pdf_paths]
    texto = " ".join(t for t in textos if t).strip()
    if not texto:
        return

    matches = proposal_detector.match_known_processes(texto, processes)
    unknown = proposal_detector.find_unknown_codes(texto, processes)

    conhecidos = {m["code"] for m in matches}
    achados: dict[str, str | None] = {code: "conteúdo" for code in conhecidos}
    achados.update({code: None for code in unknown})

    novos = storage.add_message_codes(connection, message["conv_id"], achados)
    for code in novos:
        if code in conhecidos:
            result.codes_in_content += 1
            result.codes_found[code] = result.codes_found.get(code, 0) + 1
        else:
            result.unknown_codes[code] = result.unknown_codes.get(code, 0) + 1


def _deep_scan_message(
    page,
    connection,
    message: dict,
    processes: list[dict],
    base_dir: Path,
    result: ScanResult,
) -> None:
    """Varredura profunda: abre um e-mail não identificado e caça o código
    no corpo e dentro do anexo.

    É o que pega a proposta cujo código não está no assunto nem no preview.
    Baixa os anexos para uma pasta temporária só para ler o texto; se nada
    casar com um processo cadastrado, os temporários somem e nada é
    arquivado. Se casar, os arquivos vão para a árvore definitiva.
    """
    if not browser_client.open_message(page, message["conv_id"]):
        return

    arquivos = [
        nome
        for nome in browser_client.find_attachments(page, sorted(_EXTENSIONS))
        if attachments.is_document(nome)
    ]
    if not arquivos:
        return

    corpo = browser_client.read_message_body(page)

    with tempfile.TemporaryDirectory() as tmp:
        baixados: list[tuple[str, Path]] = []
        textos_pdf: list[str] = []
        for nome in arquivos:
            alvo = Path(tmp) / attachments.file_name_for(nome)
            if browser_client.download_attachment(page, nome, alvo):
                baixados.append((nome, alvo))
                textos_pdf.append(pdf_text.extract_text(alvo))

        texto = " ".join(
            t
            for t in ([inbox_parser.searchable_text(message), corpo] + textos_pdf)
            if t
        ).strip()
        matches = proposal_detector.match_known_processes(texto, processes)
        if not matches:
            return  # não é proposta de processo cadastrado; o tempdir some

        codigo = matches[0]["code"]
        obra = next((p["obra"] for p in processes if p["code"] == codigo), None)
        fornecedor = attachments.supplier_folder(
            message.get("sender_name"), message.get("sender_email")
        )

        result.deep_matches += 1
        novos = storage.add_message_codes(
            connection, message["conv_id"], {m["code"]: "conteúdo" for m in matches}
        )
        result.codes_in_content += len(novos)
        result.messages_with_codes += 1
        for match in matches:
            result.codes_found[match["code"]] = (
                result.codes_found.get(match["code"], 0) + 1
            )

        destino_dir = attachments.proposal_dir(base_dir, obra, codigo, fornecedor)
        destino_dir.mkdir(parents=True, exist_ok=True)
        for nome, tmp_path in baixados:
            destino = attachments.unique_path(
                destino_dir / attachments.proposal_file_name(fornecedor, nome)
            )
            try:
                shutil.move(str(tmp_path), str(destino))
                gravou = True
            except Exception:  # noqa: BLE001 - falha ao mover não pode derrubar a varredura
                gravou = False

            storage.record_attachment(
                connection,
                conv_id=message["conv_id"],
                filename=nome,
                path=str(destino) if gravou else None,
                code=codigo,
                supplier=fornecedor,
                error=None if gravou else "não foi possível salvar o anexo",
            )
            if gravou:
                result.downloaded += 1
            else:
                result.download_failures += 1


def _salvar_diagnostico(page, result: ScanResult) -> None:
    """Salva o HTML do painel de leitura na primeira falha de download.

    Uma vez só por varredura: basta um exemplo para recalibrar os
    seletores, e reescrever o arquivo a cada falha só gastaria disco. O
    caminho vai para o resumo, para o usuário saber o que me enviar se o
    download continuar falhando.
    """
    if result.debug_dump is not None:
        return
    try:
        destino = config.BASE_DIR / "diagnostico-anexo.html"
        browser_client.dump_message_debug(page, destino)
        result.debug_dump = str(destino)
    except Exception:  # noqa: BLE001 - diagnóstico é melhor-esforço, não pode derrubar a varredura
        pass


def run_and_report(
    max_messages: int | None = None,
    headless: bool = False,
    folder: str | None = None,
) -> ScanResult:
    """Executa a varredura e imprime o relatório final."""
    print(f"Abrindo {folder or 'a Caixa de Entrada'}...")
    result = scan(max_messages=max_messages, headless=headless, folder=folder)

    print("\n=== Resumo da varredura ===")
    for line in result.summary_lines():
        print(line)

    return result
