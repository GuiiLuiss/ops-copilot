"""Interface Streamlit do Copiloto de Operações (demonstração local, dados sintéticos)."""

from __future__ import annotations

import streamlit as st

from copiloto import approval
from copiloto.agents.graph import run_agent
from copiloto.auth import DEMO_USERS, get_user
from copiloto.config import DATA_MONTHS, REFERENCE_MONTH, get_settings
from copiloto.providers import get_provider
from copiloto.retrieval.retriever import get_retriever
from copiloto.ui import views

st.set_page_config(page_title="Copiloto de Operações", page_icon=":compass:", layout="wide")

EXAMPLES = [
    "Por que os cancelamentos aumentaram neste mês e quais ações podemos tomar?",
    "Qual a taxa de cancelamento do segmento assinante em setembro?",
    "Qual o desempenho de entrega por transportadora neste mês?",
    "Qual é a política vigente de cancelamento por atraso?",
    "Qual a multa contratual para transportadora com SLA baixo?",
    "Qual era a regra de cancelamento em junho de 2025?",
    "Qual a taxa de cancelamento em 2024-01?",
]
RETRIEVAL_MODES = ["lexical", "hybrid", "vector"]

settings = get_settings()
provider = get_provider(settings)
llm_ok, llm_msg = provider.is_available() if provider else (False, "COPILOTO_LLM_PROVIDER=none")

with st.sidebar:
    st.header("Copiloto de Operações")
    st.warning("**Demonstração local com dados sintéticos.** A seleção de usuário abaixo "
               "NÃO é autenticação segura.")
    user_id = st.selectbox("Usuário (modo demo)", list(DEMO_USERS),
                           format_func=lambda u: DEMO_USERS[u].name)
    user = get_user(user_id)
    use_llm = st.toggle("Usar LLM", value=llm_ok, disabled=not llm_ok,
                        help=f"Provedor: {settings.llm_provider} - {llm_msg}")
    if use_llm and provider:
        st.markdown(f"**Modo LLM:** `{provider.model_id()}`")
    else:
        st.markdown("**Modo determinístico** (sem inferência de LLM)")
    retrieval_mode = st.selectbox("Recuperação", RETRIEVAL_MODES,
                                  index=RETRIEVAL_MODES.index(settings.retrieval_mode))
    want_proposal = st.checkbox("Gerar proposta de ação", value=True)
    st.divider()
    st.caption(f"Mês de referência: **{REFERENCE_MONTH}** (dados: {', '.join(DATA_MONTHS)})")
    r = get_retriever()
    st.caption(f"Índice: `{r.index_version}` - {len(r.chunks)} chunks")
    if r.vector_error:
        st.caption(f"Vetorial indisponível: {r.vector_error[:80]}")

tab_chat, tab_hist, tab_eval, tab_about = st.tabs(
    ["Chat", "Propostas e tarefas", "Avaliação", "Sobre"])

with tab_chat:
    st.subheader("Pergunte sobre pedidos, cancelamentos, entregas e políticas")
    st.session_state.setdefault("question_input", "")
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 2].button(ex, key=f"ex{i}", width="stretch"):
            st.session_state["question_input"] = ex
    question = st.text_input("Pergunta", key="question_input")
    if st.button("Perguntar", type="primary", key="ask_btn") and question.strip():
        with st.spinner("Consultando ferramentas e políticas..."):
            final, trace = run_agent(
                question, user.user_id, want_proposal=want_proposal, settings=settings,
                provider=provider if use_llm else None, retrieval_mode=retrieval_mode)
        row = None
        if final.get("proposal") is not None:
            row = approval.create_proposal(final["proposal"], trace.run_id, user)
        st.session_state["last"] = {"final": final, "trace": trace, "proposal_row": row}

    last = st.session_state.get("last")
    if last:
        views.render_answer(last["final"], last["trace"])
        if last["proposal_row"]:
            views.render_proposal(last["proposal_row"]["proposal_id"], user)

with tab_hist:
    views.render_history(user)

with tab_eval:
    views.render_eval()

with tab_about:
    st.markdown(views.ABOUT_MD.format(provider=settings.llm_provider))
    st.json({"llm_provider": settings.llm_provider, "retrieval_mode": settings.retrieval_mode,
             "max_tool_calls": settings.max_tool_calls,
             "approval_ttl_minutes": settings.approval_ttl_minutes})
