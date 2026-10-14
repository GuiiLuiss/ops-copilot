"""Grafo LangGraph: validate → plan → tools → answer → propose.

A aprovação e a execução NÃO fazem parte do grafo (ver `copiloto.approval`).
"""

from __future__ import annotations

from pathlib import Path

from langgraph.graph import END, StateGraph

from copiloto.agents.nodes_llm import node_answer, node_propose
from copiloto.agents.prompts import PROMPT_VERSION
from copiloto.agents.runtime import AgentRuntime, node_plan, node_tools, node_validate
from copiloto.agents.state import AgentState
from copiloto.auth import get_user
from copiloto.config import REFERENCE_MONTH, Settings, get_settings
from copiloto.observability.tracer import RunTrace, Tracer
from copiloto.providers import LLMProvider, get_provider
from copiloto.retrieval.retriever import Retriever, get_retriever

_AUTO = object()


def build_graph(rt: AgentRuntime):
    g = StateGraph(AgentState)
    g.add_node("validate", node_validate(rt))
    g.add_node("plan", node_plan(rt))
    g.add_node("tools", node_tools(rt))
    g.add_node("answer", node_answer(rt))
    g.add_node("propose", node_propose(rt))
    g.set_entry_point("validate")
    g.add_conditional_edges(
        "validate", lambda s: "end" if s.get("status") == "failed" else "plan",
        {"end": END, "plan": "plan"})
    g.add_conditional_edges(
        "plan", lambda s: "answer" if s.get("status") == "insufficient" else "tools",
        {"answer": "answer", "tools": "tools"})
    g.add_edge("tools", "answer")
    g.add_edge("answer", "propose")
    g.add_edge("propose", END)
    return g.compile()


def run_agent(question: str, user_id: str, *, want_proposal: bool = False,
              settings: Settings | None = None, provider: LLMProvider | None | object = _AUTO,
              retriever: Retriever | None = None, db_path: Path | None = None,
              retrieval_mode: str | None = None,
              reference_month: str | None = None) -> tuple[AgentState, RunTrace]:
    s = settings or get_settings()
    user = get_user(user_id)
    prov = get_provider(s) if provider is _AUTO else provider
    retr = retriever or get_retriever()
    tracer = Tracer(user_id=user.user_id, role=user.role,
                    mode="llm" if prov else "deterministico",
                    model=prov.model_id() if prov else None,
                    index_version=retr.index_version, prompt_version=PROMPT_VERSION,
                    log_dir=s.log_path)
    rt = AgentRuntime(settings=s, user=user, provider=prov, retriever=retr, tracer=tracer,
                      db_path=db_path, retrieval_mode=retrieval_mode)
    init: AgentState = {
        "question": question, "user_id": user.user_id, "role": user.role,
        "want_proposal": want_proposal, "reference_month": reference_month or REFERENCE_MONTH,
    }
    try:
        final = build_graph(rt).invoke(init)
        trace = tracer.finish(final.get("status", "failed"), final.get("error"))
    except Exception as e:  # noqa: BLE001 - falha controlada, mensagem compreensível
        trace = tracer.finish("failed", str(e))
        final = {**init, "status": "failed", "error": str(e), "citations": [], "limitations": [],
                 "answer": f"Falha na execução ({type(e).__name__}). Veja o rastreio."}
    return final, trace
