"""Persistência local do estado da varredura (SQLite).

Guarda o que já foi visto para que rodar a varredura duas vezes não
duplique nada e para que execuções futuras possam ser incrementais
(ver PLANEJAMENTO.md, seções 3 e 5). Banco em arquivo único na pasta do
projeto — sem servidor, coerente com a premissa de rodar só na máquina
do usuário.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from app_facilitador import config

# Separador usado ao agrupar valores no SQL. Precisa ser um caractere que
# não apareça nos dados agrupados — daí não usar vírgula, que aparece
# dentro de `matched_by` ("código, obra").
_CONCAT_SEPARATOR = "\x1f"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    conv_id TEXT PRIMARY KEY,
    sender_name TEXT,
    sender_email TEXT,
    subject TEXT,
    received_at TEXT,
    received_at_raw TEXT,
    preview TEXT,
    is_pinned INTEGER NOT NULL DEFAULT 0,
    has_attachments INTEGER NOT NULL DEFAULT 0,
    folder TEXT,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposal_codes (
    conv_id TEXT NOT NULL,
    code TEXT NOT NULL,
    matched_by TEXT,
    PRIMARY KEY (conv_id, code),
    FOREIGN KEY (conv_id) REFERENCES messages(conv_id)
);

CREATE INDEX IF NOT EXISTS idx_proposal_codes_code ON proposal_codes(code);

-- Processos de cotação que o usuário informa estar acompanhando. É a
-- "tabela de Processos" da seção 3 do PLANEJAMENTO.md: em vez de o
-- sistema tentar adivinhar quais cotações existem, o usuário cadastra as
-- suas. O nome da obra entra como pista redundante — quando o código vem
-- escrito de forma inesperada, o nome da obra no assunto ainda casa.
CREATE TABLE IF NOT EXISTS processes (
    code TEXT PRIMARY KEY,
    obra TEXT,
    deadline TEXT,
    created_at TEXT NOT NULL
);

-- Arquivos de proposta já baixados. Guardar o caminho, e não só o nome,
-- permite ao painel abrir a pasta certa e permite saber o que já foi
-- baixado — sem isso cada varredura baixaria tudo de novo.
CREATE TABLE IF NOT EXISTS attachments (
    conv_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT,
    code TEXT,
    supplier TEXT,
    tipo TEXT,
    downloaded_at TEXT NOT NULL,
    error TEXT,
    PRIMARY KEY (conv_id, filename),
    FOREIGN KEY (conv_id) REFERENCES messages(conv_id)
);

CREATE INDEX IF NOT EXISTS idx_attachments_code ON attachments(code);

-- Preferências do usuário (hoje: onde as propostas são arquivadas).
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Colunas acrescentadas depois da primeira versão do schema. Um CREATE
# TABLE IF NOT EXISTS não altera tabela existente, então bancos criados
# por versões anteriores precisam receber as colunas novas aqui.
_MIGRATIONS = [
    ("processes", "deadline", "ALTER TABLE processes ADD COLUMN deadline TEXT"),
    ("proposal_codes", "matched_by", "ALTER TABLE proposal_codes ADD COLUMN matched_by TEXT"),
    ("messages", "folder", "ALTER TABLE messages ADD COLUMN folder TEXT"),
    ("attachments", "tipo", "ALTER TABLE attachments ADD COLUMN tipo TEXT"),
]


def _apply_migrations(connection: sqlite3.Connection) -> None:
    for table, column, statement in _MIGRATIONS:
        columns = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if column not in columns:
            connection.execute(statement)


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre o banco, garante o schema e fecha a conexão ao final."""
    path = db_path if db_path is not None else config.DB_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_SCHEMA)
        _apply_migrations(connection)
        yield connection
        connection.commit()
    finally:
        connection.close()


