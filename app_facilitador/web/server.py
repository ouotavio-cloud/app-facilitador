"""Servidor local do App Facilitador.

Serve o painel no navegador da própria máquina. Flask (síncrono) e não
FastAPI (assíncrono) porque o Playwright que lê o Outlook é síncrono —
misturá-lo a um laço de eventos traria complexidade sem ganho aqui.

Nada sai da máquina: o servidor escuta só em localhost.
"""

from datetime import date

from flask import Flask, jsonify, redirect, render_template, request, url_for

from app_facilitador import browser_client, calendar_client, config, deadlines, storage
from app_facilitador import proposal_detector
from app_facilitador.web.jobs import ScanJob

HOST = "127.0.0.1"
PORT = 5000

scan_job = ScanJob()


def create_app() -> Flask:
    app = Flask(__name__)

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

        return render_template(
            "index.html",
            processes=processes,
            recent=recent,
            proposals=proposals,
            scanned_folders=scanned_folders,
            selected_folder=selected_folder or "",
            total_messages=total_messages,
            has_session=config.BROWSER_STATE_PATH.exists(),
            meetings=calendar_client.cached_meetings(),
        )

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
        folder = (request.form.get("pasta") or "").strip() or None
        limit_raw = (request.form.get("limite") or "").strip()
        max_messages = int(limit_raw) if limit_raw.isdigit() else None

        scan_job.start(folder=folder, max_messages=max_messages)
        return redirect(url_for("index"))

    @app.get("/varredura/status")
    def scan_status():
        return jsonify(scan_job.state.as_dict())

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
        try:
            calendar_client.refresh_meetings()
        except Exception:  # noqa: BLE001 - a tela mostra o estado; não derruba o app
            pass
        return redirect(url_for("index"))

    return app


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


def run(open_browser: bool = True) -> None:
    """Sobe o servidor e abre o painel no navegador padrão."""
    app = create_app()

    if open_browser:
        import threading
        import webbrowser

        # Atraso curto para o servidor estar de pé quando a aba abrir.
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()

    print(f"\nApp Facilitador rodando em http://{HOST}:{PORT}")
    print("Feche esta janela para encerrar o app.\n")
    app.run(host=HOST, port=PORT, debug=False)
