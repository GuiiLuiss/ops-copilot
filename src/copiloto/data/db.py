"""Acesso ao SQLite local. Conexões somente leitura para o agente; escrita só via serviço de aprovação."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from copiloto.config import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _connect(path: Path, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


@contextmanager
def read_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Conexão somente leitura: usada por todas as ferramentas do agente."""
    path = db_path or get_settings().db_file
    if not path.exists():
        raise FileNotFoundError(
            f"Banco não encontrado em {path}. Execute: python -m copiloto.data.generate"
        )
    conn = _connect(path, readonly=True)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def write_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Conexão de escrita: restrita ao gerador de dados e ao serviço de aprovação."""
    path = db_path or get_settings().db_file
    conn = _connect(path, readonly=False)
    try:
        init_schema(conn)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
