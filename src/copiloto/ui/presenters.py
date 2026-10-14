"""Apresentação legível para a interface: rótulos, formatação pt-BR e indicadores.

Nenhum cálculo novo acontece aqui: os números vêm prontos das ferramentas. Este módulo só
escolhe o que mostrar e como rotular.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from copiloto.tools.contracts import QueryOperationsOutput

TZ = ZoneInfo("America/Sao_Paulo")

_MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
           "setembro", "outubro", "novembro", "dezembro"]

ANALYSIS_STATE = {
    "answer_ready": "Análise concluída",
    "awaiting_approval": "Análise concluída",
    "insufficient": "Sem dados suficientes",
    "failed": "A análise não pôde ser concluída",
}

PROPOSAL_STATE = {
    "awaiting_approval": "Aguardando aprovação",
    "approved": "Aprovada, tarefa ainda não criada",
    "rejected": "Rejeitada",
    "executed": "Tarefa criada",
    "expired": "Expirada",
}

METRIC_LABEL = {
    "period_comparison": "Comparação mensal de cancelamentos",
    "cancellation_rate": "Taxa de cancelamento",
    "cancellation_breakdown": "Motivos de cancelamento",
    "delivery_performance": "Desempenho de entrega",
    "ticket_volume": "Chamados de atendimento",
    "order_volume": "Volume de pedidos",
}

DIMENSION_LABEL = {"segment": "segmento", "carrier": "transportadora", "channel": "canal",
                   "category": "categoria", "region": "região", "cancel_reason": "motivo"}

RETRIEVAL_LABEL = {"lexical": "Por palavras-chave", "vector": "Por significado",
                   "hybrid": "Combinada"}

ROLE_LABEL = {"analista": "Analista de operações", "gestor": "Gestor de operações"}
OWNER_LABEL = {"atendimento": "Atendimento", "logistica": "Logística", "operacoes": "Operações"}
PRIORITY_LABEL = {"baixa": "Baixa", "media": "Média", "alta": "Alta"}

_COLUMN_LABEL = {
    "grupo": "Grupo", "taxa_atual": "Taxa atual", "taxa_anterior": "Taxa anterior",
    "variacao_pp": "Variação (p.p.)", "pedidos_atual": "Pedidos (atual)",
    "pedidos_anterior": "Pedidos (anterior)", "cancelados_atual": "Cancelados (atual)",
    "cancelados_anterior": "Cancelados (anterior)", "pedidos": "Pedidos",
    "cancelados": "Cancelados", "taxa_cancelamento": "Taxa de cancelamento",
    "participacao": "Participação", "taxa_no_prazo": "No prazo",
    "no_prazo": "Entregas no prazo", "entregues": "Entregues",
    "atraso_medio_dias": "Atraso médio (dias)", "assunto": "Assunto",
    "chamados": "Chamados", "sem_pedido": "Sem pedido", "amostra_pequena": "Amostra pequena",
}
_PCT_COLUMNS = {"taxa_atual", "taxa_anterior", "taxa_cancelamento", "participacao",
                "taxa_no_prazo"}


def month_label(ym: str) -> str:
    """'2025-09' -> 'setembro de 2025'."""
    try:
        y, m = ym.split("-")
        return f"{_MONTHS[int(m) - 1]} de {y}"
    except (ValueError, IndexError):
        return ym


def month_range_label(months: list[str]) -> str:
    if not months:
        return ""
    if len(months) == 1:
        return month_label(months[0])
    a, b = months[0], months[-1]
    if a[:4] == b[:4]:
        return f"{_MONTHS[int(a[5:]) - 1]} a {month_label(b)}"
    return f"{month_label(a)} a {month_label(b)}"


def pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "sem dado"
    return f"{x * 100:.{digits}f}%".replace(".", ",")


def pp(x: float | None) -> str:
    """Variação em pontos percentuais, com sinal."""
    if x is None:
        return "sem dado"
    return f"{x:+.2f} p.p.".replace(".", ",")


def num(x: int | float | None) -> str:
    if x is None:
        return "sem dado"
    if isinstance(x, float) and not x.is_integer():
        return f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(x):,}".replace(",", ".")


def local_datetime(iso: str | None) -> str:
    """ISO em UTC -> 'dd/mm/aaaa às HH:MM' no horário de Brasília."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ).strftime("%d/%m/%Y às %H:%M")


def seconds(ms: int | None) -> str:
    if ms is None:
        return ""
    return f"{ms / 1000:.1f} s".replace(".", ",") if ms >= 1000 else f"{ms} ms"



def data_label(d: QueryOperationsOutput) -> str:
    """Rótulo legível de um resultado de ferramenta."""
    label = METRIC_LABEL.get(d.metric, d.metric)
    period = month_label(d.month)
    if d.compare_to:
        period += f" em relação a {month_label(d.compare_to)}"
    parts = [f"{label}, {period}"]
    gb = d.filters.get("group_by")
    if gb:
        parts.append(f"por {DIMENSION_LABEL.get(gb, gb)}")
    for k in ("segment", "carrier", "channel"):
        if d.filters.get(k):
            parts.append(f"{DIMENSION_LABEL.get(k, k)} {d.filters[k]}")
    return ", ".join(parts)


