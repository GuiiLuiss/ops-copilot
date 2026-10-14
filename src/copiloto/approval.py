"""Aprovação humana e execução idempotente: operação da aplicação, fora do LLM.

Garantias:
- A aprovação é vinculada ao hash exato do conteúdo, ao usuário e a um prazo.
- Só o papel "gestor" aprova. Reavaliado no momento da aprovação e da execução.
- Editar a proposta gera um novo hash → aprovação anterior revogada.
- Execução usa chave de idempotência (proposal_id + hash): retries não duplicam.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from copiloto.auth import User
from copiloto.config import get_settings
from copiloto.data.db import read_connection, write_connection
from copiloto.tools.contracts import ProposalContent


class ApprovalError(PermissionError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def content_hash(content: ProposalContent) -> str:
    payload = json.dumps(content.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _audit(conn, run_id, actor, event, details=None):
    conn.execute("INSERT INTO audit_log (ts, run_id, actor, event, details) VALUES (?,?,?,?,?)",
                 (_now().isoformat(), run_id, actor, event,
                  json.dumps(details, ensure_ascii=False) if details else None))


def _fetch(conn, proposal_id: str):
    p = conn.execute("SELECT * FROM action_proposals WHERE proposal_id=?",
                     (proposal_id,)).fetchone()
    if p is None:
        raise ApprovalError("proposta não encontrada")
    return p


def create_proposal(content: ProposalContent, run_id: str, creator: User,
                    db_path: Path | None = None, ttl_minutes: int | None = None) -> dict:
    ttl = ttl_minutes or get_settings().approval_ttl_minutes
    pid = f"prop_{uuid.uuid4().hex[:10]}"
    now = _now()
    row = {
        "proposal_id": pid, "run_id": run_id, "title": content.title,
        "content_json": json.dumps(content.model_dump(), ensure_ascii=False),
        "content_hash": content_hash(content), "state": "awaiting_approval",
        "created_by": creator.user_id, "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ttl)).isoformat(),
    }
    with write_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO action_proposals (proposal_id, run_id, title, content_json, content_hash,
               state, created_by, created_at, expires_at)
               VALUES (:proposal_id, :run_id, :title, :content_json, :content_hash, :state,
                       :created_by, :created_at, :expires_at)""", row)
        _audit(conn, run_id, creator.user_id, "proposal_created", {"proposal_id": pid})
    return row


def get_proposal(proposal_id: str, db_path: Path | None = None) -> dict | None:
    with read_connection(db_path) as conn:
        r = conn.execute("SELECT * FROM action_proposals WHERE proposal_id = ?",
                         (proposal_id,)).fetchone()
    return dict(r) if r else None


def edit_proposal(proposal_id: str, new_content: ProposalContent, editor: User,
                  db_path: Path | None = None) -> dict:
    """Editar muda o hash e revoga qualquer aprovação anterior."""
    with write_connection(db_path) as conn:
        p = _fetch(conn, proposal_id)
        if p["state"] == "executed":
            raise ApprovalError("proposta já executada; não pode ser editada")
        prev_state = p["state"]
        conn.execute(
            """UPDATE action_proposals SET content_json=?, content_hash=?, title=?,
               state='awaiting_approval', decided_by=NULL, decided_at=NULL, decision_hash=NULL
               WHERE proposal_id=?""",
            (json.dumps(new_content.model_dump(), ensure_ascii=False),
             content_hash(new_content), new_content.title, proposal_id))
        _audit(conn, p["run_id"], editor.user_id, "proposal_edited",
               {"proposal_id": proposal_id, "previous_state": prev_state,
                "approval_revoked": prev_state == "approved"})
    return get_proposal(proposal_id, db_path)


def decide(proposal_id: str, approver: User, approve: bool, expected_hash: str,
           db_path: Path | None = None) -> dict:
    """Aprova/rejeita. Exige papel gestor, hash igual ao exibido e prazo válido."""
    if not approver.can_approve:
        raise ApprovalError(f"papel '{approver.role}' não pode aprovar propostas")
    with write_connection(db_path) as conn:
        p = _fetch(conn, proposal_id)
        if p["state"] != "awaiting_approval":
            raise ApprovalError(f"proposta no estado '{p['state']}', não aguarda decisão")
        if p["content_hash"] != expected_hash:
            raise ApprovalError("o conteúdo da proposta mudou desde a exibição; revise antes")
        if datetime.fromisoformat(p["expires_at"]) < _now():
            conn.execute("UPDATE action_proposals SET state='expired' WHERE proposal_id=?",
                         (proposal_id,))
            _audit(conn, p["run_id"], approver.user_id, "proposal_expired",
                   {"proposal_id": proposal_id})
            conn.commit()  # persiste a expiração antes de sinalizar o erro
            raise ApprovalError("proposta expirada")
        state = "approved" if approve else "rejected"
        conn.execute(
            """UPDATE action_proposals SET state=?, decided_by=?, decided_at=?, decision_hash=?
               WHERE proposal_id=?""",
            (state, approver.user_id, _now().isoformat(), expected_hash, proposal_id))
        _audit(conn, p["run_id"], approver.user_id, f"proposal_{state}",
               {"proposal_id": proposal_id, "hash": expected_hash[:12]})
    return get_proposal(proposal_id, db_path)



def execute(proposal_id: str, executor: User, db_path: Path | None = None) -> dict:
    """Registra a tarefa de forma idempotente. Revalida permissão, estado e hash."""
    if not executor.can_approve:
        raise ApprovalError(f"papel '{executor.role}' não pode executar propostas")
    with write_connection(db_path) as conn:
        p = _fetch(conn, proposal_id)
        key = f"{proposal_id}:{p['content_hash']}"
        existing = conn.execute("SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
        if existing:
            _audit(conn, p["run_id"], executor.user_id, "task_execute_idempotent_hit",
                   {"task_id": existing["task_id"]})
            return {**dict(existing), "idempotent_replay": True}
        if p["state"] != "approved":
            raise ApprovalError(f"proposta no estado '{p['state']}'; só aprovadas podem executar")
        if p["decision_hash"] != p["content_hash"]:
            raise ApprovalError("aprovação não corresponde ao conteúdo atual (revogada)")
        task = {
            "task_id": f"task_{uuid.uuid4().hex[:10]}", "proposal_id": proposal_id,
            "idempotency_key": key, "title": p["title"], "content_json": p["content_json"],
            "created_by": executor.user_id, "created_at": _now().isoformat(),
        }
        conn.execute(
            """INSERT INTO tasks (task_id, proposal_id, idempotency_key, title, content_json,
               created_by, created_at) VALUES (:task_id, :proposal_id, :idempotency_key, :title,
               :content_json, :created_by, :created_at)""", task)
        conn.execute("UPDATE action_proposals SET state='executed' WHERE proposal_id=?",
                     (proposal_id,))
        _audit(conn, p["run_id"], executor.user_id, "task_created", {"task_id": task["task_id"]})
    return {**task, "idempotent_replay": False}


def list_history(db_path: Path | None = None, limit: int = 50) -> dict:
    with read_connection(db_path) as conn:
        props = [dict(r) for r in conn.execute(
            "SELECT * FROM action_proposals ORDER BY created_at DESC LIMIT ?", (limit,))]
        tasks = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))]
        audit = [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]
    return {"proposals": props, "tasks": tasks, "audit": audit}
