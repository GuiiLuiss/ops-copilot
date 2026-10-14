"""Contratos (Pydantic) das ferramentas do agente.

Os contratos são estreitos de propósito: o LLM só escolhe entre consultas
predefinidas e parâmetros validados. Nenhum SQL vem do modelo.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

Dimension = Literal["segment", "carrier", "channel", "category", "region", "cancel_reason"]
Metric = Literal[
    "order_volume",
    "cancellation_rate",
    "cancellation_breakdown",
    "period_comparison",
    "delivery_performance",
    "ticket_volume",
]


class QueryOperationsInput(BaseModel):
    """Entrada de `query_operations`."""

    metric: Metric = Field(description="Consulta predefinida a executar.")
    month: str = Field(description="Mês de referência no formato YYYY-MM.")
    compare_to: str | None = Field(
        default=None, description="Mês anterior para comparação (YYYY-MM), se aplicável."
    )
    group_by: Dimension | None = Field(
        default=None, description="Dimensão para agrupar os resultados."
    )
    segment: str | None = Field(default=None, description="Filtro opcional por segmento.")
    carrier: str | None = Field(default=None, description="Filtro opcional por transportadora.")
    channel: str | None = Field(default=None, description="Filtro opcional por canal.")
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("month", "compare_to")
    @classmethod
    def _valid_month(cls, v: str | None) -> str | None:
        if v is not None and not MONTH_RE.match(v):
            raise ValueError(f"mês inválido: {v!r}; use YYYY-MM")
        return v

    @field_validator("segment", "carrier", "channel")
    @classmethod
    def _plain_token(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"[A-Za-z0-9_\- ]{1,40}", v):
            raise ValueError("filtro contém caracteres não permitidos")
        return v


class QueryOperationsOutput(BaseModel):
    metric: Metric
    month: str
    compare_to: str | None = None
    filters: dict[str, str] = Field(default_factory=dict)
    definition: str
    rows: list[dict] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    data_sufficient: bool = True
    note: str | None = None


class SearchPoliciesInput(BaseModel):
    """Entrada de `search_policies`. Identidade e permissão NÃO vêm daqui."""

    query: str = Field(min_length=3, max_length=500)
    reference_date: str | None = Field(
        default=None, description="Data de referência (YYYY-MM-DD) para filtrar vigência."
    )
    top_k: int = Field(default=5, ge=1, le=10)


class PolicyHit(BaseModel):
    doc_id: str
    chunk_id: str
    title: str
    version: str
    section: str
    text: str
    score: float
    source: str
    valid_from: str
    valid_until: str | None


class SearchPoliciesOutput(BaseModel):
    query: str
    retrieval_mode: str
    hits: list[PolicyHit]
    filtered_out_count: int = 0


class ProposeTaskInput(BaseModel):
    """Entrada de `propose_task`. Produz apenas uma proposta; nunca grava a tarefa."""

    title: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=10, max_length=2000)
    owner_role: Literal["atendimento", "logistica", "operacoes"]
    priority: Literal["baixa", "media", "alta"] = "media"
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="IDs de documentos/chunks ou métricas que sustentam a proposta.",
        max_length=20,
    )


class ProposalContent(BaseModel):
    title: str
    description: str
    owner_role: str
    priority: str
    evidence_refs: list[str]
