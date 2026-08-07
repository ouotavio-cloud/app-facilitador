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
from datetime import datetime
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
    created_at TEXT NOT NULL
);
"""


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre o banco, garante o schema e fecha a conexão ao final."""
    path = db_path if db_path is not None else config.DB_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(_SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def add_process(connection: sqlite3.Connection, code: str, obra: str | None = None) -> bool:
    """Cadastra um processo de cotação. Devolve True se era novo.

    Recadastrar um código existente atualiza o nome da obra, para permitir
    corrigir um cadastro sem apagar e recriar.
    """
    cursor = connection.execute(
        """
        INSERT INTO processes (code, obra, created_at) VALUES (?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET obra = excluded.obra
        """,
        (code, obra, datetime.now().isoformat(timespec="seconds")),
    )
    return cursor.rowcount > 0


def remove_process(connection: sqlite3.Connection, code: str) -> bool:
    """Remove um processo do acompanhamento. Devolve True se existia."""
    cursor = connection.execute("DELETE FROM processes WHERE code = ?", (code,))
    return cursor.rowcount > 0


def list_processes(connection: sqlite3.Connection) -> list[dict]:
    rows = connection.execute(
        "SELECT code, obra, created_at FROM processes ORDER BY code"
    ).fetchall()
    return [dict(row) for row in rows]


def save_message(
    connection: sqlite3.Connection,
    message: dict,
    codes: list[str],
    matched_by: dict[str, str] | None = None,
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
            received_at_raw, preview, is_pinned, has_attachments, first_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def count_messages(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


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
