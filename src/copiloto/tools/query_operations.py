"""Ferramenta `query_operations`: consultas determinísticas e parametrizadas (somente leitura)."""

from __future__ import annotations

from pathlib import Path

from copiloto.data.db import read_connection
from copiloto.tools._ops_sql import (
    BASE_FROM,
    CANCEL_RATE_DEF,
    DIM_SQL,
    MIN_ROWS_FOR_RATE,
    active_filters,
    build_filters,
    rate_rows,
)
from copiloto.tools.contracts import QueryOperationsInput, QueryOperationsOutput


def _out(inp, **kw) -> QueryOperationsOutput:
    return QueryOperationsOutput(metric=inp.metric, month=inp.month, compare_to=inp.compare_to,
                                 filters=active_filters(inp), **kw)


def _order_volume(conn, inp):
    rows = rate_rows(conn, inp, inp.month)
    total = sum(r["pedidos"] for r in rows)
    return _out(inp, definition="volume = pedidos criados no mês", rows=rows,
                summary={"pedidos": total}, data_sufficient=total > 0)


def _cancellation_rate(conn, inp):
    rows = rate_rows(conn, inp, inp.month)
    pedidos = sum(r["pedidos"] for r in rows)
    cancelados = sum(r["cancelados"] for r in rows)
    ok = pedidos >= MIN_ROWS_FOR_RATE
    return _out(
        inp, definition=CANCEL_RATE_DEF, rows=rows,
        summary={"pedidos": pedidos, "cancelados": cancelados,
                 "taxa_cancelamento": round(cancelados / pedidos, 4) if pedidos else 0.0},
        data_sufficient=ok,
        note=None if ok else f"amostra com menos de {MIN_ROWS_FOR_RATE} pedidos; taxa pouco confiável",
    )


def _cancellation_breakdown(conn, inp):
    inp = inp.model_copy(update={"group_by": inp.group_by or "cancel_reason"})
    where, params = build_filters(inp)
    dim = DIM_SQL[inp.group_by]
    sql = f"""
        SELECT {dim} AS grupo, COUNT(*) AS cancelados
        {BASE_FROM}
        WHERE {where} AND o.status = 'cancelado'
        GROUP BY {dim} ORDER BY cancelados DESC LIMIT :limit
    """
    params["limit"] = inp.limit
    rows = [dict(r) for r in conn.execute(sql, params)]
    total = sum(r["cancelados"] for r in rows)
    for r in rows:
        r["participacao"] = round(r["cancelados"] / total, 4) if total else 0.0
    return _out(inp, definition=f"distribuição dos pedidos cancelados por {inp.group_by}",
                rows=rows, summary={"cancelados": total}, data_sufficient=total > 0)


def _period_comparison(conn, inp):
    if not inp.compare_to:
        raise ValueError("period_comparison exige compare_to")
    cur = {r.get("grupo", "_total"): r for r in rate_rows(conn, inp, inp.month)}
    prev = {r.get("grupo", "_total"): r for r in rate_rows(conn, inp, inp.compare_to)}
    rows = []
    keys = sorted(set(cur) | set(prev), key=lambda k: -cur.get(k, {}).get("cancelados", 0))
    for g in keys:
        c, p = cur.get(g, {}), prev.get(g, {})
        tc, tp = c.get("taxa_cancelamento", 0.0), p.get("taxa_cancelamento", 0.0)
        rows.append({
            "grupo": g,
            "pedidos_atual": c.get("pedidos", 0), "cancelados_atual": c.get("cancelados", 0),
            "taxa_atual": tc,
            "pedidos_anterior": p.get("pedidos", 0), "cancelados_anterior": p.get("cancelados", 0),
            "taxa_anterior": tp,
            "variacao_pp": round((tc - tp) * 100, 2),
            "amostra_pequena": c.get("amostra_pequena", True) or p.get("amostra_pequena", True),
        })
    tot_c = sum(r["pedidos_atual"] for r in rows)
    can_c = sum(r["cancelados_atual"] for r in rows)
    tot_p = sum(r["pedidos_anterior"] for r in rows)
    can_p = sum(r["cancelados_anterior"] for r in rows)
    tc = round(can_c / tot_c, 4) if tot_c else 0.0
    tp = round(can_p / tot_p, 4) if tot_p else 0.0
    return _out(
        inp, definition=CANCEL_RATE_DEF + "; variação em pontos percentuais (p.p.)", rows=rows,
        summary={"taxa_atual": tc, "taxa_anterior": tp, "variacao_pp": round((tc - tp) * 100, 2),
                 "pedidos_atual": tot_c, "pedidos_anterior": tot_p,
                 "cancelados_atual": can_c, "cancelados_anterior": can_p},
        data_sufficient=tot_c >= MIN_ROWS_FOR_RATE and tot_p >= MIN_ROWS_FOR_RATE,
    )


