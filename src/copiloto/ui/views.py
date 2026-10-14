"""Componentes de interface: resposta, proposta, histórico, qualidade e detalhes técnicos."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from copiloto import approval
from copiloto.auth import User
from copiloto.config import PROJECT_ROOT
from copiloto.retrieval.retriever import get_retriever
from copiloto.tools.contracts import ProposalContent
from copiloto.ui import presenters as pr

ABOUT_MD = """
### Sobre esta demonstração

**Ops Copilot** responde perguntas sobre a operação de uma loja online fictícia e sugere
ações, que só acontecem depois que uma pessoa com perfil de gestor aprova.

- Os dados são inventados e gerados por programa. O aumento de cancelamentos no mês de
  referência foi colocado de propósito, para testar o sistema.
- Os números vêm sempre de consultas fixas ao banco. A IA, quando ligada, só redige o texto a
  partir deles; não calcula nem inventa valores.
- As políticas citadas são trechos reais dos documentos fictícios, filtrados pela permissão
  do perfil antes da busca. Um analista não vê documentos restritos a gestores.
- Uma ação sugerida vira tarefa só depois de aprovada por um gestor, no texto exato que foi
  exibido. Editar a proposta exige nova aprovação. Clicar duas vezes não cria duas tarefas.
- Este ambiente roda no computador local e não é um sistema em produção. O que falta para
  isso está descrito em `docs/production.md`; as limitações, em `docs/limitations.md`.
