"""API FastAPI do Copiloto de Operações.

Autenticação: MODO DE DEMONSTRAÇÃO LOCAL via header `X-Demo-User`.
Não é autenticação segura. Para implantação externa, substituir por autenticação real.
"""

from __future__ import annotations

from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from copiloto import __version__, approval
from copiloto.agents.graph import run_agent
from copiloto.auth import DEMO_USERS, User, get_user
from copiloto.config import DATA_MONTHS, REFERENCE_MONTH, get_settings
from copiloto.providers import get_provider
from copiloto.retrieval.retriever import get_retriever
from copiloto.tools.contracts import (
    ProposalContent,
    QueryOperationsInput,
    SearchPoliciesInput,
)
from copiloto.tools.query_operations import query_operations
from copiloto.tools.search_policies import search_policies

app = FastAPI(
    title="Copiloto de Operações (demonstração, dados sintéticos)",
    version=__version__,
    description="Agente com consultas determinísticas, RAG e aprovação humana. "
                "Todos os dados são fictícios.",
)


def current_user(x_demo_user: str = Header(default="ana.analista")) -> User:
    try:
        return get_user(x_demo_user)
    except PermissionError as e:
        raise HTTPException(401, str(e)) from e


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    want_proposal: bool = False
    use_llm: bool | None = Field(default=None, description="None = conforme configuração")
    retrieval_mode: Literal["lexical", "vector", "hybrid"] | None = None


class DecisionRequest(BaseModel):
    approve: bool
    content_hash: str = Field(min_length=64, max_length=64)


@app.get("/health")
def health():
    s = get_settings()
    prov = get_provider(s)
    ok, msg = prov.is_available() if prov else (True, "modo determinístico")
    r = get_retriever()
    return {
        "status": "ok", "version": __version__, "reference_month": REFERENCE_MONTH,
        "data_months": DATA_MONTHS, "llm_provider": s.llm_provider,
        "llm_model": prov.model_id() if prov else None, "llm_available": ok, "llm_note": msg,
        "retrieval_mode": s.retrieval_mode, "index_version": r.index_version,
        "chunks": len(r.chunks), "demo_auth": True, "synthetic_data": True,
    }


@app.get("/users")
def users():
    return [{"user_id": u.user_id, "name": u.name, "role": u.role} for u in DEMO_USERS.values()]


@app.post("/ask")
def ask(req: AskRequest, user: User = Depends(current_user)):
    s = get_settings()
    if req.use_llm is False:
        provider = None
    elif req.use_llm is True and s.llm_provider == "none":
        raise HTTPException(400, "LLM solicitado, mas COPILOTO_LLM_PROVIDER=none")
    else:
        provider = get_provider(s)
    final, trace = run_agent(req.question, user.user_id, want_proposal=req.want_proposal,
                             settings=s, provider=provider, retrieval_mode=req.retrieval_mode)
    proposal_row = None
    if final.get("proposal") is not None:
        proposal_row = approval.create_proposal(final["proposal"], trace.run_id, user)
    return {
        "run_id": trace.run_id, "status": final.get("status"), "answer": final.get("answer"),
        "citations": final.get("citations", []), "limitations": final.get("limitations", []),
        "injection_flags": final.get("injection_flags", []),
        "data_results": [d.model_dump() for d in final.get("data_results", [])],
        "proposal": proposal_row, "trace": trace.to_dict(),
    }


@app.post("/tools/query_operations")
def tool_query(inp: QueryOperationsInput, user: User = Depends(current_user)):
    try:
        return query_operations(inp).model_dump()
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/tools/search_policies")
def tool_search(inp: SearchPoliciesInput, user: User = Depends(current_user)):
    return search_policies(inp, user).model_dump()


@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, user: User = Depends(current_user)):
    p = approval.get_proposal(proposal_id)
    if p is None:
        raise HTTPException(404, "proposta não encontrada")
    return p


@app.put("/proposals/{proposal_id}")
def edit_proposal(proposal_id: str, content: ProposalContent,
                  user: User = Depends(current_user)):
    try:
        return approval.edit_proposal(proposal_id, content, user)
    except approval.ApprovalError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/proposals/{proposal_id}/decision")
def decide(proposal_id: str, req: DecisionRequest, user: User = Depends(current_user)):
    try:
        return approval.decide(proposal_id, user, req.approve, req.content_hash)
    except approval.ApprovalError as e:
        raise HTTPException(403 if "papel" in str(e) else 409, str(e)) from e


@app.post("/proposals/{proposal_id}/execute")
def execute(proposal_id: str, user: User = Depends(current_user)):
    try:
        return approval.execute(proposal_id, user)
    except approval.ApprovalError as e:
        raise HTTPException(403 if "papel" in str(e) else 409, str(e)) from e


@app.get("/history")
def history(user: User = Depends(current_user)):
    return approval.list_history()
