"""Nós de resposta e proposta (com ou sem LLM)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from copiloto.agents.prompts import SYSTEM_ANSWER, SYSTEM_PROPOSAL
from copiloto.agents.render import (
    build_context,
    deterministic_answer,
    strip_bad_citations,
    validate_answer,
)
from copiloto.agents.runtime import MAX_CONTEXT_CHARS, AgentRuntime
from copiloto.agents.state import AgentState, Citation
from copiloto.providers import ProviderError
from copiloto.tools.contracts import ProposalContent, ProposeTaskInput


def node_answer(rt: AgentRuntime):
    def run(state: AgentState) -> AgentState:
        data, hits = state.get("data_results", []), state.get("policy_hits", [])
        lims = list(state.get("limitations", []))
        if state.get("injection_flags"):
            lims.append("Instruções suspeitas detectadas na entrada ou em documentos; "
                        "foram ignoradas.")
        citations: list[Citation] = [
            {"chunk_id": h.chunk_id, "doc_id": h.doc_id, "title": h.title,
             "section": h.section, "text": h.text, "source": h.source} for h in hits]
        if state.get("status") == "insufficient":
            return {"answer": "**Informação insuficiente.** " + " ".join(lims),
                    "citations": [], "limitations": lims, "status": "insufficient"}
        if rt.provider is None:
            return {"answer": deterministic_answer(data, hits, lims),
                    "citations": citations, "limitations": lims, "status": "answer_ready"}

        ctx = build_context(data, hits)
        if len(ctx) > MAX_CONTEXT_CHARS:
            ctx = ctx[:MAX_CONTEXT_CHARS] + "\n[contexto truncado]"
            lims.append("Contexto truncado por limite de tamanho.")
        user_msg = (f"Pergunta: {state['question']}\nMês de referência: "
                    f"{state['reference_month']}\n\n{ctx}")
        with rt.tracer.step("llm:answer") as rec:
            try:
                resp = rt.llm(SYSTEM_ANSWER, user_msg, json_mode=False)
            except ProviderError as e:
                lims.append(f"LLM indisponível ({e}); resposta em modo determinístico.")
                return {"answer": deterministic_answer(data, hits, lims),
                        "citations": citations, "limitations": lims, "status": "answer_ready"}
            rec.meta["latency_ms"] = resp.latency_ms
        with rt.tracer.step("validate_answer") as rec:
            valid, problems = validate_answer(resp.text, hits, data)
            rec.meta["problems"] = problems
            text = strip_bad_citations(resp.text, set(valid))
            lims.extend(problems)
            used = [c for c in citations if c["chunk_id"] in set(valid)]
        return {"answer": text, "citations": used, "limitations": lims, "status": "answer_ready"}
    return run


def fallback_proposal(state: AgentState) -> ProposalContent | None:
    """Proposta determinística a partir da comparação por transportadora."""
    comp = next((d for d in state.get("data_results", [])
                 if d.metric == "period_comparison" and d.filters.get("group_by") == "carrier"),
                None)
    if comp is None or not comp.rows:
        return None
    top = max(comp.rows, key=lambda r: r["variacao_pp"])
    refs = [f"metric:{comp.metric}"] + [h.chunk_id for h in state.get("policy_hits", [])[:3]]
    return ProposalContent(
        title=f"Investigar cancelamentos com {top['grupo']} em {comp.month}",
        description=(
            f"A taxa de cancelamento com {top['grupo']} foi de {top['taxa_atual'] * 100:.1f}% "
            f"em {comp.month} contra {top['taxa_anterior'] * 100:.1f}% em {comp.compare_to} "
            f"({top['variacao_pp']:+.2f} p.p.). Abrir revisão operacional conforme o SLA. "
            f"Hipótese a investigar: associação com atrasos de entrega."
        ),
        owner_role="logistica", priority="alta", evidence_refs=refs,
    )


def node_propose(rt: AgentRuntime):
    def run(state: AgentState) -> AgentState:
        if not state.get("want_proposal") or state.get("status") != "answer_ready":
            return {"proposal": None}
        rt.tracer.tool_used("propose_task")
        known = {h.chunk_id for h in state.get("policy_hits", [])} | {
            f"metric:{d.metric}" for d in state.get("data_results", [])}
        proposal: ProposalContent | None = None
        if rt.provider is not None:
            ctx = build_context(state.get("data_results", []), state.get("policy_hits", []))
            user_msg = f"Pergunta: {state['question']}\n\n{ctx[:MAX_CONTEXT_CHARS]}"
            with rt.tracer.step("llm:proposal") as rec:
                try:
                    resp = rt.llm(SYSTEM_PROPOSAL, user_msg, json_mode=True)
                    raw = json.loads(resp.text)
                    raw["evidence_refs"] = [r for r in raw.get("evidence_refs", []) if r in known]
                    proposal = ProposalContent(**ProposeTaskInput(**raw).model_dump())
                except (ProviderError, json.JSONDecodeError, ValidationError, TypeError) as e:
                    rec.meta["fallback"] = type(e).__name__
                    rt.tracer.trace.retries += 1
        if proposal is None:
            proposal = fallback_proposal(state)
        if proposal is None:
            return {"proposal": None, "limitations": state.get("limitations", []) + [
                "Sem evidência comparativa suficiente para propor uma tarefa."]}
        return {"proposal": proposal, "status": "awaiting_approval"}
    return run