"""


def _trace_mode_label(used_llm: bool, trace) -> str:
    if used_llm and trace.model:
        return f"Resposta redigida por IA ({trace.model})"
    return "Resposta montada só com os dados, sem IA"


def _render_main_text(final: dict, data: list, cits: list[dict], llm_text: bool) -> None:
    """Texto principal: redigido pela IA ou montado por regras (modo sem IA)."""
    if llm_text:
        st.markdown(final.get("answer", ""))
        return
    for f in pr.findings(data):
        st.markdown(f"- {f}")
    if not data and cits:
        st.markdown("Trechos de política encontrados para a pergunta:")
        for c in cits[:3]:
            st.markdown(f"- **{c['title']}**, {c['section']}: "
                        f"{c['text'].split(chr(10), 1)[-1].strip()[:240]}")


def render_answer(final: dict, trace, *, used_llm: bool = False) -> None:
    status = final.get("status")
    data = final.get("data_results") or []
    cits = final.get("citations", [])
    lims = final.get("limitations", [])

    if status == "failed":
        st.error("A análise não pôde ser concluída. Nenhuma ação foi executada. "
                 "Tente reformular a pergunta ou repetir em instantes.")
        if final.get("error"):
            with st.expander("Detalhe do erro"):
                st.code(str(final["error"]))
        return

    if final.get("injection_flags"):
        st.warning("A pergunta ou um documento continha instruções suspeitas. Elas foram "
                   "ignoradas e não afetaram a análise.")

    if status == "insufficient":
        st.markdown("## Resposta")
        st.info("Não há dados ou políticas suficientes para responder a essa pergunta. "
                "Experimente outra formulação ou uma das perguntas sugeridas.")
        if lims:
            with st.expander("Por quê"):
                for lim in lims:
                    st.markdown(f"- {lim}")
        return

    st.markdown("## Resposta")
    st.caption(f"{pr.ANALYSIS_STATE.get(status, status)}. {_trace_mode_label(used_llm, trace)}.")

    inds = pr.indicators(data)
    if inds:
        cols = st.columns(len(inds))
        for col, ind in zip(cols, inds, strict=True):
            col.metric(ind["label"], ind["value"], help=ind["help"])

    _render_main_text(final, data, cits, used_llm and bool(trace.model))

    if lims:
        st.markdown("### O que ainda precisa ser confirmado")
        for lim in lims:
            st.markdown(f"- {lim}")

    if cits:
        st.markdown("### Fontes consultadas")
        for c in cits:
            with st.expander(f"{c['title']}: {c['section']}"):
                st.markdown(c["text"])
                st.caption(f"Documento {c['doc_id']}, trecho {c['chunk_id']}. "
                           f"Arquivo: {c['source']}")

    if data:
        st.markdown("### O que os dados mostram")
        for d in data:
            with st.expander(pr.data_label(d)):
                st.caption(d.definition)
                if d.rows:
                    st.dataframe(pr.table_rows(d), width="stretch", hide_index=True)
                if not d.data_sufficient:
                    st.warning(f"Dados insuficientes: {d.note or 'amostra pequena ou vazia'}.")



def _evidence_labels(refs: list[str], citations: list[dict] | None) -> list[str]:
    """Rótulos legíveis das evidências, resolvidos pelo índice de documentos (não depende
    da sessão) e, como alternativa, pelas citações da resposta atual."""
    by_id = get_retriever().by_id
    out = []
    for ref in refs:
        if ref.startswith("metric:"):
            out.append(pr.METRIC_LABEL.get(ref[7:], ref[7:]))
        elif ref in by_id:
            c = by_id[ref]
            out.append(f"{c.title}: {c.section}")
        else:
            out.append(pr.evidence_label(ref, citations or []))
    return out


def render_proposal(proposal_id: str, user: User, *, citations: list[dict] | None = None,
                    heading: str = "## Ação sugerida", key_prefix: str = "a") -> None:
    p = approval.get_proposal(proposal_id)
    if p is None:
        return
    content = json.loads(p["content_json"])
    state = p["state"]
    if heading:
        st.markdown(heading)
    st.markdown(f"**{content['title']}**")
    st.markdown(f"**Situação: {pr.PROPOSAL_STATE.get(state, state)}**",
                help=pr.PROPOSAL_STATE_HELP.get(state))
    st.caption(f"Área responsável: {pr.OWNER_LABEL.get(content['owner_role'], content['owner_role'])}. "
               f"Prioridade: {pr.PRIORITY_LABEL.get(content['priority'], content['priority'])}. "
               f"Criada em {pr.local_datetime(p['created_at'])} por {p['created_by']}."
               + (f" Válida até {pr.local_datetime(p['expires_at'])}."
                  if state == "awaiting_approval" else "")
               + (f" Decidida por {p['decided_by']} em {pr.local_datetime(p['decided_at'])}."
                  if p.get("decided_by") else ""))
    st.markdown(content["description"])
    if content.get("evidence_refs"):
        with st.expander("Evidências que sustentam a sugestão"):
            for label in _evidence_labels(content["evidence_refs"], citations):
                st.markdown(f"- {label}")

    if state == "awaiting_approval":
        _proposal_controls(proposal_id, p, content, user, key_prefix)
    elif state == "approved":
        st.success("Proposta aprovada. Falta criar a tarefa.")
        if user.can_approve:
            if st.button("Criar tarefa", type="primary", key=f"{key_prefix}_ex_{proposal_id}"):
                _execute(proposal_id, user)
        else:
            st.caption("A criação da tarefa precisa de uma pessoa com perfil de gestor.")
    elif state == "executed":
        st.success("Tarefa criada. Veja em Ações e tarefas.")
    elif state == "rejected":
        st.info("Proposta rejeitada. Nenhuma tarefa foi criada.")
    elif state == "expired":
        st.info("O prazo de aprovação expirou. Faça uma nova análise para gerar outra proposta.")


def _proposal_controls(proposal_id: str, p: dict, content: dict, user: User,
                       key_prefix: str = "a") -> None:
    with st.popover("Editar proposta"):
        st.caption("Se você alterar a proposta, ela precisará de uma nova aprovação.")
        new_title = st.text_input("Título", content["title"], key=f"{key_prefix}_t_{proposal_id}")
        new_desc = st.text_area("Descrição", content["description"], key=f"{key_prefix}_d_{proposal_id}")
        owners = list(pr.OWNER_LABEL)
        new_owner = st.selectbox("Área responsável", owners,
                                 index=owners.index(content["owner_role"])
                                 if content["owner_role"] in owners else 0,
                                 format_func=lambda o: pr.OWNER_LABEL[o], key=f"{key_prefix}_o_{proposal_id}")
        prios = list(pr.PRIORITY_LABEL)
        new_prio = st.selectbox("Prioridade", prios,
                                index=prios.index(content["priority"])
                                if content["priority"] in prios else 1,
                                format_func=lambda x: pr.PRIORITY_LABEL[x],
                                key=f"{key_prefix}_p_{proposal_id}")
        if st.button("Salvar alterações", key=f"{key_prefix}_save_{proposal_id}"):
            try:
                approval.edit_proposal(proposal_id, ProposalContent(
                    **{**content, "title": new_title, "description": new_desc,
                       "owner_role": new_owner, "priority": new_prio}), user)
                st.rerun()
            except approval.ApprovalError as e:
                st.error(f"Não foi possível salvar: {e}.")
    if not user.can_approve:
        st.info("Esta proposta precisa da aprovação de uma pessoa com perfil de gestor. "
                "Troque o perfil na barra lateral para experimentar.")
        return
    c1, c2 = st.columns(2)
    if c1.button("Aprovar proposta", type="primary", key=f"{key_prefix}_ap_{proposal_id}",
                 width="stretch"):
        _decide(proposal_id, user, True, p["content_hash"])
    if c2.button("Rejeitar", key=f"{key_prefix}_rj_{proposal_id}", width="stretch"):
        _decide(proposal_id, user, False, p["content_hash"])
    st.caption("Aprovar autoriza a proposta. A tarefa é criada em uma etapa seguinte.")


def _decide(pid: str, user: User, approve: bool, h: str) -> None:
    try:
        approval.decide(pid, user, approve, h)
        st.rerun()
    except approval.ApprovalError as e:
        st.error(f"Não foi possível registrar a decisão: {e}. Nenhuma tarefa foi criada.")


def _execute(pid: str, user: User) -> None:
    try:
        t = approval.execute(pid, user)
        if t["idempotent_replay"]:
            st.info("Essa tarefa já tinha sido criada. Nada foi duplicado.")
        st.rerun()
    except approval.ApprovalError as e:
        st.error(f"Não foi possível criar a tarefa: {e}.")


def render_technical(final: dict, trace) -> None:
    with st.expander("Detalhes técnicos"):
        c1, c2, c3 = st.columns(3)
        c1.metric("Tempo total", pr.seconds(trace.total_ms))
        c2.metric("Consultas feitas", trace.tool_calls)
        tok = (f"{pr.num(trace.prompt_tokens)} + {pr.num(trace.completion_tokens)}"
               if trace.tokens_reported_by_provider else "não se aplica")
        c3.metric("Tokens (entrada + saída)", tok,
                  help="Informados pelo provedor do modelo. Tokens são a unidade de texto "
                       "que o modelo processa. Não há custo em dinheiro neste ambiente.")
        mode = final.get("retrieval_mode")
        st.caption(f"Execução {trace.run_id}. Modelo: {trace.model or 'nenhum'}. "
                   f"Prompt {trace.prompt_version}. Índice {trace.index_version}. "
                   f"Busca: {pr.RETRIEVAL_LABEL.get(mode, mode)}.")
        st.table([{"Etapa": s.name, "Tempo": pr.seconds(s.duration_ms),
                   "Resultado": "ok" if s.ok else "falha",
                   "Detalhes": json.dumps(s.meta, ensure_ascii=False)[:120]}
                  for s in trace.steps])


def render_history(user: User) -> None:
    h = approval.list_history()
    pending = [p for p in h["proposals"] if p["state"] in ("awaiting_approval", "approved")]
    done = [p for p in h["proposals"] if p["state"] not in ("awaiting_approval", "approved")]

    st.markdown("## Pendentes")
    if not pending:
        st.caption("Nenhuma proposta aguardando decisão.")
    elif user.can_approve:
        st.caption("Abra uma proposta para aprovar, rejeitar, editar ou criar a tarefa.")
    else:
        st.caption("Estas propostas aguardam uma pessoa com perfil de gestor. Você pode abrir "
                   "cada uma para ler e editar.")
    for p in pending:
        label = f"{p['title']} · {pr.PROPOSAL_STATE.get(p['state'], p['state'])}"
        with st.expander(label, expanded=len(pending) == 1):
            render_proposal(p["proposal_id"], user, heading="", key_prefix="h")

    st.markdown("## Histórico de propostas")
    st.caption("Sugestões geradas pelas análises e o que aconteceu com cada uma.")
    if done:
        st.dataframe([{
            "Título": p["title"],
            "Situação": pr.PROPOSAL_STATE.get(p["state"], p["state"]),
            "Criada por": p["created_by"],
            "Decidida por": p["decided_by"] or "",
            "Criada em": pr.local_datetime(p["created_at"]),
        } for p in done], width="stretch", hide_index=True)
    else:
        st.caption("Nenhuma proposta concluída ainda.")
    st.markdown("## Tarefas criadas")
    if h["tasks"]:
        st.dataframe([{
            "Título": t["title"], "Criada por": t["created_by"],
            "Criada em": pr.local_datetime(t["created_at"]),
        } for t in h["tasks"]], width="stretch", hide_index=True)
    else:
        st.caption("Nenhuma tarefa ainda. Tarefas só são criadas após aprovação de um gestor.")
    if h["audit"]:
        with st.expander("Registro de auditoria"):
            st.dataframe([{
                "Quando": pr.local_datetime(a["ts"]), "Quem": a["actor"], "Evento": a["event"],
                "Detalhes": a["details"] or "",
            } for a in h["audit"]], width="stretch", hide_index=True)



_METRIC_HELP = {
    "cases_passed": "Casos de teste em que a resposta atendeu a todos os critérios.",
    "numeric_checks": "Números esperados encontrados na resposta.",
    "recall_at_k_mean": "Dos documentos que deveriam ser encontrados, a fração que apareceu "
                        "entre os primeiros resultados (1,0 = todos).",
    "citation_precision_mean": "Das citações feitas, a fração que aponta para um trecho "
                               "realmente recuperado.",
    "authorization_violations": "Vezes em que um documento proibido apareceu. Esperado: 0.",
    "unapproved_executions": "Tarefas criadas sem aprovação. Esperado: 0.",
    "fake_citations_detected": "Citações inventadas pelo modelo e removidas pela validação.",
}


def render_eval() -> None:
    results_dir = PROJECT_ROOT / "evals" / "results"
    files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []
    st.markdown("## Qualidade das respostas")
    st.caption("Resultados de testes automáticos: 33 perguntas com gabarito, executadas com e "
               "sem IA. Só aparecem avaliações que foram realmente executadas.")
    if not files:
        st.info("Nenhum relatório encontrado. Execute `copiloto eval` para gerar um.")
        return
    choice = st.selectbox("Relatório", files, format_func=lambda p: p.name, index=len(files) - 1)
    rep = json.loads(Path(choice).read_text(encoding="utf-8"))
    st.caption(f"Gerado em {pr.local_datetime(rep.get('generated_at'))}. "
               f"Modelo: {rep.get('model') or 'nenhum (sem IA)'}. "
               f"Índice {rep.get('index_version')}.")
    for variant, m in rep.get("variants", {}).items():
        met = m["metrics"]
        st.markdown(f"### Busca {pr.RETRIEVAL_LABEL.get(variant, variant).lower()}")
        c = st.columns(4)
        c[0].metric("Casos corretos", f"{met['cases_passed']}/{met['cases_total']}",
                    help=_METRIC_HELP["cases_passed"])
        c[1].metric("Números exatos", met["numeric_checks"], help=_METRIC_HELP["numeric_checks"])
        c[2].metric("Vazamentos", met["authorization_violations"],
                    help=_METRIC_HELP["authorization_violations"])
        c[3].metric("Ações sem aprovação", met["unapproved_executions"],
                    help=_METRIC_HELP["unapproved_executions"])
        c = st.columns(4)
        c[0].metric("Documentos encontrados", f"{met['recall_at_k_mean']:.3f}".replace(".", ","),
                    help=_METRIC_HELP["recall_at_k_mean"])
        c[1].metric("Citações válidas",
                    f"{met['citation_precision_mean']:.2f}".replace(".", ","),
                    help=_METRIC_HELP["citation_precision_mean"])
        c[2].metric("Citações inventadas", met.get("fake_citations_detected", 0),
                    help=_METRIC_HELP["fake_citations_detected"])
        lat = met.get("llm_latency_ms") or met.get("latency_ms") or {}
        c[3].metric("Tempo típico", pr.seconds(lat.get("p50")),
                    help="Mediana: metade das execuções foi mais rápida que isso.")
        fails = [x for x in m["cases"] if not x["passed"]]
        if fails:
            with st.expander(f"{len(fails)} caso(s) com falha"):
                st.dataframe([{"Caso": x["id"], "Categoria": x["category"],
                               "O que falhou": "; ".join(x["failures"])} for x in fails],
                             width="stretch", hide_index=True)
        with st.expander("Todas as métricas"):
            st.json(met)
