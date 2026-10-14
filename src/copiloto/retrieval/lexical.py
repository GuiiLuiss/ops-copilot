"""Busca lexical com SQLite FTS5 (BM25 nativo). Sem downloads adicionais."""

from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata

from copiloto.retrieval.ingest import Chunk

_STOP = {
    "a", "o", "os", "as", "de", "do", "da", "dos", "das", "e", "em", "no", "na", "nos", "nas",
    "um", "uma", "por", "para", "com", "que", "se", "ao", "aos", "quais", "qual", "como",
    "quando", "este", "esta", "neste", "nesta", "mes", "podemos", "tomar", "sobre",
}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _terms(query: str) -> list[str]:
    toks = re.findall(r"[a-z0-9]{3,}", normalize(query))
    return [t for t in toks if t not in _STOP]


class LexicalIndex:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = {c.chunk_id: c for c in chunks}
        # Índice em memória compartilhado entre threads da API (leitura serializada por lock)
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5(chunk_id UNINDEXED, title, section, body, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        self.conn.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?)",
            [(c.chunk_id, normalize(c.title), normalize(c.section), normalize(c.text))
             for c in chunks],
        )
        self.conn.commit()

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        terms = _terms(query)
        if not terms:
            return []
        # OR entre termos; bm25() devolve valores negativos (menor = melhor)
        match = " OR ".join(f'"{t}"' for t in terms)
        with self._lock:
            rows = self.conn.execute(
                "SELECT chunk_id, bm25(chunks, 0.0, 2.0, 1.5, 1.0) AS s FROM chunks "
                "WHERE chunks MATCH ? ORDER BY s LIMIT ?",
                (match, top_k),
            ).fetchall()
        return [(cid, -s) for cid, s in rows]
