"""Servidor local do App Facilitador.

Serve o painel no navegador da própria máquina. Flask (síncrono) e não
FastAPI (assíncrono) porque o Playwright que lê o Outlook é síncrono —
misturá-lo a um laço de eventos traria complexidade sem ganho aqui.

Nada sai da máquina: o servidor escuta só em localhost.
"""

import os
import threading
from datetime import date

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for

from app_facilitador import browser_client, calendar_client, config, deadlines, paths
from app_facilitador import proposal_detector, scanner, storage
from app_facilitador.web.jobs import LoginJob, MeetingsJob, ScanJob

HOST = "127.0.0.1"

# Porta padrão. Se estiver ocupada, `run()` procura a próxima livre — num
# app que o usuário abre com dois cliques, "porta em uso" seria um erro
# sem tradução possível para quem só quer ver seus e-mails.
DEFAULT_PORT = 5000
PORT_ATTEMPTS = 20

scan_job = ScanJob()
login_job = LoginJob()
meetings_job = MeetingsJob()


def _browser_busy() -> str | None:
    """O que está usando o navegador agora, ou None se estiver livre.

    As três operações (conectar, varrer, ler o calendário) abrem uma
    janela cada. Duas ao mesmo tempo disputariam a mesma sessão do
    Outlook e uma atrapalharia a outra — melhor recusar e dizer por quê.
    """
    if login_job.state.running:
        return "conectando ao Outlook"
    if scan_job.state.running:
        return "varrendo seus e-mails"
    if meetings_job.state.running:
        return "lendo seu calendário"
    return None


def create_app() -> Flask:
    # Caminhos explícitos: dentro do executável os templates ficam na
    # pasta temporária do PyInstaller, não ao lado do código-fonte.
    web_dir = paths.resource_dir() / "app_facilitador" / "web"
    app = Flask(
        __name__,
        template_folder=str(web_dir / "templates"),
        static_folder=str(web_dir / "static"),
    )
    # Só assina os avisos temporários da tela. Sorteada a cada execução
    # de propósito: não há sessão de usuário para preservar entre uma
    # abertura do app e a seguinte.
    app.secret_key = os.urandom(32)

    @app.route("/")
    def index():
        selected_folder = (request.args.get("pasta") or "").strip() or None

        with storage.connect() as connection:
            processes = _processes_with_status(connection)
            recent = storage.list_recent_messages(
                connection, folder=selected_folder, limit=25
            )
            proposals = storage.list_messages_with_codes(connection)
            scanned_folders = storage.list_scanned_folders(connection)
            total_messages = storage.count_messages(connection)
            arquivos = storage.attachments_by_conversation(connection)
            pasta_propostas = scanner.proposals_dir(connection)

        for proposta in proposals:
            proposta["arquivos"] = arquivos.get(proposta["conv_id"], [])

        meetings = calendar_client.cached_meetings()

        return render_template(
            "index.html",
            processes=processes,
            recent=recent,
            proposals=proposals,
            scanned_folders=scanned_folders,
            selected_folder=selected_folder or "",
            total_messages=total_messages,
            has_session=config.LOGIN_MARKER_PATH.exists(),
            meetings=meetings,
            resumo=_daily_summary(processes, proposals, meetings, total_messages),
            data_dir=str(config.BASE_DIR),
            pasta_propostas=str(pasta_propostas),
            total_arquivos=sum(len(v) for v in arquivos.values()),
        )

    @app.post("/pasta-propostas")
    def set_proposals_dir():
        """Muda onde as propostas são arquivadas.

        Editável porque o melhor lugar depende do usuário: uma pasta local
        serve para quem trabalha sozinho, e uma pasta sincronizada com o
        OneDrive faz o time enxergar as propostas junto.
        """
        escolhida = (request.form.get("pasta") or "").strip()
        with storage.connect() as connection:
            storage.set_setting(
                connection, config.PROPOSALS_DIR_SETTING, escolhida or None
            )
        return redirect(url_for("index"))

    @app.post("/processos")
    def add_process():
        code_input = (request.form.get("codigo") or "").strip()
        obra = (request.form.get("obra") or "").strip() or None
        deadline = deadlines.parse_deadline(request.form.get("prazo"))

        # Normaliza para o mesmo formato que a busca usa: um cadastro
        # digitado "sup 2026 197" nunca casaria com o código achado no
        # e-mail se fosse gravado como veio.
        codes = proposal_detector.find_proposal_codes(code_input)
        if codes:
            with storage.connect() as connection:
                storage.add_process(connection, codes[0], obra, deadline)

        return redirect(url_for("index"))

    @app.post("/processos/<code>/remover")
    def remove_process(code: str):
        with storage.connect() as connection:
            storage.remove_process(connection, code)
        return redirect(url_for("index"))

    @app.post("/varredura")
    def start_scan():
        ocupado = _browser_busy()
        if ocupado:
            flash(f"O app já está {ocupado}. Espere terminar e tente de novo.")
            return redirect(url_for("index"))

        folder = (request.form.get("pasta") or "").strip() or None
        limit_raw = (request.form.get("limite") or "").strip()
        max_messages = int(limit_raw) if limit_raw.isdigit() else None
        # Checkbox marcado por padrão no HTML; quando desmarcado, o navegador
        # simplesmente não envia o campo — daí a ausência significar "não".
        baixar = request.form.get("baixar_anexos") is not None
        # Varredura profunda é opt-in (desmarcada por padrão): abre e lê
        # e-mails que não casaram, marcando-os como lidos.
        profunda = request.form.get("varredura_profunda") is not None

        scan_job.start(
            folder=folder,
            max_messages=max_messages,
            download_attachments=baixar,
            deep_scan=profunda,
        )
        return redirect(url_for("index"))

    @app.post("/varredura/parar")
    def stop_scan():
        """Interrompe a varredura em andamento.

        Existe porque uma varredura pode demorar ou tropeçar num e-mail que
        se comporta de forma inesperada — sem uma saída, a única opção do
        usuário seria fechar o app inteiro.
        """
        scan_job.stop()
        return redirect(url_for("index"))

    @app.get("/varredura/status")
    def scan_status():
        return jsonify(scan_job.state.as_dict())

    @app.post("/login")
    def start_login():
        ocupado = _browser_busy()
        if ocupado:
            flash(f"O app já está {ocupado}. Espere terminar e tente de novo.")
            return redirect(url_for("index"))

        login_job.start()
        return redirect(url_for("index"))

    @app.post("/login/confirmar")
    def confirm_login():
        login_job.confirm()
        return redirect(url_for("index"))

    @app.get("/login/status")
    def login_status():
        state = login_job.state.as_dict()
        # A verdade sobre estar conectado é o arquivo de sessão existir, e
        # não o resultado guardado desta execução: quem já conectou ontem
        # continua conectado hoje sem clicar em nada.
        state["connected"] = state["connected"] or config.LOGIN_MARKER_PATH.exists()
        return jsonify(state)

    @app.get("/pastas")
    def folders():
        """Consulta as pastas direto no Outlook, para o usuário escolher."""
        try:
            with browser_client.open_inbox_session() as page:
                return jsonify({"folders": browser_client.list_folders(page)})
        except Exception as exc:  # noqa: BLE001 - o erro precisa aparecer na tela
            return jsonify({"error": str(exc)}), 500

    @app.post("/reunioes/atualizar")
    def refresh_meetings():
        ocupado = _browser_busy()
        if ocupado:
            flash(f"O app já está {ocupado}. Espere terminar e tente de novo.")
        else:
            meetings_job.start()
        return redirect(url_for("index"))

    @app.get("/reunioes/status")
    def meetings_status():
        return jsonify(meetings_job.state.as_dict())

    @app.post("/encerrar")
    def shutdown():
        """Fecha o app a partir da própria tela.

        No executável não há terminal para interromper com Ctrl+C, e
        deixar um servidor rodando esquecido em segundo plano é pior que
        um encerramento abrupto: aqui não há nada em memória para perder,
        tudo já está no banco.
        """
        _schedule_shutdown()
        return render_template("encerrado.html")

    return app