def _delivery_performance(conn, inp):
    where, params = build_filters(inp)
    dim = DIM_SQL.get(inp.group_by) if inp.group_by else None
    select_dim = f"{dim} AS grupo," if dim else ""
    group = f"GROUP BY {dim}" if dim else ""
    sql = f"""
        SELECT {select_dim} COUNT(*) AS entregues,
               COALESCE(SUM(o.delivered_days <= o.promised_days), 0) AS no_prazo,
               ROUND(AVG(CASE WHEN o.delivered_days > o.promised_days
                              THEN o.delivered_days - o.promised_days END), 2) AS atraso_medio_dias
        {BASE_FROM}
        WHERE {where} AND o.status = 'entregue'
        {group} ORDER BY entregues DESC LIMIT :limit
    """
    params["limit"] = inp.limit
    rows = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["taxa_no_prazo"] = round(d["no_prazo"] / d["entregues"], 4) if d["entregues"] else 0.0
        rows.append(d)
    ent = sum(r["entregues"] for r in rows)
    return _out(
        inp, rows=rows, summary={"entregues": ent}, data_sufficient=ent >= MIN_ROWS_FOR_RATE,
        definition="taxa no prazo = entregues com dias <= prometido / entregues; "
                   "atraso médio só sobre entregas fora do prazo (POL-008)",
    )


def _ticket_volume(conn, inp):
    params: dict = {"month": inp.month, "limit": inp.limit}
    extra = ""
    if inp.carrier:
        extra += " AND o.carrier = :carrier"
        params["carrier"] = inp.carrier
    if inp.segment:
        extra += " AND cu.segment = :segment"
        params["segment"] = inp.segment
    sql = f"""
        SELECT t.subject AS assunto, COUNT(*) AS chamados, SUM(t.order_id IS NULL) AS sem_pedido
        FROM tickets t
        LEFT JOIN orders o ON o.order_id = t.order_id
        LEFT JOIN customers cu ON cu.customer_id = o.customer_id
        WHERE substr(t.created_at, 1, 7) = :month {extra}
        GROUP BY t.subject ORDER BY chamados DESC LIMIT :limit
    """
    rows = [dict(r) for r in conn.execute(sql, params)]
    total = sum(r["chamados"] for r in rows)
    return _out(inp, definition="chamados criados no mês por assunto", rows=rows,
                summary={"chamados": total}, data_sufficient=total > 0)


_HANDLERS = {
    "order_volume": _order_volume,
    "cancellation_rate": _cancellation_rate,
    "cancellation_breakdown": _cancellation_breakdown,
    "period_comparison": _period_comparison,
    "delivery_performance": _delivery_performance,
    "ticket_volume": _ticket_volume,
}


def query_operations(inp: QueryOperationsInput, db_path: Path | None = None) -> QueryOperationsOutput:
    """Executa uma consulta predefinida em conexão somente leitura."""
    with read_connection(db_path) as conn:
        return _HANDLERS[inp.metric](conn, inp)