def add_process(
    connection: sqlite3.Connection,
    code: str,
    obra: str | None = None,
    deadline: date | None = None,
) -> bool:
    """Cadastra um processo de cotação. Devolve True se era novo.

    Recadastrar um código existente atualiza obra e prazo, para permitir
    corrigir um cadastro sem apagar e recriar.
    """
    cursor = connection.execute(
        """
        INSERT INTO processes (code, obra, deadline, created_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            obra = excluded.obra,
            deadline = excluded.deadline
        """,
        (
            code,
            obra,
            deadline.isoformat() if deadline else None,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    return cursor.rowcount > 0


def remove_process(connection: sqlite3.Connection, code: str) -> bool:
    """Remove um processo do acompanhamento. Devolve True se existia."""
    cursor = connection.execute("DELETE FROM processes WHERE code = ?", (code,))
    return cursor.rowcount > 0


def list_processes(connection: sqlite3.Connection) -> list[dict]:
    """Processos acompanhados, cada um com a contagem de e-mails já ligados a ele."""
    rows = connection.execute(
        """
        SELECT p.code, p.obra, p.deadline, p.created_at,
               COUNT(pc.conv_id) AS message_count
        FROM processes p
        LEFT JOIN proposal_codes pc ON pc.code = p.code
        GROUP BY p.code
        ORDER BY p.deadline IS NULL, p.deadline, p.code
        """
    ).fetchall()

    return [
        {**dict(row), "deadline_date": date.fromisoformat(row["deadline"]) if row["deadline"] else None}
        for row in rows
    ]


def save_message(
    connection: sqlite3.Connection,
    message: dict,
    codes: list[str],
    matched_by: dict[str, str] | None = None,
    folder: str | None = None,
) -> bool:
    """Grava a mensagem e seus códigos de processo. Devolve True se era nova.

    Idempotente por `conv_id`: reencontrar a mesma conversa numa varredura
    posterior não duplica o registro nem sobrescreve o `first_seen_at`
    original.
    """
    received_at = message.get("received_at")
    cursor = connection.execute(
        """
        INSERT INTO messages (
            conv_id, sender_name, sender_email, subject, received_at,
            received_at_raw, preview, is_pinned, has_attachments, folder,
            first_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conv_id) DO NOTHING
        """,
        (
            message["conv_id"],
            message.get("sender_name"),
            message.get("sender_email"),
            message.get("subject"),
            received_at.isoformat() if isinstance(received_at, datetime) else None,
            message.get("received_at_raw"),
            message.get("preview"),
            int(bool(message.get("is_pinned"))),
            int(bool(message.get("has_attachments"))),
            folder,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    is_new = cursor.rowcount > 0

    matched_by = matched_by or {}
    for code in codes:
        connection.execute(
            "INSERT INTO proposal_codes (conv_id, code, matched_by) VALUES (?, ?, ?) "
            "ON CONFLICT(conv_id, code) DO NOTHING",
            (message["conv_id"], code, matched_by.get(code)),
        )

    return is_new


def add_message_codes(
    connection: sqlite3.Connection,
    conv_id: str,
    matched_by: dict[str, str | None],
) -> list[str]:
    """Acrescenta códigos a uma mensagem já salva. Devolve os que eram novos.

    Usado quando o código aparece só no corpo do e-mail ou dentro do PDF —
    descoberto depois de a mensagem já ter sido gravada pela leitura do
    assunto. Para um código que já existe, funde as pistas ("obra" +
    "anexo" → "obra, anexo") em vez de sobrescrever, para o painel mostrar
    tudo o que confirmou aquela proposta.
    """
    novos: list[str] = []
    for code, clue in matched_by.items():
        existente = connection.execute(
            "SELECT matched_by FROM proposal_codes WHERE conv_id = ? AND code = ?",
            (conv_id, code),
        ).fetchone()

        if existente is None:
            connection.execute(
                "INSERT INTO proposal_codes (conv_id, code, matched_by) VALUES (?, ?, ?)",
                (conv_id, code, clue),
            )
            novos.append(code)
        elif clue:
            pistas = [
                p.strip()
                for p in ((existente["matched_by"] or "").split(",") + clue.split(","))
                if p.strip()
            ]
            fundido = ", ".join(dict.fromkeys(pistas))
            connection.execute(
                "UPDATE proposal_codes SET matched_by = ? WHERE conv_id = ? AND code = ?",
                (fundido, conv_id, code),
            )
    return novos


def count_messages(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def list_recent_messages(
    connection: sqlite3.Connection, folder: str | None = None, limit: int = 20
) -> list[dict]:
    """E-mails mais recentes primeiro, opcionalmente de uma pasta só.

    Atende o item 2.1 do pedido: enumerar os e-mails novos que chegaram
    na pasta de trabalho do usuário, do mais recente para o mais antigo.

    Mensagens sem data reconhecida vão para o fim: sem `received_at` não
    dá para afirmar que são recentes, e colocá-las no topo (onde o NULL
    cairia por padrão) daria uma ordem enganosa.
    """
    where = "WHERE folder = ?" if folder else ""
    params = (folder, limit) if folder else (limit,)

    rows = connection.execute(
        f"""
        SELECT conv_id, sender_name, sender_email, subject, received_at,
               received_at_raw, preview, has_attachments, folder
        FROM messages
        {where}
        ORDER BY received_at IS NULL, received_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()

    return [dict(row) for row in rows]


def list_scanned_folders(connection: sqlite3.Connection) -> list[str]:
    """Pastas que já foram varridas ao menos uma vez."""
    rows = connection.execute(
        "SELECT DISTINCT folder FROM messages WHERE folder IS NOT NULL ORDER BY folder"
    ).fetchall()
    return [row["folder"] for row in rows]


def list_messages_with_codes(connection: sqlite3.Connection) -> list[dict]:
    """Lista as mensagens que citam algum código de processo, mais recentes primeiro."""
    # Separador explícito em vez do padrão do GROUP_CONCAT: `matched_by`
    # guarda listas de pistas como "código, obra", e separar por vírgula
    # partiria esse valor ao meio, desalinhando cada código da sua pista.
    rows = connection.execute(
        f"""
        SELECT m.conv_id, m.sender_name, m.sender_email, m.subject,
               m.received_at, m.received_at_raw, m.has_attachments,
               GROUP_CONCAT(p.code, '{_CONCAT_SEPARATOR}') AS codes,
               GROUP_CONCAT(
                   COALESCE(p.matched_by, 'não cadastrado'), '{_CONCAT_SEPARATOR}'
               ) AS matched_by
        FROM messages m
        JOIN proposal_codes p ON p.conv_id = m.conv_id
        GROUP BY m.conv_id
        ORDER BY m.received_at DESC
        """
    ).fetchall()

    return [
        {
            **dict(row),
            "codes": row["codes"].split(_CONCAT_SEPARATOR),
            "matched_by": row["matched_by"].split(_CONCAT_SEPARATOR),
        }
        for row in rows
    ]


def set_setting(connection: sqlite3.Connection, key: str, value: str | None) -> None:
    """Grava uma preferência do usuário."""
    connection.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_setting(
    connection: sqlite3.Connection, key: str, default: str | None = None
) -> str | None:
    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    if row is None or row["value"] is None:
        return default
    return row["value"]


def record_attachment(
    connection: sqlite3.Connection,
    conv_id: str,
    filename: str,
    path: str | None,
    code: str | None,
    supplier: str | None,
    tipo: str | None = None,
    error: str | None = None,
) -> None:
    """Registra um anexo baixado — ou a falha ao baixá-lo.

    Guardar também o que falhou é o que permite ao painel mostrar "esta
    proposta não veio", em vez de o arquivo simplesmente não existir e
    ninguém notar. `tipo` marca comercial/técnica, para o painel destacar a
    comercial (a que tem preço).
    """
    connection.execute(
        """
        INSERT INTO attachments
            (conv_id, filename, path, code, supplier, tipo, downloaded_at, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conv_id, filename) DO UPDATE SET
            path = excluded.path,
            code = excluded.code,
            supplier = excluded.supplier,
            tipo = excluded.tipo,
            downloaded_at = excluded.downloaded_at,
            error = excluded.error
        """,
        (
            conv_id,
            filename,
            path,
            code,
            supplier,
            tipo,
            datetime.now().isoformat(timespec="seconds"),
            error,
        ),
    )


def downloaded_conversations(connection: sqlite3.Connection) -> set[str]:
    """Conversas cujos anexos já foram baixados com sucesso.

    Serve para a varredura não abrir de novo um e-mail já processado —
    abrir custa segundos e marca a mensagem como lida no Outlook.
    """
    rows = connection.execute(
        "SELECT DISTINCT conv_id FROM attachments WHERE error IS NULL"
    ).fetchall()
    return {row["conv_id"] for row in rows}


def downloaded_conversations_on_disk(connection: sqlite3.Connection) -> set[str]:
    """Conversas já baixadas **e cujos arquivos ainda estão na pasta**.

    O banco sozinho não basta: se o usuário apagou uma proposta da pasta, a
    varredura tem de baixá-la de novo. Aqui o disco é que manda — uma
    conversa só conta como "já baixada" se todos os arquivos que ela gerou
    continuam existindo. Some um deles, a conversa volta a ser processada.
    """
    rows = connection.execute(
        "SELECT conv_id, path FROM attachments WHERE error IS NULL AND path IS NOT NULL"
    ).fetchall()

    por_conversa: dict[str, list[str]] = {}
    for row in rows:
        por_conversa.setdefault(row["conv_id"], []).append(row["path"])

    return {
        conv_id
        for conv_id, caminhos in por_conversa.items()
        if all(Path(caminho).exists() for caminho in caminhos)
    }


def list_attachments(connection: sqlite3.Connection) -> list[dict]:
    """Propostas baixadas, das mais recentes para as mais antigas."""
    rows = connection.execute(
        """
        SELECT a.conv_id, a.filename, a.path, a.code, a.supplier, a.tipo,
               a.downloaded_at, a.error,
               m.sender_name, m.sender_email, m.subject, m.received_at_raw
        FROM attachments a
        LEFT JOIN messages m ON m.conv_id = a.conv_id
        ORDER BY a.downloaded_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def attachments_by_conversation(connection: sqlite3.Connection) -> dict[str, list[dict]]:
    """Anexos agrupados por conversa, para a tabela de propostas."""
    agrupados: dict[str, list[dict]] = {}
    for anexo in list_attachments(connection):
        agrupados.setdefault(anexo["conv_id"], []).append(anexo)
    return agrupados
