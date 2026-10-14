"""Nós de resposta e proposta (com ou sem LLM)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from copiloto.agents.labels import humanize_refs
from copiloto.agents.prompts import SYSTEM_ANSWER, SYSTEM_PROPOSAL
from copiloto.agents.render import (
    build_context,
    deterministic_answer,
    strip_bad_citations,
    validate_answer,
    validate_free_text,
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
            lims.append("A pergunta ou um documento continha instruções suspeitas, que foram "
                        "ignoradas.")
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
            lims.append("Parte das evidências foi cortada por limite de tamanho; a resposta "
                        "pode estar incompleta.")
        user_msg = (f"Pergunta: {state['question']}\nMês de referência: "
                    f"{state['reference_month']}\n\n{ctx}")
        with rt.tracer.step("llm:answer") as rec:
            try:
                resp = rt.llm(SYSTEM_ANSWER, user_msg, json_mode=False)
            except ProviderError as e:
                lims.append(f"O modelo de IA não respondeu ({e}). A resposta foi montada só "
                            "com os dados, sem texto redigido por IA.")
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


_MONTHS_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
              "setembro", "outubro", "novembro", "dezembro"]


def _month_pt(ym: str) -> str:
    try:
        y, m = ym.split("-")
        return f"{_MONTHS_PT[int(m) - 1]} de {y}"
    except (ValueError, IndexError):
        return ym


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def fallback_proposal(state: AgentState) -> ProposalContent | None:
    """Proposta determinística a partir da comparação por transportadora."""
    comp = next((d for d in state.get("data_results", [])
                 if d.metric == "period_comparison" and d.filters.get("group_by") == "carrier"),
                None)
    if comp is None or not comp.rows:
        return None
    top = max(comp.rows, key=lambda r: r["variacao_pp"])
    refs = [f"metric:{comp.metric}"] + [h.chunk_id for h in state.get("policy_hits", [])[:3]]
    cur, prev = _month_pt(comp.month), _month_pt(comp.compare_to or "")
    delta = f"{top['variacao_pp']:+.2f}".replace(".", ",")
    return ProposalContent(
        title=f"Investigar cancelamentos com {top['grupo']} em {cur}",
        description=(
            f"A taxa de cancelamento com {top['grupo']} foi de {_pct(top['taxa_atual'])} em "
            f"{cur}, contra {_pct(top['taxa_anterior'])} em {prev} (diferença de {delta} pontos "
            f"percentuais). Abrir revisão operacional conforme o acordo de nível de serviço. "
            f"Os atrasos de entrega aparecem entre os motivos; falta verificar se explicam o "
            f"aumento."
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
        bad: set[str] = set()
        if rt.provider is not None:
            ctx = build_context(state.get("data_results", []), state.get("policy_hits", []))
            user_msg = f"Pergunta: {state['question']}\n\n{ctx[:MAX_CONTEXT_CHARS]}"
            with rt.tracer.step("llm:proposal") as rec:
                try:
                    resp = rt.llm(SYSTEM_PROPOSAL, user_msg, json_mode=True)
                    raw = json.loads(resp.text)
                    raw["evidence_refs"] = [r for r in raw.get("evidence_refs", []) if r in known]
                    # O texto da proposta passa pela mesma validação de citações da resposta:
                    # IDs fora do contexto são removidos e registrados, nunca exibidos.
                    by_id = {h.chunk_id: f"{h.title}, {h.section}"
                             for h in state.get("policy_hits", [])}
                    for field in ("title", "description"):
                        text, removed = validate_free_text(str(raw.get(field, "")), known)
                        bad.update(removed)
                        # Identificadores válidos que sobraram no texto viram nomes legíveis;
                        # os IDs continuam só em evidence_refs.
                        raw[field] = humanize_refs(text, by_id)
                    if bad:
                        rec.meta["bad_citations"] = sorted(bad)
                    proposal = ProposalContent(**ProposeTaskInput(**raw).model_dump())
                except (ProviderError, json.JSONDecodeError, ValidationError, TypeError) as e:
                    rec.meta["fallback"] = type(e).__name__
                    rt.tracer.trace.retries += 1
        if proposal is None:
            proposal = fallback_proposal(state)
        if proposal is None:
            return {"proposal": None, "limitations": state.get("limitations", []) + [
                "Não há comparação entre meses suficiente para sugerir uma ação."]}
        lims = list(state.get("limitations", []))
        if bad:
            lims.append("A sugestão citava uma política que não foi consultada; a referência "
                        "foi removida (citação inexistente na proposta): " + ", ".join(sorted(bad)))
        return {"proposal": proposal, "status": "awaiting_approval", "limitations": lims}
    return run
