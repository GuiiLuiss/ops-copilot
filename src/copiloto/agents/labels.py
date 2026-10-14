"""Rótulos legíveis para identificadores internos. Compartilhado por agente e interface."""

from __future__ import annotations

import re

METRIC_LABEL = {
    "period_comparison": "comparação mensal de cancelamentos",
    "cancellation_rate": "taxa de cancelamento",
    "cancellation_breakdown": "motivos de cancelamento",
    "delivery_performance": "desempenho de entrega",
    "ticket_volume": "chamados de atendimento",
    "order_volume": "volume de pedidos",
}

# Identificadores técnicos que o modelo às vezes deixa escapar em texto corrido:
# metric:xxx, xxx#sNN, POL-001#s03, nomes de métricas soltos.
_METRIC_NAMES = "|".join(METRIC_LABEL)
_ID = (rf"(?:metric:)?(?P<id>(?:[A-Z]+-\d+[A-Za-z0-9-]*#[A-Za-z0-9]+)|(?:{_METRIC_NAMES})"
       rf"(?:#s\d+)?)")
# Entre parênteses ou colchetes, possivelmente com um rótulo antes ("(evidência X)",
# "(ver X)", "[X]"): vira "(nome legível)".
PAREN_REF_RE = re.compile(rf"\s*[\(\[]\s*(?:[^()\[\]]{{0,25}}?\s)?{_ID}\s*[\)\]]")
# Solto no meio da frase: é ruído do modelo, remove.
BARE_REF_RE = re.compile(rf"\s*\b{_ID}\b")


def humanize_refs(text: str, citations_by_id: dict[str, str]) -> str:
    """Remove identificadores técnicos de um texto para pessoas.

    Entre parênteses ou colchetes, o ID vira o nome legível entre parênteses. Solto na frase,
    é removido. `citations_by_id` mapeia chunk_id -> "Título do documento, seção"; IDs de
    chunk fora do mapa viram "política não consultada", para não exibir referência inválida.
    """
    def label(ref: str) -> str:
        base = ref.split("#")[0]
        if base in METRIC_LABEL:
            return METRIC_LABEL[base]
        return citations_by_id.get(ref, "política não consultada")

    out = PAREN_REF_RE.sub(lambda m: f" ({label(m.group('id'))})", text)
    out = BARE_REF_RE.sub("", out)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip()
