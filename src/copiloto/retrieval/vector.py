"""Busca vetorial local (sentence-transformers + FAISS). Dependências opcionais.

Instalação: pip install -e ".[vector]". O modelo é baixado na primeira execução
e exige memória local. Se as dependências não estiverem instaladas, o módulo
informa claramente e o sistema continua em modo lexical.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from copiloto.retrieval.ingest import Chunk


class VectorUnavailable(RuntimeError):
    pass


def _import_deps():
    try:
        import faiss  # type: ignore
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise VectorUnavailable(
            "Busca vetorial indisponível: instale com `pip install -e \".[vector]\"`"
        ) from e
    return faiss, SentenceTransformer


class VectorIndex:
    def __init__(self, chunks: list[Chunk], model_name: str, cache_dir: Path | None = None,
                 index_version: str = ""):
        faiss, sentence_transformer_cls = _import_deps()
        self.chunks = chunks
        self.ids = [c.chunk_id for c in chunks]
        self.model_name = model_name
        self.model = sentence_transformer_cls(model_name)

        cache_file = None
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            safe = model_name.replace("/", "__")
            cache_file = cache_dir / f"emb_{safe}_{index_version}.npz"

        if cache_file and cache_file.exists():
            data = np.load(cache_file, allow_pickle=False)
            emb = data["emb"]
            cached_ids = json.loads(str(data["ids"]))
            if cached_ids != self.ids:
                emb = self._embed_chunks()
                np.savez(cache_file, emb=emb, ids=json.dumps(self.ids))
        else:
            emb = self._embed_chunks()
            if cache_file:
                np.savez(cache_file, emb=emb, ids=json.dumps(self.ids))

        self.index = faiss.IndexFlatIP(emb.shape[1])
        self.index.add(emb.astype(np.float32))

    def _embed_chunks(self) -> np.ndarray:
        texts = [f"{c.title}. {c.section}. {c.text}" for c in self.chunks]
        return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        q = self.model.encode([query], normalize_embeddings=True, show_progress_bar=False)
        scores, idx = self.index.search(q.astype(np.float32), min(top_k, len(self.ids)))
        return [(self.ids[i], float(s)) for s, i in zip(scores[0], idx[0], strict=True) if i >= 0]
