"""Componentes de interface: resposta, fontes, rastreio, proposta, histórico e avaliação."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from copiloto import approval
from copiloto.auth import User
from copiloto.config import PROJECT_ROOT
from copiloto.tools.contracts import ProposalContent

ABOUT_MD = """
### Sobre esta demonstração
- **Empresa e dados fictícios**, gerados com seed fixa. O aumento de cancelamentos no mês de
  referência foi introduzido de propósito para testar o sistema.
- **Modo determinístico**: sem LLM; a resposta é montada só com os números das ferramentas e
  trechos recuperados. **Modo LLM**: provedor `{provider}` redige a resposta a partir das mesmas
  evidências; números e citações são validados antes de exibir.
- **Aprovação humana**: a tarefa só é registrada após um **gestor** aprovar o conteúdo exato
  (hash). Editar a proposta revoga a aprovação; reexecutar não duplica.
- **Autorização** por papel é aplicada no backend antes da recuperação; documentos restritos
  nunca entram no contexto de um analista.
- Este ambiente **não** é um sistema em produção. Veja `docs/limitations.md`.
"""

_BADGE = {"answer_ready": "[OK]", "awaiting_approval": "[AGUARDANDO APROVAÇÃO]",
          "insufficient": "[INSUFICIENTE]", "failed": "[FALHA]"}


def render_answer(final: dict, trace) -> None:
    status = final.get("status")
    mode = f"LLM {trace.model}" if trace.model else "determinístico"
    st.markdown(f"{_BADGE.get(status, '')} **Estado:** `{status}` - run `{trace.run_id}` - "
                f"{mode} - {trace.total_ms} ms")
    if final.get("injection_flags"):
        st.error("Instruções suspeitas detectadas (entrada ou documento) e ignoradas: "
                 + ", ".join(final["injection_flags"]))
    st.markdown(final.get("answer", ""))

    cits = final.get("citations", [])
    if cits:
        st.markdown("**Fontes**")
        for c in cits:
            with st.expander(f"[{c['chunk_id']}] {c['title']} - {c['section']}"):
                st.markdown(c["text"])
                st.caption(f"Fonte local: `{c['source']}`")
    if final.get("limitations"):
        with st.expander("Limitações desta resposta", expanded=status == "insufficient"):
            for lim in final["limitations"]:
                st.markdown(f"- {lim}")

    with st.expander("Rastreio da execução (ferramentas, tempos, tokens)"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Chamadas de ferramenta", trace.tool_calls)
        c2.metric("Tempo total (ms)", trace.total_ms)
        tok = (f"{trace.prompt_tokens}+{trace.completion_tokens}"
               if trace.tokens_reported_by_provider else "-")
        c3.metric("Tokens (provedor)", tok)
        c4.metric("Tokens (estimados)", trace.tokens_estimated or "-")
        st.caption("Tokens do provedor = reportados pela API; estimados = ~4 chars/token. "
                   "Sem tabela de preços vigente, não é exibido custo em dinheiro.")
        st.table([{"etapa": s.name, "ms": s.duration_ms, "ok": s.ok,
                   "detalhes": json.dumps(s.meta, ensure_ascii=False)[:120]}
                  for s in trace.steps])
        st.caption(f"prompt `{trace.prompt_version}` - índice `{trace.index_version}` - "
                   f"recuperação `{final.get('retrieval_mode')}`")
    data = final.get("data_results") or []
    if data:
        with st.expander("Dados consultados (saída bruta das ferramentas)"):
            for d in data:
                head = f"**{d.metric}** - {d.month}"
                if d.compare_to:
                    head += f" vs {d.compare_to}"
                if d.filters:
                    head += f" - filtros {d.filters}"
                st.markdown(head)
                st.caption(d.definition)
                st.json(d.summary)
                if d.rows:
                    st.dataframe(d.rows, width="stretch", hide_index=True)



def render_proposal(proposal_id: str, user: User) -> None:
    p = approval.get_proposal(proposal_id)
    if p is None:
        return
    content = json.loads(p["content_json"])
    st.divider()
    st.subheader("Proposta de ação (requer aprovação humana)")
    st.markdown(f"**Estado:** `{p['state']}` - criada por `{p['created_by']}` - "
                f"expira `{p['expires_at'][:16]}` - hash `{p['content_hash'][:12]}...`")
    st.markdown(f"**{content['title']}**")
    st.markdown(content["description"])
    st.caption(f"Responsável: {content['owner_role']} - prioridade: {content['priority']} - "
               f"evidências: {', '.join(content['evidence_refs']) or '-'}")

    if p["state"] == "awaiting_approval":
        with st.expander("Editar proposta (revoga aprovações anteriores)"):
            new_title = st.text_input("Título", content["title"], key=f"t_{proposal_id}")
            new_desc = st.text_area("Descrição", content["description"], key=f"d_{proposal_id}")
            if st.button("Salvar edição", key=f"save_{proposal_id}"):
                approval.edit_proposal(proposal_id, ProposalContent(
                    **{**content, "title": new_title, "description": new_desc}), user)
                st.rerun()
        c1, c2, _ = st.columns([1, 1, 4])
        if not user.can_approve:
            st.info("Somente o papel **gestor** pode aprovar ou rejeitar. Troque o usuário na "
                    "barra lateral para demonstrar.")
        if c1.button("Aprovar", disabled=not user.can_approve, key=f"ap_{proposal_id}"):
            _decide(proposal_id, user, True, p["content_hash"])
        if c2.button("Rejeitar", disabled=not user.can_approve, key=f"rj_{proposal_id}"):
            _decide(proposal_id, user, False, p["content_hash"])
    elif p["state"] == "approved":
        if st.button("Registrar tarefa (idempotente)", disabled=not user.can_approve,
                     key=f"ex_{proposal_id}"):
            try:
                t = approval.execute(proposal_id, user)
                st.success(f"Tarefa `{t['task_id']}` registrada"
                           + (" (replay idempotente)" if t["idempotent_replay"] else ""))
                st.rerun()
            except approval.ApprovalError as e:
                st.error(str(e))
    elif p["state"] == "executed":
        st.success("Tarefa registrada. Veja a aba *Propostas e tarefas*.")
    else:
        st.info(f"Proposta em estado `{p['state']}`.")


def _decide(pid: str, user: User, approve: bool, h: str) -> None:
    try:
        approval.decide(pid, user, approve, h)
        st.rerun()
    except approval.ApprovalError as e:
        st.error(str(e))


def render_history(user: User) -> None:
    h = approval.list_history()
    st.subheader("Propostas")
    if h["proposals"]:
        st.dataframe([{k: p[k] for k in ("proposal_id", "title", "state", "created_by",
                                         "decided_by", "created_at")} for p in h["proposals"]],
                     width="stretch", hide_index=True)
    else:
        st.caption("Nenhuma proposta ainda.")
    st.subheader("Tarefas registradas")
    if h["tasks"]:
        st.dataframe([{k: t[k] for k in ("task_id", "proposal_id", "title", "created_by",
                                         "created_at")} for t in h["tasks"]],
                     width="stretch", hide_index=True)
    else:
        st.caption("Nenhuma tarefa registrada - nada é escrito sem aprovação.")
    st.subheader("Auditoria")
    if h["audit"]:
        st.dataframe(h["audit"], width="stretch", hide_index=True)


def render_eval() -> None:
    results_dir = PROJECT_ROOT / "evals" / "results"
    files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []
    if not files:
        st.info("Nenhum relatório de avaliação encontrado. Execute "
                "`copiloto eval` para gerar `evals/results/*.json`.")
        return
    choice = st.selectbox("Relatório", files, format_func=lambda p: p.name, index=len(files) - 1)
    rep = json.loads(Path(choice).read_text(encoding="utf-8"))
    st.caption(f"Gerado em {rep.get('generated_at')} - modo {rep.get('mode')} - "
               f"modelo {rep.get('model')} - índice {rep.get('index_version')}")
    for variant, m in rep.get("variants", {}).items():
        st.markdown(f"#### Variante `{variant}`")
        st.json(m["metrics"])
        fails = [c for c in m["cases"] if not c["passed"]]
        if fails:
            with st.expander(f"{len(fails)} caso(s) com falha"):
                st.dataframe([{"id": c["id"], "categoria": c["category"],
                               "falhas": "; ".join(c["failures"])} for c in fails],
                             width="stretch", hide_index=True)
