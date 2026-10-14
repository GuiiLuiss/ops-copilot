"""Interface Streamlit do Ops Copilot (demonstração local, dados fictícios)."""

from __future__ import annotations

import streamlit as st

from copiloto import approval
from copiloto.agents.graph import run_agent
from copiloto.auth import DEMO_USERS, get_user
from copiloto.config import DATA_MONTHS, REFERENCE_MONTH, get_settings
from copiloto.providers import get_provider
from copiloto.retrieval.retriever import get_retriever
from copiloto.ui import presenters as pr
from copiloto.ui import views

st.set_page_config(page_title="Ops Copilot", page_icon=":compass:", layout="centered")

# CSS mínimo: largura de leitura e espaçamento. Sem seletores de classes internas.
st.markdown(
    """<style>
    .block-container { max-width: 980px; padding-top: 1.5rem; }
    h1 { font-size: 1.9rem; margin-bottom: 0.2rem; }
    h2 { font-size: 1.35rem; margin-top: 1.4rem; }
    h3 { font-size: 1.1rem; margin-top: 1.1rem; }
    [data-testid="stMetricValue"] { font-size: 1.5rem; }
    </style>""",
    unsafe_allow_html=True,
)

SUGGESTED = [
    "Como os cancelamentos mudaram neste mês?",
    "Quais transportadoras estão entregando com atraso?",
    "O que a política diz sobre cancelamento por atraso?",
]
RETRIEVAL_MODES = ["lexical", "hybrid", "vector"]

settings = get_settings()
provider = get_provider(settings)
llm_ok, llm_msg = provider.is_available() if provider else (False, "nenhum provedor configurado")
retriever = get_retriever()
available_modes = [m for m in RETRIEVAL_MODES if m == "lexical" or not retriever.vector_error]

# ---------------------------------------------------------------- barra lateral
with st.sidebar:
    st.markdown("## Ops Copilot")
    st.caption("Demonstração com dados fictícios.")
    user_id = st.selectbox("Perfil da demonstração", list(DEMO_USERS),
                           format_func=lambda u: DEMO_USERS[u].name)
    user = get_user(user_id)
    st.caption("Troque o perfil para experimentar diferentes permissões. "
               "Esta opção não é um login.")
    st.markdown(f"**{user.name.split(' (')[0]}**, {pr.ROLE_LABEL.get(user.role, user.role)}")
    st.markdown(f"Período de referência: **{pr.month_label(REFERENCE_MONTH)}**  \n"
                f"Dados disponíveis: {pr.month_range_label(DATA_MONTHS)}")

    with st.expander("Configurações avançadas"):
        use_llm = st.toggle("Usar IA para elaborar a resposta", value=llm_ok, disabled=not llm_ok,
                            help="Desligado, a resposta mostra os números e os trechos de "
                                 "política encontrados, sem texto redigido por IA.")
        if provider and llm_ok:
            st.caption(f"Provedor: {settings.llm_provider}. Modelo: {provider.model_id()}.")
        elif provider:
            st.caption(f"Modelo de IA indisponível: {llm_msg}")
        else:
            st.caption("Nenhum modelo de IA configurado. Defina COPILOTO_LLM_PROVIDER no .env.")
        retrieval_mode = st.selectbox(
            "Método de busca nas políticas", available_modes,
            index=available_modes.index(settings.retrieval_mode)
            if settings.retrieval_mode in available_modes else 0,
            format_func=lambda m: pr.RETRIEVAL_LABEL[m])
        st.caption(f"Índice {retriever.index_version}, {len(retriever.chunks)} trechos de "
                   f"documentos.")
        if retriever.vector_error:
            st.caption("Busca por significado indisponível neste ambiente "
                       "(instale o extra `vector`).")

# ---------------------------------------------------------------- cabeçalho
st.title("Ops Copilot")
st.markdown("Entenda seus dados e transforme análises em ações.")

tab_ask, tab_actions, tab_quality, tab_about = st.tabs(
    ["Analisar", "Ações e tarefas", "Qualidade das respostas", "Sobre"])


# ---------------------------------------------------------------- analisar
with tab_ask:
    st.markdown("## O que você quer entender sobre a operação?")
    st.caption(f"Pedidos, cancelamentos, entregas, chamados de atendimento e políticas "
               f"internas. \"Neste mês\" significa {pr.month_label(REFERENCE_MONTH)}.")
    st.session_state.setdefault("question_input", "")
    cols = st.columns(len(SUGGESTED))
    for i, ex in enumerate(SUGGESTED):
        if cols[i].button(ex, key=f"ex{i}", width="stretch"):
            st.session_state["question_input"] = ex
    question = st.text_area("Sua pergunta", key="question_input", height=80,
                            placeholder="Escreva aqui ou escolha uma das perguntas acima.")
    want_proposal = st.checkbox("Sugerir uma ação após a análise", value=True,
                                help="A sugestão será apresentada para revisão. Nenhuma ação "
                                     "será executada automaticamente.")
    ask = st.button("Analisar", type="primary", key="ask_btn")

    if ask and not question.strip():
        st.warning("Escreva uma pergunta antes de analisar.")
    elif ask:
        with st.status("Analisando...", expanded=True) as status:
            st.write("Consultando os pedidos e as políticas.")
            final, trace = run_agent(
                question, user.user_id, want_proposal=want_proposal, settings=settings,
                provider=provider if use_llm else None, retrieval_mode=retrieval_mode)
            st.write("Preparando a resposta.")
            status.update(label="Análise concluída.", state="complete", expanded=False)
        row = None
        if final.get("proposal") is not None:
            row = approval.create_proposal(final["proposal"], trace.run_id, user)
        st.session_state["last"] = {"final": final, "trace": trace, "proposal_row": row,
                                    "used_llm": bool(use_llm and provider)}

    last = st.session_state.get("last")
    if last:
        views.render_answer(last["final"], last["trace"], used_llm=last["used_llm"])
        if last["proposal_row"]:
            views.render_proposal(last["proposal_row"]["proposal_id"], user,
                                  citations=last["final"].get("citations", []))
        views.render_technical(last["final"], last["trace"])
    else:
        st.info("Escolha uma pergunta sugerida ou escreva a sua e clique em Analisar.")

with tab_actions:
    views.render_history(user)

with tab_quality:
    views.render_eval()

with tab_about:
    st.markdown(views.ABOUT_MD)
    with st.expander("Configuração desta instância"):
        st.json({"provedor_ia": settings.llm_provider,
                 "metodo_busca_padrao": settings.retrieval_mode,
                 "maximo_de_consultas_por_pergunta": settings.max_tool_calls,
                 "validade_da_aprovacao_minutos": settings.approval_ttl_minutes})
