"""Testes de aprovação humana, idempotência, revogação e autorização."""

import pytest

from copiloto import approval
from copiloto.auth import get_user
from copiloto.tools.contracts import ProposalContent

ANA = get_user("ana.analista")
GUI = get_user("gui.gestor")


def _content(**over):
    base = {"title": "Investigar cancelamentos com RapidoLog", "owner_role": "logistica",
            "description": "Taxa de 12,6% vs 8,0%. Abrir revisão operacional.",
            "priority": "alta", "evidence_refs": ["metric:period_comparison"]}
    base.update(over)
    return ProposalContent(**base)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "approval.db"


def test_full_flow_approve_execute_idempotent(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    assert p["state"] == "awaiting_approval"
    assert approval.list_history(db)["tasks"] == []

    approval.decide(p["proposal_id"], GUI, True, p["content_hash"], db)
    t1 = approval.execute(p["proposal_id"], GUI, db)
    t2 = approval.execute(p["proposal_id"], GUI, db)  # retry
    assert t1["task_id"] == t2["task_id"]
    assert t2["idempotent_replay"] is True
    assert len(approval.list_history(db)["tasks"]) == 1
    assert approval.get_proposal(p["proposal_id"], db)["state"] == "executed"


def test_analyst_cannot_approve_or_execute(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    with pytest.raises(approval.ApprovalError):
        approval.decide(p["proposal_id"], ANA, True, p["content_hash"], db)
    with pytest.raises(approval.ApprovalError):
        approval.execute(p["proposal_id"], ANA, db)
    assert approval.list_history(db)["tasks"] == []


def test_execute_without_approval_is_blocked(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    with pytest.raises(approval.ApprovalError):
        approval.execute(p["proposal_id"], GUI, db)
    assert approval.list_history(db)["tasks"] == []


def test_rejected_cannot_execute(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    approval.decide(p["proposal_id"], GUI, False, p["content_hash"], db)
    with pytest.raises(approval.ApprovalError):
        approval.execute(p["proposal_id"], GUI, db)


def test_wrong_hash_rejected(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    with pytest.raises(approval.ApprovalError, match="mudou"):
        approval.decide(p["proposal_id"], GUI, True, "deadbeef", db)


def test_edit_after_approval_revokes(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    approval.decide(p["proposal_id"], GUI, True, p["content_hash"], db)
    edited = approval.edit_proposal(p["proposal_id"], _content(priority="baixa"), ANA, db)
    assert edited["state"] == "awaiting_approval"
    assert edited["content_hash"] != p["content_hash"]
    with pytest.raises(approval.ApprovalError):
        approval.execute(p["proposal_id"], GUI, db)
    audit = approval.list_history(db)["audit"]
    assert any(a["event"] == "proposal_edited" and '"approval_revoked": true' in a["details"]
               for a in audit)


def test_expired_proposal(db):
    p = approval.create_proposal(_content(), "run1", ANA, db, ttl_minutes=-1)
    with pytest.raises(approval.ApprovalError, match="expirada"):
        approval.decide(p["proposal_id"], GUI, True, p["content_hash"], db)
    assert approval.get_proposal(p["proposal_id"], db)["state"] == "expired"


def test_cannot_edit_executed(db):
    p = approval.create_proposal(_content(), "run1", ANA, db)
    approval.decide(p["proposal_id"], GUI, True, p["content_hash"], db)
    approval.execute(p["proposal_id"], GUI, db)
    with pytest.raises(approval.ApprovalError):
        approval.edit_proposal(p["proposal_id"], _content(priority="baixa"), GUI, db)
