"""Testes da ferramenta determinística `query_operations`."""

import sqlite3

import pytest
from pydantic import ValidationError

from copiloto.config import DATA_MONTHS, REFERENCE_MONTH
from copiloto.tools.contracts import QueryOperationsInput
from copiloto.tools.query_operations import query_operations

PREV = DATA_MONTHS[1]


def _raw_rate(db, month, extra_where="", params=()):
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT COUNT(*), SUM(status='cancelado') FROM orders o "
        "JOIN customers cu USING(customer_id) WHERE substr(o.created_at,1,7)=? " + extra_where,
        (month, *params),
    ).fetchone()
    conn.close()
    return row[0], row[1], round(row[1] / row[0], 4)


def test_cancellation_rate_matches_raw_sql(synthetic_db):
    out = query_operations(QueryOperationsInput(metric="cancellation_rate", month=REFERENCE_MONTH),
                           synthetic_db)
    pedidos, cancelados, taxa = _raw_rate(synthetic_db, REFERENCE_MONTH)
    assert out.summary == {"pedidos": pedidos, "cancelados": cancelados, "taxa_cancelamento": taxa}
    assert out.data_sufficient
    assert "coorte de criação" in out.definition


def test_period_comparison_shows_increase(synthetic_db):
    out = query_operations(
        QueryOperationsInput(metric="period_comparison", month=REFERENCE_MONTH, compare_to=PREV),
        synthetic_db,
    )
    assert out.summary["variacao_pp"] > 0
    assert out.summary["taxa_atual"] > out.summary["taxa_anterior"]


def test_period_comparison_by_segment_points_to_assinante(synthetic_db):
    out = query_operations(
        QueryOperationsInput(metric="period_comparison", month=REFERENCE_MONTH,
                             compare_to=PREV, group_by="segment"),
        synthetic_db,
    )
    top = max(out.rows, key=lambda r: r["variacao_pp"])
    assert top["grupo"] == "assinante"


def test_filter_segment_and_group_by_carrier(synthetic_db):
    out = query_operations(
        QueryOperationsInput(metric="cancellation_rate", month=REFERENCE_MONTH,
                             segment="assinante", group_by="carrier"),
        synthetic_db,
    )
    by = {r["grupo"]: r for r in out.rows}
    assert by["RapidoLog"]["taxa_cancelamento"] > by["EntregaBR"]["taxa_cancelamento"]
    pedidos, cancelados, _ = _raw_rate(synthetic_db, REFERENCE_MONTH,
                                       "AND cu.segment=? AND o.carrier=?",
                                       ("assinante", "RapidoLog"))
    assert by["RapidoLog"]["pedidos"] == pedidos
    assert by["RapidoLog"]["cancelados"] == cancelados


def test_breakdown_reason_includes_no_reason_bucket(synthetic_db):
    out = query_operations(
        QueryOperationsInput(metric="cancellation_breakdown", month=REFERENCE_MONTH), synthetic_db
    )
    groups = {r["grupo"] for r in out.rows}
    assert "atraso na entrega" in groups
    assert "sem motivo registrado" in groups
    assert abs(sum(r["participacao"] for r in out.rows) - 1.0) < 0.01


def test_delivery_performance_target_carrier_is_worse(synthetic_db):
    out = query_operations(
        QueryOperationsInput(metric="delivery_performance", month=REFERENCE_MONTH,
                             segment="assinante", group_by="carrier"),
        synthetic_db,
    )
    by = {r["grupo"]: r for r in out.rows}
    assert by["RapidoLog"]["taxa_no_prazo"] < by["EntregaBR"]["taxa_no_prazo"]


def test_ticket_volume(synthetic_db):
    out = query_operations(QueryOperationsInput(metric="ticket_volume", month=REFERENCE_MONTH),
                           synthetic_db)
    assert out.summary["chamados"] > 0
    assert any(r["assunto"] == "atraso na entrega" for r in out.rows)


def test_insufficient_data_month(synthetic_db):
    out = query_operations(QueryOperationsInput(metric="cancellation_rate", month="2024-01"),
                           synthetic_db)
    assert not out.data_sufficient
    assert out.note is not None


def test_invalid_inputs_rejected():
    with pytest.raises(ValidationError):
        QueryOperationsInput(metric="cancellation_rate", month="2025-13")
    with pytest.raises(ValidationError):
        QueryOperationsInput(metric="cancellation_rate", month="2025-09",
                             segment="x'; DROP TABLE orders; --")
    with pytest.raises(ValidationError):
        QueryOperationsInput(metric="run_sql", month="2025-09")
    with pytest.raises(ValidationError):
        QueryOperationsInput(metric="cancellation_rate", month="2025-09", group_by="order_id")


def test_period_comparison_requires_compare_to(synthetic_db):
    with pytest.raises(ValueError):
        query_operations(QueryOperationsInput(metric="period_comparison", month=REFERENCE_MONTH),
                         synthetic_db)


def test_connection_is_read_only(synthetic_db):
    from copiloto.data.db import read_connection

    with read_connection(synthetic_db) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM orders")
