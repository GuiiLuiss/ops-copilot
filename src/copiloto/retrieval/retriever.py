"""Retriever com filtro de autorização e vigência ANTES de montar o contexto.

- Modo `lexical`: FTS5/BM25 (sem downloads).
- Modo `vector`: embeddings locais + FAISS (opcional).
- Modo `hybrid`: Reciprocal Rank Fusion (RRF) entre os dois.

A autorização é um pré-filtro sobre o conjunto de chunks pesquisável: o usuário
nunca vê trechos de documentos acima do seu nível. A lista de chunks autorizados
é derivada do `User` do backend, nunca de argumentos escolhidos pelo modelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from copiloto.auth import User
from copiloto.config import Settings, get_settings
from copiloto.retrieval.ingest import Chunk, corpus_version, load_corpus
from copiloto.retrieval.lexical import LexicalIndex
from copiloto.tools.contracts import PolicyHit

RRF_K = 60


@dataclass
class RetrievalResult:
    hits: list[PolicyHit]
    mode: str
    index_version: str
    filtered_out_count: int
    candidates_considered: int


def _is_valid_on(chunk: Chunk, reference_date: str | None) -> bool:
    if reference_date is None:
        return chunk.valid_until is None
    if chunk.valid_from > reference_date:
        return False
    return chunk.valid_until is None or chunk.valid_until >= reference_date


def rrf(rankings: list[list[tuple[str, float]]], k: int = RRF_K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (cid, _) in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: -x[1])


class Retriever:
    def __init__(self, settings: Settings | None = None, policies_dir: Path | None = None):
        self.settings = settings or get_settings()
        self.chunks = load_corpus(policies_dir or self.settings.policies_path)
        self.by_id = {c.chunk_id: c for c in self.chunks}
        self.index_version = corpus_version(self.chunks)
        self.lexical = LexicalIndex(self.chunks)
        self._vector = None
        self.vector_error: str | None = None

    @property
    def vector(self):
        if self._vector is None and self.vector_error is None:
            try:
                from copiloto.retrieval.vector import VectorIndex

                self._vector = VectorIndex(
                    self.chunks, self.settings.embedding_model,
                    cache_dir=self.settings.index_path, index_version=self.index_version,
                )
            except Exception as e:  # noqa: BLE001 - registramos e seguimos em lexical
                self.vector_error = f"{type(e).__name__}: {e}"
        return self._vector

    def search(self, query: str, user: User, reference_date: str | None = None,
               top_k: int | None = None, mode: str | None = None) -> RetrievalResult:
        top_k = top_k or self.settings.top_k
        mode = mode or self.settings.retrieval_mode

        # 1) Pré-filtro de autorização e vigência (no backend, antes de qualquer ranking)
        allowed = {
            c.chunk_id for c in self.chunks
            if user.can_access(c.access_level) and _is_valid_on(c, reference_date)
        }
        filtered_out = len(self.chunks) - len(allowed)

        # 2) Ranking apenas sobre o subconjunto autorizado
        pool = top_k * 4
        rankings: list[list[tuple[str, float]]] = []
        effective_mode = mode
        if mode in ("lexical", "hybrid"):
            rankings.append([(c, s) for c, s in self.lexical.search(query, pool) if c in allowed])
        if mode in ("vector", "hybrid"):
            vec = self.vector
            if vec is None:
                effective_mode = "lexical (vetorial indisponível)"
                if mode == "vector":
                    rankings.append([(c, s) for c, s in self.lexical.search(query, pool)
                                     if c in allowed])
            else:
                rankings.append([(c, s) for c, s in vec.search(query, pool) if c in allowed])

        fused = rrf(rankings) if len(rankings) > 1 else (rankings[0] if rankings else [])
        hits = [self._to_hit(cid, score) for cid, score in fused[:top_k]]
        return RetrievalResult(
            hits=hits, mode=effective_mode, index_version=self.index_version,
            filtered_out_count=filtered_out, candidates_considered=len(allowed),
        )

    def _to_hit(self, chunk_id: str, score: float) -> PolicyHit:
        c = self.by_id[chunk_id]
        return PolicyHit(
            doc_id=c.doc_id, chunk_id=c.chunk_id, title=c.title, version=c.version,
            section=c.section, text=c.text, score=round(score, 5), source=c.source,
            valid_from=c.valid_from, valid_until=c.valid_until,
        )

    def get_chunk(self, chunk_id: str, user: User) -> Chunk | None:
        """Acesso direto a um chunk, ainda sujeito à autorização."""
        c = self.by_id.get(chunk_id)
        if c is None or not user.can_access(c.access_level):
            return None
        return c


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever()
