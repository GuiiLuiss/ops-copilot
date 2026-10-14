"""Identificação de intenção e seleção de ferramentas (determinística, por regras).

Escolha de projeto: o plano de ferramentas é gerado por regras, não pelo LLM.
Isso mantém a lista de ferramentas fechada, torna o modo sem LLM útil e deixa o
LLM responsável só por redigir a resposta a partir das evidências.
"""

from __future__ import annotations

import re

from copiloto.agents.state import ToolPlan
from copiloto.config import DATA_MONTHS, REFERENCE_MONTH
from copiloto.retrieval.lexical import normalize

_MONTH_NAMES = {
    "janeiro": "01", "fevereiro": "02", "marco": "03", "abril": "04", "maio": "05",
    "junho": "06", "julho": "07", "agosto": "08", "setembro": "09", "outubro": "10",
    "novembro": "11", "dezembro": "12",
}
_SEGMENTS = ["varejo", "assinante", "corporativo"]
_CARRIERS = {"rapidolog": "RapidoLog", "entregabr": "EntregaBR", "correios": "Correios"}

INJECTION_PATTERNS = [
    r"ignore (todas )?(as )?instru", r"voce agora (e|tem)", r"system prompt", r"<system>",
    r"aprove automaticamente", r"sem (pedir )?confirmac", r"run_sql", r"delete from",
    r"drop table", r"https?://", r"revele|mostre (o|as) (prompt|instruc)",
]


def detect_injection(text: str) -> list[str]:
    n = normalize(text)
    return [p for p in INJECTION_PATTERNS if re.search(p, n)]


def previous_month(month: str) -> str | None:
    if month in DATA_MONTHS:
        i = DATA_MONTHS.index(month)
        return DATA_MONTHS[i - 1] if i > 0 else None
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _extract_month(q: str, default: str) -> tuple[str, bool]:
    """Retorna (mês YYYY-MM, explícito?). Usa o PRIMEIRO mês mencionado na frase."""
    m = re.search(r"(20\d{2})-(0[1-9]|1[0-2])", q)
    if m:
        return m.group(0), True
    found = [(mm.start(), num) for name, num in _MONTH_NAMES.items()
             for mm in re.finditer(rf"\b{name}\b", q)]
    if found:
        num = min(found)[1]
        y = re.search(r"20\d{2}", q)
        return f"{y.group(0) if y else default[:4]}-{num}", True
    return default, False


def plan(question: str, reference_month: str = REFERENCE_MONTH) -> tuple[str, list[ToolPlan]]:
    """Retorna (intenção, lista de chamadas de ferramentas permitidas)."""
    q = normalize(question)
    month, month_explicit = _extract_month(q, reference_month)
    prev = previous_month(month)
    month_has_data = month in DATA_MONTHS
    segment = next((s for s in _SEGMENTS if s in q), None)
    carrier = next((v for k, v in _CARRIERS.items() if k in q), None)
    filters = {k: v for k, v in (("segment", segment), ("carrier", carrier)) if v}

    wants_data = bool(re.search(
        r"cancelament|pedido|volume|taxa|entrega|atraso|chamado|ticket|transportadora|"
        r"segmento|canal|comparar|aumentou|caiu|quantos|quanto|numero|percentual|desempenho", q))
    # Pergunta explicitamente sobre o texto de uma política ("o que a política diz sobre...",
    # "qual a regra de..."): só busca documentos, sem consultar dados.
    policy_only = bool(re.search(
        r"^(o que|qual|quais|como) (a |as |e a |e o )?(politica|regra|norma|procedimento)", q))
    wants_policy = bool(re.search(
        r"politica|regra|reembolso|sla|prazo|procedimento|escalon|pode|permitido|vigente|"
        r"contrato|multa|penalidade|troca|devolucao|acao|acoes|o que fazer|como", q))
    comparison = bool(re.search(r"aumentou|caiu|comparad|em relacao|versus|vs|mes anterior|"
                                r"por que|porque|subiu|variacao|tendencia|mudou|mudaram|"
                                r"evolu|cresceu|diminuiu", q))
    is_cancel = "cancel" in q
    is_delivery = bool(re.search(r"entrega|atraso|prazo|transportadora|sla", q))
    is_ticket = bool(re.search(r"chamado|ticket|atendimento", q))
    # Pergunta histórica sobre regra ("qual era a regra em junho"): política com data de
    # referência, sem consulta de dados para um mês fora do conjunto.
    historical_policy = bool(re.search(r"\b(era|eram|vigorava|valia|antiga|anterior)\b", q)) \
        and wants_policy and month_explicit and not month_has_data
    if historical_policy:
        return "politicas", [{"tool": "search_policies", "args": {
            "query": question, "reference_date": f"{month}-15"}}]

    if policy_only:
        return "politicas", [{"tool": "search_policies", "args": {"query": question}}]

    steps: list[ToolPlan] = []
    if wants_data:
        if comparison and prev:
            steps.append({"tool": "query_operations", "args": {
                "metric": "period_comparison", "month": month, "compare_to": prev,
                "group_by": "segment", **filters}})
            steps.append({"tool": "query_operations", "args": {
                "metric": "period_comparison", "month": month, "compare_to": prev,
                "group_by": "carrier", **filters}})
        elif is_cancel:
            steps.append({"tool": "query_operations", "args": {
                "metric": "cancellation_rate", "month": month, **filters}})
        if is_cancel:
            steps.append({"tool": "query_operations", "args": {
                "metric": "cancellation_breakdown", "month": month, **filters}})
        if is_delivery or (is_cancel and comparison):
            steps.append({"tool": "query_operations", "args": {
                "metric": "delivery_performance", "month": month, "group_by": "carrier",
                **filters}})
        if is_ticket or (is_cancel and comparison):
            steps.append({"tool": "query_operations", "args": {
                "metric": "ticket_volume", "month": month, **filters}})
        if not steps:
            steps.append({"tool": "query_operations", "args": {
                "metric": "order_volume", "month": month, "group_by": "segment", **filters}})

    if wants_policy or (is_cancel and comparison):
        # Políticas primeiro: não podem ser cortadas pelo limite de chamadas
        steps.insert(0, {"tool": "search_policies", "args": {"query": question}})

    if not steps:
        return "fora_de_escopo", []
    intent = "dados+politicas" if (wants_data and (wants_policy or comparison)) else (
        "dados" if wants_data else "politicas")
    return intent, steps
