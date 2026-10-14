"""Ingestão de documentos de políticas: validação, chunking por seção e dedup por hash."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, field_validator

FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SECTION_RE = re.compile(r"^(#{1,3})\s+(.*)$", re.MULTILINE)


class DocMeta(BaseModel):
    doc_id: str
    title: str
    version: str
    valid_from: str
    valid_until: str | None = None
    access_level: str
    source: str
    supersedes: str | None = None
    test_malicious: bool = False

    @field_validator("access_level")
    @classmethod
    def _lvl(cls, v):
        if v not in {"analista", "gestor"}:
            raise ValueError(f"access_level inválido: {v}")
        return v

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _date(cls, v):
        if v is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
            raise ValueError(f"data inválida: {v}")
        return v


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    version: str
    section: str
    text: str
    access_level: str
    valid_from: str
    valid_until: str | None
    source: str
    content_hash: str
    order: int = 0
    extra: dict = field(default_factory=dict)


def _parse_front_matter(raw: str) -> tuple[dict, str]:
    m = FRONT_RE.match(raw)
    if not m:
        raise ValueError("front matter ausente")
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip().strip('"').strip("'")
        if v in ("null", ""):
            v = None
        elif v in ("true", "false"):
            v = v == "true"
        meta[k.strip()] = v
    return meta, raw[m.end():]


def chunk_document(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    meta_dict, body = _parse_front_matter(raw)
    meta = DocMeta(**meta_dict)

    # Divide por cabeçalhos; o texto antes do primeiro "##" é a introdução
    positions = [(m.start(), m.group(2).strip()) for m in SECTION_RE.finditer(body)]
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for i, (start, heading) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        text = body[start:end].strip()
        if len(text.split()) < 8:
            continue
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        if h in seen:
            continue
        seen.add(h)
        chunks.append(
            Chunk(
                chunk_id=f"{meta.doc_id}#s{len(chunks):02d}",
                doc_id=meta.doc_id,
                title=meta.title,
                version=meta.version,
                section=heading,
                text=text,
                access_level=meta.access_level,
                valid_from=meta.valid_from,
                valid_until=meta.valid_until,
                source=meta.source,
                content_hash=h,
                order=len(chunks),
                extra={"test_malicious": meta.test_malicious, "supersedes": meta.supersedes},
            )
        )
    return chunks


def load_corpus(policies_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    doc_hashes: set[str] = set()
    for path in sorted(policies_dir.glob("*.md")):
        full_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if full_hash in doc_hashes:
            continue  # documento duplicado byte a byte
        doc_hashes.add(full_hash)
        chunks.extend(chunk_document(path))
    return chunks


def corpus_version(chunks: list[Chunk]) -> str:
    """Versão do índice = hash dos hashes dos chunks, em ordem."""
    joined = "|".join(c.content_hash for c in chunks)
    return hashlib.sha256(joined.encode()).hexdigest()[:12]
