"""Estado do grafo do agente."""

from __future__ import annotations

from typing import Literal, TypedDict

from copiloto.tools.contracts import PolicyHit, ProposalContent, QueryOperationsOutput

AgentStatus = Literal[
    "received", "analyzing", "retrieving", "answer_ready", "awaiting_approval",
    "approved", "rejected", "executed", "failed", "insufficient",
]


class ToolPlan(TypedDict):
    tool: str
    args: dict


class Citation(TypedDict):
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str
    source: str


class AgentState(TypedDict, total=False):
    # entrada
    question: str
    user_id: str
    role: str
    reference_month: str
    want_proposal: bool
    # planejamento
    intent: str
    plan: list[ToolPlan]
    # evidências
    data_results: list[QueryOperationsOutput]
    policy_hits: list[PolicyHit]
    retrieval_mode: str
    injection_flags: list[str]
    # saída
    answer: str
    citations: list[Citation]
    proposal: ProposalContent | None
    status: AgentStatus
    limitations: list[str]
    error: str | None
