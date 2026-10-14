"""Contexto de execução do agente e nós de validação/plano/ferramentas."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from copiloto.agents import planner
from copiloto.agents.state import AgentState
from copiloto.auth import User
from copiloto.config import REFERENCE_MONTH, Settings
from copiloto.observability.tracer import Tracer
from copiloto.providers import LLMProvider
from copiloto.providers.base import estimate_tokens
from copiloto.retrieval.retriever import Retriever
from copiloto.tools.contracts import QueryOperationsInput, SearchPoliciesInput
from copiloto.tools.query_operations import query_operations
from copiloto.tools.search_policies import search_policies

MAX_CONTEXT_CHARS = 24_000
MAX_QUESTION_CHARS = 1_000


@dataclass
class AgentRuntime:
    settings: Settings
    user: User
    provider: LLMProvider | None
    retriever: Retriever
    tracer: Tracer
    db_path: Path | None = None
    retrieval_mode: str | None = None

    def llm(self, system: str, user: str, json_mode: bool):
        assert self.provider is not None
        resp = self.provider.generate(system, user, json_mode=json_mode,
                                      timeout_s=self.settings.llm_timeout_seconds)
        self.tracer.add_usage(resp.usage.prompt_tokens, resp.usage.completion_tokens,
                              resp.usage.reported_by_provider,
                              estimated=estimate_tokens(system + user + resp.text))
        return resp


def node_validate(rt: AgentRuntime):
    def run(state: AgentState) -> AgentState:
        with rt.tracer.step("validate"):
            q = (state.get("question") or "").strip()
            if not q:
                return {"status": "failed", "error": "pergunta vazia"}
            if len(q) > MAX_QUESTION_CHARS:
                return {"status": "failed",
                        "error": f"pergunta acima de {MAX_QUESTION_CHARS} caracteres"}
            return {"status": "analyzing", "injection_flags": planner.detect_injection(q),
                    "reference_month": state.get("reference_month") or REFERENCE_MONTH}
    return run


def node_plan(rt: AgentRuntime):
    def run(state: AgentState) -> AgentState:
        with rt.tracer.step("plan") as rec:
            intent, steps = planner.plan(state["question"], state["reference_month"])
            steps = steps[: rt.settings.max_tool_calls]
            rec.meta["intent"] = intent
            rec.meta["n_tools"] = len(steps)
            if not steps:
                return {"intent": intent, "plan": [], "status": "insufficient",
                        "limitations": [("A pergunta não corresponde a nenhuma consulta ou "
                                         "política disponível (fora de escopo).")]}
            return {"intent": intent, "plan": steps, "status": "retrieving"}
    return run


def node_tools(rt: AgentRuntime):
    def run(state: AgentState) -> AgentState:
        data, hits, mode = [], [], None
        lims = list(state.get("limitations", []))
        for step in state["plan"]:
            tool, args = step["tool"], step["args"]
            with rt.tracer.step(f"tool:{tool}", args=args) as rec:
                rt.tracer.tool_used(tool)
                try:
                    if tool == "query_operations":
                        out = query_operations(QueryOperationsInput(**args), rt.db_path)
                        data.append(out)
                        if not out.data_sufficient:
                            lims.append(f"{out.metric} ({out.month}): "
                                        f"{out.note or 'dados insuficientes'}")
                    elif tool == "search_policies":
                        out = search_policies(SearchPoliciesInput(**args), rt.user,
                                              rt.retriever, mode=rt.retrieval_mode)
                        hits.extend(out.hits)
                        mode = out.retrieval_mode
                        rec.meta["hits"] = [h.chunk_id for h in out.hits]
                        rec.meta["filtered_out"] = out.filtered_out_count
                        if not out.hits:
                            lims.append("Nenhuma política relevante encontrada para a pergunta.")
                    else:
                        raise ValueError(f"ferramenta não permitida: {tool}")
                except (ValidationError, ValueError) as e:
                    lims.append(f"Falha na ferramenta {tool}: {e}")
        # Quarentena: chunks com padrões de injeção NÃO entram no contexto nem nas citações.
        # Ficam apenas registrados no rastreio e nas limitações.
        flags = list(state.get("injection_flags", []))
        quarantined = [h for h in hits if planner.detect_injection(h.text)]
        if quarantined:
            ids = [h.chunk_id for h in quarantined]
            flags.extend(f"doc:{cid}" for cid in ids)
            hits = [h for h in hits if h.chunk_id not in set(ids)]
            lims.append(f"{len(ids)} trecho(s) recuperado(s) com instruções suspeitas foram "
                        f"excluídos do contexto: {', '.join(ids)}.")
            rt.tracer.trace.steps[-1].meta["quarantined"] = ids
        status = "answer_ready" if (data or hits) else "insufficient"
        if status == "insufficient":
            lims.append("Nenhuma evidência obtida das ferramentas.")
        return {"data_results": data, "policy_hits": hits, "limitations": lims,
                "injection_flags": flags, "retrieval_mode": mode or "n/a", "status": status}
    return run
