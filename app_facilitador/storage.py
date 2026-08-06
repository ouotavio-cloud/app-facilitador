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
    PRIMARY KEY (conv_id, code),
    FOREIGN KEY (conv_id) REFERENCES messages(conv_id)
);

CREATE INDEX IF NOT EXISTS idx_proposal_codes_code ON proposal_codes(code);
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


def save_message(connection: sqlite3.Connection, message: dict, codes: list[str]) -> bool:
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

    for code in codes:
        connection.execute(
            "INSERT INTO proposal_codes (conv_id, code) VALUES (?, ?) "
            "ON CONFLICT(conv_id, code) DO NOTHING",
            (message["conv_id"], code),
        )

    return is_new


def count_messages(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def list_messages_with_codes(connection: sqlite3.Connection) -> list[dict]:
    """Lista as mensagens que citam algum código de processo, mais recentes primeiro."""
    rows = connection.execute(
        """
        SELECT m.conv_id, m.sender_name, m.sender_email, m.subject,
               m.received_at, m.received_at_raw, m.has_attachments,
               GROUP_CONCAT(p.code) AS codes
        FROM messages m
        JOIN proposal_codes p ON p.conv_id = m.conv_id
        GROUP BY m.conv_id
        ORDER BY m.received_at DESC
        """
    ).fetchall()

    return [{**dict(row), "codes": row["codes"].split(",")} for row in rows]