def evidence_label(ref: str, citations: list[dict]) -> str:
    """'metric:period_comparison' ou 'POL-001#s03' -> texto legível."""
    if ref.startswith("metric:"):
        return METRIC_LABEL.get(ref[7:], ref[7:])
    for c in citations:
        if c.get("chunk_id") == ref:
            return f"{c['title']}: {c['section']}"
    return f"Referência {ref} não encontrada entre as fontes consultadas"


def indicators(data: list[QueryOperationsOutput]) -> list[dict]:
    """Até quatro indicadores, só com valores vindos das ferramentas."""
    out: list[dict] = []
    comp = next((d for d in data if d.metric == "period_comparison"), None)
    rate = next((d for d in data if d.metric == "cancellation_rate"), None)
    brk = next((d for d in data if d.metric == "cancellation_breakdown"), None)
    tickets = next((d for d in data if d.metric == "ticket_volume"), None)
    if comp and comp.summary:
        s = comp.summary
        out.append({"label": f"Taxa de cancelamento em {month_label(comp.month)}",
                    "value": pct(s.get("taxa_atual")),
                    "help": f"{num(s.get('cancelados_atual'))} cancelados em "
                            f"{num(s.get('pedidos_atual'))} pedidos criados no mês"})
        out.append({"label": f"Variação sobre {month_label(comp.compare_to or '')}",
                    "value": pp(s.get("variacao_pp")),
                    "help": f"Mês anterior: {pct(s.get('taxa_anterior'))}. Diferença em pontos "
                            "percentuais (p.p.), não em percentual relativo."})
    elif rate and rate.summary:
        s = rate.summary
        out.append({"label": f"Taxa de cancelamento em {month_label(rate.month)}",
                    "value": pct(s.get("taxa_cancelamento")),
                    "help": f"{num(s.get('cancelados'))} cancelados em "
                            f"{num(s.get('pedidos'))} pedidos criados no mês"})
    if brk and brk.rows:
        top = brk.rows[0]
        out.append({"label": "Principal motivo registrado",
                    "value": str(top.get("grupo", "")),
                    "help": f"{num(top.get('cancelados'))} pedidos cancelados, "
                            f"{pct(top.get('participacao'))} dos cancelamentos do mês"})
    if tickets and tickets.summary and len(out) < 4:
        out.append({"label": f"Chamados em {month_label(tickets.month)}",
                    "value": num(tickets.summary.get("chamados")),
                    "help": "Chamados de atendimento abertos no mês, de qualquer assunto. "
                            "Não é o mesmo que pedidos cancelados."})
    return out[:4]


def findings(data: list[QueryOperationsOutput]) -> list[str]:
    """Até três achados em frases curtas, direto das linhas das ferramentas."""
    out: list[str] = []
    for d in data:
        if d.metric == "period_comparison" and d.filters.get("group_by") and d.rows:
            dim = DIMENSION_LABEL.get(d.filters["group_by"], d.filters["group_by"])
            top = max(d.rows, key=lambda r: r.get("variacao_pp", 0))
            small = " (amostra pequena)" if top.get("amostra_pequena") else ""
            out.append(f"Por {dim}, a maior alta foi em **{top['grupo']}**: "
                       f"{pct(top.get('taxa_anterior'))} para {pct(top.get('taxa_atual'))} "
                       f"({pp(top.get('variacao_pp'))}){small}.")
        elif d.metric == "delivery_performance" and d.rows:
            worst = min(d.rows, key=lambda r: r.get("taxa_no_prazo", 1))
            out.append(f"Entrega no prazo mais baixa: **{worst.get('grupo', 'total')}**, "
                       f"{pct(worst.get('taxa_no_prazo'))} ({num(worst.get('no_prazo'))} de "
                       f"{num(worst.get('entregues'))} entregas).")
        elif d.metric == "ticket_volume" and d.rows:
            top = d.rows[0]
            out.append(f"Assunto mais frequente nos chamados: **{top['assunto']}**, "
                       f"{num(top['chamados'])} de {num(d.summary.get('chamados'))}.")
        if len(out) == 3:
            break
    return out


def table_rows(d: QueryOperationsOutput) -> list[dict]:
    """Linhas da ferramenta com cabeçalhos e números em pt-BR."""
    rows = []
    for r in d.rows:
        row = {}
        for k, v in r.items():
            key = _COLUMN_LABEL.get(k, k)
            if k in _PCT_COLUMNS:
                row[key] = pct(v)
            elif k == "variacao_pp":
                row[key] = pp(v)
            elif k == "amostra_pequena":
                row[key] = "sim" if v else "não"
            elif isinstance(v, (int, float)):
                row[key] = num(v)
            else:
                row[key] = v
        rows.append(row)
    return rows
