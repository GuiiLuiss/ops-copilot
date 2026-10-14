"""Testes do agente em modo determinístico (fluxo principal, escopo, autorização)."""

from tests.conftest import MAIN_Q
from tests.conftest import run_case as _run


def test_main_scenario_deterministic(settings, retriever, synthetic_db):
    final, trace = _run(MAIN_Q, "ana.analista", want_proposal=True, provider=None,
                        settings=settings, retriever=retriever, synthetic_db=synthetic_db)
    assert final["status"] == "awaiting_approval"
    assert "Modo determinístico" in final["answer"]
    assert "assinante" in final["answer"] and "RapidoLog" in final["answer"]
    assert final["proposal"] is not None and "RapidoLog" in final["proposal"].title
    assert "search_policies" in trace.tools_used
    assert trace.model is None and trace.mode == "deterministico"
    assert trace.tool_calls <= settings.max_tool_calls + 1  # +1 propose_task


def test_numbers_come_from_tools(settings, retriever, synthetic_db):
    final, _ = _run(MAIN_Q, "ana.analista", provider=None, settings=settings,
                    retriever=retriever, synthetic_db=synthetic_db)
    comp = next(d for d in final["data_results"] if d.filters.get("group_by") == "segment")
    row = next(r for r in comp.rows if r["grupo"] == "assinante")
    assert f"{row['taxa_atual'] * 100:.1f}%".replace(".", ",") in final["answer"]


def test_out_of_scope_returns_insufficient(settings, retriever, synthetic_db):
    final, trace = _run("Qual a previsão do tempo amanhã?", "ana.analista", provider=None,
                        settings=settings, retriever=retriever, synthetic_db=synthetic_db)
    assert final["status"] == "insufficient"
    assert "insuficiente" in final["answer"].lower()
    assert trace.tool_calls == 0


def test_month_without_data_declares_limitation(settings, retriever, synthetic_db):
    final, _ = _run("Qual a taxa de cancelamento em 2024-01?", "ana.analista", provider=None,
                    settings=settings, retriever=retriever, synthetic_db=synthetic_db)
    assert any("pouco confiável" in lim or "insuficientes" in lim for lim in final["limitations"])


def test_analyst_cannot_cite_restricted_doc(settings, retriever, synthetic_db):
    q = "Qual a multa contratual para transportadora com SLA baixo?"
    final, _ = _run(q, "ana.analista", provider=None, settings=settings,
                    retriever=retriever, synthetic_db=synthetic_db)
    assert all(c["doc_id"] != "POL-007" for c in final["citations"])
    assert "POL-007" not in final["answer"]


def test_manager_can_cite_restricted_doc(settings, retriever, synthetic_db):
    q = "Qual a multa contratual para transportadora com SLA baixo?"
    final, _ = _run(q, "gui.gestor", provider=None, settings=settings,
                    retriever=retriever, synthetic_db=synthetic_db)
    assert any(c["doc_id"] == "POL-007" for c in final["citations"])
