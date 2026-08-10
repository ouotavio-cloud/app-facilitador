"""Varredura da caixa de entrada: percorre, detecta propostas e persiste.

Junta as peças — navegador (`browser_client`), detecção do código do
processo (`proposal_detector`) e estado local (`storage`) — e produz o
resumo do que foi encontrado (PLANEJAMENTO.md, Fase 4).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app_facilitador import attachments, browser_client, config, inbox_parser
from app_facilitador import logs, pdf_text, proposal_detector, storage

_log = logs.get_logger("scanner")

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
    # assunto/obra, mas cujo corpo revelou um processo cadastrado.
    deep_matches: int = 0
    # E-mails identificados mas pulados por parecerem não-proposta (nota
    # fiscal, contrato, habilitação) — não são abertos nem baixados.
    skipped_non_proposal: int = 0
    stopped: bool = False
    # Pastas vazias levadas embora no fim da varredura — sobras das versões
    # que criavam a árvore da proposta antes de saber se o download daria certo.
    empty_dirs_removed: int = 0
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
        if self.skipped_non_proposal:
            lines.append(
                f"E-mails pulados por não serem proposta (nota/contrato/habilitação): "
                f"{self.skipped_non_proposal}"
            )
        if self.empty_dirs_removed:
            lines.append(
                f"Pastas vazias removidas (sobra de downloads que falharam): "
                f"{self.empty_dirs_removed}"
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
    keep_technical: bool = False,
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
    _log.info(
        "varredura iniciada — pasta=%s limite=%s baixar=%s profunda=%s tecnica=%s",
        folder or "Caixa de Entrada", max_messages, download_attachments,
        deep_scan, keep_technical,
    )

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
                # Não abre (nem baixa) e-mail que é claramente nota fiscal,
                # contrato ou habilitação. Esses citam o código na thread da
                # cotação e casavam, mas não são proposta — abri-los só
                # marcava e-mails como lidos e enchia a pasta de lixo.
                if attachments.is_probably_not_proposal(
                    f"{message.get('subject') or ''} {message.get('preview') or ''}"
                ):
                    result.skipped_non_proposal += 1
                    continue

                try:
                    if matches and download_attachments:
                        _download_proposal(
                            page, connection, message, matches, processes,
                            pasta_propostas, result, keep_technical,
                        )
                    elif deep_scan and not matches:
                        _deep_scan_message(
                            page, connection, message, processes,
                            pasta_propostas, result, keep_technical,
                        )
                except Exception as error:  # noqa: BLE001 - idem: não derruba a varredura
                    _log.exception("erro ao processar anexo de %r", message.get("subject"))
                    result.errors.append(
                        f"anexo de {message.get('subject', '(sem assunto)')}: {error}"
                    )

        # Varre a pasta de propostas no fim para levar embora as árvores
        # vazias deixadas pelas versões anteriores do app, que criavam a
        # pasta antes de o download dar certo.
        result.empty_dirs_removed = attachments.remove_empty_dirs(pasta_propostas)

    _log.info(
        "varredura concluída — %d e-mails, %d baixados, %d falhas%s",
        result.scanned, result.downloaded, result.download_failures,
        " (interrompida)" if result.stopped else "",
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
    keep_technical: bool = False,
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

    baixados = _baixar_anexos_abertos(
        page, connection, message, codigo, obra, base_dir, result, keep_technical
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
    base_dir: Path,
    result: ScanResult,
    keep_technical: bool,
) -> list[Path]:
    """Baixa e arquiva os anexos-documento do e-mail já aberto.

    O fornecedor e o tipo (comercial/técnica) são decididos **por arquivo**,
    porque um e-mail pode trazer propostas de vários fornecedores e, para
    cada um, a técnica e a comercial. Devolve os caminhos gravados, para o
    enriquecimento ler o texto deles.
    """
    arquivos = [
        nome
        for nome in browser_client.find_attachments(page, sorted(_EXTENSIONS))
        if attachments.is_document(nome)
        and not attachments.is_probably_not_proposal(nome)
    ]
    if not arquivos:
        # O e-mail dizia ter anexo, mas nenhum é proposta — só imagem, nota
        # fiscal ou habilitação. Não é erro, é o filtro funcionando.
        return []

    selecionados = attachments.select_proposals(
        arquivos,
        message.get("sender_name"),
        message.get("sender_email"),
        keep_technical=keep_technical,
    )

    gravados: list[Path] = []
    for item in selecionados:
        nome, fornecedor, tipo = item["filename"], item["supplier"], item["tipo"]
        destino_dir = attachments.proposal_dir(base_dir, obra, codigo, fornecedor)
        # A pasta não é criada aqui: quem a cria é o download, depois de o
        # arquivo já estar vindo (ver `browser_client.download_attachment`).
        # Criá-la junto com o caminho deixava uma árvore vazia por cada
        # download que falhava.
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
            tipo=tipo,
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
    keep_technical: bool = False,
) -> None:
    """Varredura profunda: abre um e-mail não identificado e lê o CORPO
    para achar o código escrito ali (não só no assunto).

    Lê apenas o corpo — de propósito. A versão anterior baixava todo anexo
    de todo e-mail para uma pasta temporária só para ler o PDF, e isso, numa
    caixa de trabalho, baixava centenas de arquivos (notas, contratos,
    certidões) e os descartava — enchia o histórico do navegador e abria
    e-mails que não eram proposta. Agora, se o corpo casar com um processo
    cadastrado, os anexos-proposta são baixados de verdade; se não casar,
    nada é baixado. O preço é não pegar o código que só existe DENTRO do PDF
    de um e-mail sem nenhuma pista no assunto/corpo — caso raro, e caro
    demais de cobrir.
    """
    if not browser_client.open_message(page, message["conv_id"]):
        return

    corpo = browser_client.read_message_body(page)
    texto = " ".join(
        t for t in (inbox_parser.searchable_text(message), corpo) if t
    ).strip()

    matches = proposal_detector.match_known_processes(texto, processes)
    if not matches:
        return  # o corpo não cita processo cadastrado; nada a baixar

    codigo = matches[0]["code"]
    obra = next((p["obra"] for p in processes if p["code"] == codigo), None)

    result.deep_matches += 1
    novos = storage.add_message_codes(
        connection, message["conv_id"], {m["code"]: "conteúdo" for m in matches}
    )
    result.codes_in_content += len(novos)
    result.messages_with_codes += 1
    for match in matches:
        result.codes_found[match["code"]] = result.codes_found.get(match["code"], 0) + 1

    # Casou pelo corpo: agora sim baixa os anexos-proposta de verdade,
    # com o mesmo filtro e preferência pela comercial do download normal.
    _baixar_anexos_abertos(
        page, connection, message, codigo, obra, base_dir, result, keep_technical
    )


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
