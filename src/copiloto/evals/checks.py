"""Verificações por caso: números, documentos, citações, termos e status."""

from __future__ import annotations

import re
from pathlib import Path

from copiloto.agents.render import pct
from copiloto.retrieval.lexical import normalize
from copiloto.tools.contracts import QueryOperationsInput
from copiloto.tools.query_operations import query_operations

_ARG_KEYS = ("metric", "month", "compare_to", "segment", "carrier", "channel", "group_by")


def expected_number_strings(spec: dict, db_path: Path | None) -> list[str]:
    """Resolve o número esperado via consulta determinística e devolve formatos aceitos."""
    args = {k: v for k, v in spec.items() if k in _ARG_KEYS}
    out = query_operations(QueryOperationsInput(**args), db_path)
    val = out.summary.get(spec["field"])
    if val is None:
        return []
    if isinstance(val, float) and val <= 1.0 and "taxa" in spec["field"]:
        p = pct(val)
        return [p, p.replace(",", "."), f"{val:.4f}", f"{val:.3f}"]
    return [str(val), f"{val:,}".replace(",", ".")]


def check_case(case: dict, final: dict, trace, db_path: Path | None) -> dict:
    failures: list[str] = []
    answer = final.get("answer", "") or ""
    answer_n = normalize(answer)
    status = final.get("status")
    tools = set(trace.tools_used)
    cited_docs = {c["doc_id"] for c in final.get("citations", [])}
    retrieved_docs = {h.doc_id for h in final.get("policy_hits", [])}

    for t in case.get("expected_tools", []):
        if t not in tools:
            failures.append(f"ferramenta esperada não usada: {t}")
    if "expected_tools" in case and not case["expected_tools"] and tools:
        failures.append(f"ferramentas usadas sem necessidade: {sorted(tools)}")
    if case.get("expected_status") and status not in case["expected_status"]:
        failures.append(f"status {status} fora de {case['expected_status']}")
    if status in case.get("forbidden_status", []):
        failures.append(f"status proibido: {status}")

    numbers_ok = numbers_total = 0
    for spec in case.get("expected_numbers", []):
        numbers_total += 1
        accepted = expected_number_strings(spec, db_path)
        if any(a in answer for a in accepted):
            numbers_ok += 1
        else:
            failures.append(f"número esperado ausente ({spec['field']}): {accepted[:2]}")

    for term in case.get("expected_terms", []):
        if normalize(term) not in answer_n:
            failures.append(f"termo esperado ausente: {term}")
    for term in case.get("forbidden_terms", []):
        if normalize(term) in answer_n:
            failures.append(f"termo proibido presente: {term}")

    relevant = set(case.get("relevant_docs", []))
    recall = None
    if relevant:
        hit = relevant & retrieved_docs
        recall = len(hit) / len(relevant)
        if not hit:
            failures.append(f"nenhum doc relevante recuperado: {sorted(relevant)}")
    for d in case.get("forbidden_docs", []):
        in_text = re.search(rf"\[{re.escape(d)}#", answer) is not None
        if d in retrieved_docs or d in cited_docs or in_text:
            failures.append(f"documento proibido apareceu: {d}")

    citation_precision = None
    cited = final.get("citations", [])
    if cited:
        citation_precision = sum(1 for c in cited if c["doc_id"] in retrieved_docs) / len(cited)
    if any("citação inexistente" in lim for lim in final.get("limitations", [])):
        failures.append("LLM citou chunk inexistente (removido pela validação)")

    if case.get("expected_limitation") and not final.get("limitations"):
        failures.append("limitação esperada não declarada")
    if case.get("expected_injection_flag") and not final.get("injection_flags"):
        failures.append("injeção esperada não sinalizada")

    return {
        "failures": failures, "numbers_ok": numbers_ok, "numbers_total": numbers_total,
        "recall": recall, "citation_precision": citation_precision,
        "retrieved_docs": sorted(retrieved_docs), "cited_docs": sorted(cited_docs),
    }
