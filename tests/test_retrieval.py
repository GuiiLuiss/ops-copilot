"""Testes de ingestão, busca lexical, autorização e vigência."""

import pytest

from copiloto.auth import get_user
from copiloto.config import PROJECT_ROOT, get_settings
from copiloto.retrieval.ingest import load_corpus
from copiloto.retrieval.retriever import Retriever, rrf
from copiloto.tools.contracts import SearchPoliciesInput
from copiloto.tools.search_policies import search_policies

POLICIES = PROJECT_ROOT / "data" / "policies"


@pytest.fixture(scope="module")
def retriever():
    s = get_settings().model_copy(update={"retrieval_mode": "lexical"})
    return Retriever(settings=s, policies_dir=POLICIES)


def test_corpus_loads_with_metadata():
    chunks = load_corpus(POLICIES)
    docs = {c.doc_id for c in chunks}
    assert {"POL-001", "POL-001-v1", "POL-007", "TEST-INJ-001"} <= docs
    assert all(c.chunk_id and c.title and c.version and c.valid_from for c in chunks)
    assert len({c.content_hash for c in chunks}) == len(chunks)


def test_analyst_finds_cancellation_policy(retriever):
    ana = get_user("ana.analista")
    out = search_policies(SearchPoliciesInput(query="política de cancelamento por atraso na entrega"),
                          ana, retriever)
    assert out.hits
    assert out.hits[0].doc_id in {"POL-001", "POL-003"}
    assert all(h.text for h in out.hits)


def test_analyst_never_sees_restricted_doc(retriever):
    ana = get_user("ana.analista")
    out = search_policies(SearchPoliciesInput(query="multa contratual transportadora renegociação"),
                          ana, retriever)
    assert all(h.doc_id != "POL-007" for h in out.hits)
    assert out.filtered_out_count > 0
    assert retriever.get_chunk("POL-007#s00", ana) is None


def test_manager_sees_restricted_doc(retriever):
    gui = get_user("gui.gestor")
    out = search_policies(SearchPoliciesInput(query="multa contratual transportadora renegociação"),
                          gui, retriever)
    assert any(h.doc_id == "POL-007" for h in out.hits)


def test_expired_policy_filtered_without_reference_date(retriever):
    ana = get_user("ana.analista")
    out = search_policies(SearchPoliciesInput(query="cancelamento taxa administrativa 24 horas"),
                          ana, retriever)
    assert all(h.doc_id != "POL-001-v1" for h in out.hits)


def test_old_policy_visible_with_past_reference_date(retriever):
    ana = get_user("ana.analista")
    out = search_policies(
        SearchPoliciesInput(query="cancelamento taxa administrativa 24 horas",
                            reference_date="2025-06-15"), ana, retriever)
    assert any(h.doc_id == "POL-001-v1" for h in out.hits)
    assert all(h.doc_id != "POL-001" for h in out.hits)  # v2 só vale a partir de 08/2025


def test_rrf_fuses_rankings():
    a = [("x", 1.0), ("y", 0.5), ("z", 0.1)]
    b = [("y", 1.0), ("x", 0.5)]
    fused = rrf([a, b])
    assert [c for c, _ in fused][:2] == ["x", "y"] or [c for c, _ in fused][:2] == ["y", "x"]
    assert fused[-1][0] == "z"


def test_empty_query_terms(retriever):
    ana = get_user("ana.analista")
    out = search_policies(SearchPoliciesInput(query="o a de"), ana, retriever)
    assert out.hits == []
