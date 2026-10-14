"""Testes de integração da API (modo determinístico, banco temporário)."""

import pytest
from fastapi.testclient import TestClient

from copiloto.api import app as app_module
from copiloto.config import get_settings


@pytest.fixture(scope="module")
def client(tmp_path_factory, synthetic_db):
    import copiloto.approval as approval_mod
    import copiloto.config as config_mod
    import copiloto.data.db as db_mod

    tmp = tmp_path_factory.mktemp("api")
    s = get_settings().model_copy(update={
        "llm_provider": "none", "retrieval_mode": "lexical",
        "db_path": synthetic_db, "log_dir": tmp / "logs",
    })
    originals = {}
    for mod in (app_module, approval_mod, db_mod, config_mod):
        originals[mod] = mod.get_settings
        mod.get_settings = lambda: s  # injeta configuração de teste
    yield TestClient(app_module.app)
    for mod, fn in originals.items():
        mod.get_settings = fn


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["synthetic_data"] and body["demo_auth"]
    assert body["reference_month"] == "2025-09"


def test_ask_and_full_approval_flow(client):
    r = client.post("/ask", json={"question": "Por que os cancelamentos aumentaram neste mês?",
                                  "want_proposal": True, "use_llm": False},
                    headers={"X-Demo-User": "ana.analista"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "awaiting_approval"
    assert body["proposal"]["state"] == "awaiting_approval"
    pid, h = body["proposal"]["proposal_id"], body["proposal"]["content_hash"]

    # analista não aprova
    r = client.post(f"/proposals/{pid}/decision", json={"approve": True, "content_hash": h},
                    headers={"X-Demo-User": "ana.analista"})
    assert r.status_code == 403

    # executar sem aprovação é bloqueado
    r = client.post(f"/proposals/{pid}/execute", headers={"X-Demo-User": "gui.gestor"})
    assert r.status_code == 409

    # gestor aprova e executa; retry não duplica
    r = client.post(f"/proposals/{pid}/decision", json={"approve": True, "content_hash": h},
                    headers={"X-Demo-User": "gui.gestor"})
    assert r.status_code == 200 and r.json()["state"] == "approved"
    t1 = client.post(f"/proposals/{pid}/execute", headers={"X-Demo-User": "gui.gestor"}).json()
    t2 = client.post(f"/proposals/{pid}/execute", headers={"X-Demo-User": "gui.gestor"}).json()
    assert t1["task_id"] == t2["task_id"] and t2["idempotent_replay"]
    hist = client.get("/history", headers={"X-Demo-User": "gui.gestor"}).json()
    assert len([t for t in hist["tasks"] if t["proposal_id"] == pid]) == 1


def test_tool_endpoint_rejects_bad_params(client):
    r = client.post("/tools/query_operations",
                    json={"metric": "cancellation_rate", "month": "2025-99"})
    assert r.status_code == 422


def test_search_respects_role(client):
    q = {"query": "multa contratual transportadora"}
    a = client.post("/tools/search_policies", json=q, headers={"X-Demo-User": "ana.analista"})
    g = client.post("/tools/search_policies", json=q, headers={"X-Demo-User": "gui.gestor"})
    assert all(h["doc_id"] != "POL-007" for h in a.json()["hits"])
    assert any(h["doc_id"] == "POL-007" for h in g.json()["hits"])


def test_unknown_user(client):
    r = client.get("/history", headers={"X-Demo-User": "intruso"})
    assert r.status_code == 401


def test_llm_requested_but_disabled(client):
    r = client.post("/ask", json={"question": "cancelamentos", "use_llm": True})
    assert r.status_code == 400