# Espera antes de matar o processo, para a resposta HTTP chegar ao
# navegador e o usuário ver a tela de despedida em vez de "conexão
# recusada".
SHUTDOWN_DELAY_S = 0.5


def _schedule_shutdown() -> None:
    """Agenda o encerramento do processo.

    Isolado numa função para que os testes possam substituí-la — chamar
    `os._exit` de dentro de um teste derrubaria o pytest junto.
    """
    threading.Timer(SHUTDOWN_DELAY_S, lambda: os._exit(0)).start()


def _processes_with_status(connection) -> list[dict]:
    """Processos já com o semáforo de prazo calculado, prontos para exibir."""
    today = date.today()
    result = []
    for process in storage.list_processes(connection):
        status = deadlines.status_for(process["deadline_date"], today)
        result.append(
            {
                **process,
                "status": status.status,
                "status_label": status.label,
                "status_description": status.description,
            }
        )
    return result


def _daily_summary(
    processes: list[dict], proposals: list[dict], meetings: dict, total_messages: int
) -> dict:
    """Os números do topo da tela: o que exige atenção hoje.

    Existe para responder "o que preciso olhar agora?" sem obrigar o
    usuário a ler quatro tabelas — que é justamente o trabalho que o app
    deveria poupar.
    """
    urgentes = [p for p in processes if p["status"] in ("vencido", "critico")]
    nao_cadastrados = {
        code
        for proposal in proposals
        for code, clue in zip(proposal["codes"], proposal["matched_by"])
        if clue == "não cadastrado"
    }

    return {
        "processos": len(processes),
        "urgentes": len(urgentes),
        "propostas": len(proposals),
        "nao_cadastrados": len(nao_cadastrados),
        "reunioes": len(meetings.get("events", [])) if not meetings.get("stale") else None,
        "emails": total_messages,
    }


def _find_free_port(host: str, first_port: int, attempts: int) -> int:
    import socket

    for port in range(first_port, first_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
                return port
            except OSError:
                continue

    raise RuntimeError(
        f"Nenhuma porta livre entre {first_port} e {first_port + attempts - 1}."
    )


def run(open_browser: bool = True, port: int | None = None) -> None:
    """Sobe o servidor e abre o painel no navegador padrão."""
    app = create_app()
    port = port or _find_free_port(HOST, DEFAULT_PORT, PORT_ATTEMPTS)
    url = f"http://{HOST}:{port}"

    if open_browser:
        import webbrowser

        # Atraso curto para o servidor estar de pé quando a aba abrir.
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print("\n  App Facilitador")
    print(f"  Painel: {url}")
    print(f"  Seus dados: {config.BASE_DIR}")
    print("\n  Se a aba não abrir sozinha, copie o endereço acima no navegador.")
    print("  Para encerrar: feche esta janela.\n")

    app.run(host=HOST, port=port, debug=False)
