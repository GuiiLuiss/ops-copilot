"""Fluxos de aprovação exercitados na avaliação (rejeição, aprovação+retry, edição, papel)."""

from __future__ import annotations

from pathlib import Path

from copiloto import approval
from copiloto.auth import get_user
from copiloto.tools.contracts import ProposalContent


def _expect_blocked(fn, failures: list[str], msg: str) -> None:
    try:
        fn()
        failures.append(msg)
    except approval.ApprovalError:
        pass


def run_flow(case: dict, final: dict, trace, db_path: Path | None) -> list[str]:
    """Executa o fluxo de aprovação do caso e verifica invariantes de segurança."""
    failures: list[str] = []
    flow = case.get("flow")
    before = len(approval.list_history(db_path)["tasks"])
    creator = get_user(case["user"])
    gui, ana = get_user("gui.gestor"), get_user("ana.analista")
    proposal = final.get("proposal")
    if proposal is None:
        if flow or case.get("expected_tasks_created", 0) > 0:
            failures.append("sem proposta gerada")
        return failures

    row = approval.create_proposal(proposal, trace.run_id, creator, db_path)
    pid, h = row["proposal_id"], row["content_hash"]
    try:
        if flow == "reject":
            approval.decide(pid, gui, False, h, db_path)
        elif flow == "approve_execute_retry":
            approval.decide(pid, gui, True, h, db_path)
            t1 = approval.execute(pid, gui, db_path)
            t2 = approval.execute(pid, gui, db_path)
            if t1["task_id"] != t2["task_id"]:
                failures.append("retry criou tarefa duplicada")
        elif flow == "approve_edit_execute":
            approval.decide(pid, gui, True, h, db_path)
            edited = ProposalContent(**{**proposal.model_dump(), "priority": "baixa"})
            approval.edit_proposal(pid, edited, ana, db_path)
            _expect_blocked(lambda: approval.execute(pid, gui, db_path), failures,
                            "execução após edição deveria ser bloqueada")
        elif flow == "analyst_tries_approve":
            _expect_blocked(lambda: approval.decide(pid, ana, True, h, db_path), failures,
                            "analista conseguiu aprovar")
            _expect_blocked(lambda: approval.execute(pid, ana, db_path), failures,
                            "analista conseguiu executar")
        elif flow is None:
            # Sem fluxo explícito: garantir que nada foi executado automaticamente
            _expect_blocked(lambda: approval.execute(pid, gui, db_path), failures,
                            "execução sem aprovação deveria ser bloqueada")
    except approval.ApprovalError as e:
        failures.append(f"erro inesperado no fluxo: {e}")

    final_state = approval.get_proposal(pid, db_path)["state"]
    exp_state = case.get("expected_final_proposal_state")
    if exp_state and final_state != exp_state:
        failures.append(f"estado final {final_state} != {exp_state}")
    created = len(approval.list_history(db_path)["tasks"]) - before
    if "expected_tasks_created" in case and created != case["expected_tasks_created"]:
        failures.append(f"tarefas criadas {created} != {case['expected_tasks_created']}")
    return failures
