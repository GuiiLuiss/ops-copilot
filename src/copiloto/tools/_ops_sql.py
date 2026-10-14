"""SQL fixo e helpers de `query_operations`. Nenhuma string do usuário entra no SQL."""

from __future__ import annotations

import sqlite3

from copiloto.tools.contracts import Dimension, QueryOperationsInput

CANCEL_RATE_DEF = (
    "taxa de cancelamento = pedidos com status 'cancelado' / pedidos criados no mês "
    "(coorte de criação)"
)
MIN_ROWS_FOR_RATE = 20  # abaixo disso a taxa é informada mas marcada como pouco confiável

# Dimensão permitida -> expressão SQL (lista fechada; nunca interpolamos entrada do usuário)
DIM_SQL: dict[Dimension, str] = {
    "segment": "cu.segment",
    "carrier": "o.carrier",
    "channel": "o.channel",
    "category": "o.category",
    "region": "cu.region",
    "cancel_reason": "COALESCE(o.cancel_reason, 'sem motivo registrado')",
}

BASE_FROM = "FROM orders o JOIN customers cu ON cu.customer_id = o.customer_id"


def build_filters(inp: QueryOperationsInput, month: str | None = None) -> tuple[str, dict]:
    clauses = ["substr(o.created_at, 1, 7) = :month"]
    params: dict = {"month": month or inp.month}
    if inp.segment:
        clauses.append("cu.segment = :segment")
        params["segment"] = inp.segment
    if inp.carrier:
        clauses.append("o.carrier = :carrier")
        params["carrier"] = inp.carrier
    if inp.channel:
        clauses.append("o.channel = :channel")
        params["channel"] = inp.channel
    return " AND ".join(clauses), params


def active_filters(inp: QueryOperationsInput) -> dict[str, str]:
    return {k: getattr(inp, k) for k in ("segment", "carrier", "channel", "group_by")
            if getattr(inp, k)}


def rate_rows(conn: sqlite3.Connection, inp: QueryOperationsInput, month: str) -> list[dict]:
    """Pedidos e cancelados (opcionalmente agrupados) para um mês."""
    where, params = build_filters(inp, month)
    dim = DIM_SQL.get(inp.group_by) if inp.group_by else None
    select_dim = f"{dim} AS grupo," if dim else ""
    group = f"GROUP BY {dim}" if dim else ""
    sql = f"""
        SELECT {select_dim} COUNT(*) AS pedidos,
               COALESCE(SUM(o.status = 'cancelado'), 0) AS cancelados
        {BASE_FROM}
        WHERE {where}
        {group}
        ORDER BY cancelados DESC, pedidos DESC
        LIMIT :limit
    """
    params["limit"] = inp.limit
    rows = []
    for r in conn.execute(sql, params):
        d = dict(r)
        d["taxa_cancelamento"] = round(d["cancelados"] / d["pedidos"], 4) if d["pedidos"] else 0.0
        d["amostra_pequena"] = d["pedidos"] < MIN_ROWS_FOR_RATE
        rows.append(d)
    return rows
