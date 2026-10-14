"""Gerador de dados sintéticos com seed fixa.

Padrão artificial introduzido de propósito: no mês de referência (2025-09) os
cancelamentos aumentam, concentrados no segmento "assinante" com a transportadora
"RapidoLog", associados a atrasos registrados em tickets. Isso serve para testar o
sistema e NÃO representa dados de uma empresa real.
"""

from __future__ import annotations

import calendar
import csv
import random
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from copiloto.config import DATA_MONTHS, PROJECT_ROOT, REFERENCE_MONTH, SEED, get_settings
from copiloto.data.db import write_connection

REGIONS = ["Sudeste", "Sul", "Nordeste", "Centro-Oeste", "Norte"]
SEGMENTS = ["varejo", "assinante", "corporativo"]
CHANNELS = ["site", "app", "marketplace"]
CATEGORIES = ["eletronicos", "casa", "moda", "livros", "esporte"]
CARRIERS = ["RapidoLog", "EntregaBR", "Correios"]
CANCEL_REASONS = [
    "atraso na entrega",
    "desistencia do cliente",
    "produto indisponivel",
    "pagamento recusado",
    "preco melhor no concorrente",
    None,  # sem informação suficiente
]
TICKET_SUBJECTS = [
    "atraso na entrega",
    "pedido de cancelamento",
    "reembolso",
    "produto com defeito",
    "duvida sobre prazo",
    "troca",
]

BASE_CANCEL_RATE = 0.06
SPIKE_CANCEL_RATE = 0.22  # assinante + RapidoLog no mês de referência
TARGET_SEGMENT = "assinante"
TARGET_CARRIER = "RapidoLog"


@dataclass
class Customer:
    customer_id: str
    region: str
    segment: str


@dataclass
class Order:
    order_id: str
    customer_id: str
    created_at: str
    status: str
    channel: str
    category: str
    amount: float
    carrier: str
    promised_days: int
    delivered_days: int | None
    cancel_reason: str | None
    cancelled_at: str | None


@dataclass
class Ticket:
    ticket_id: str
    order_id: str | None
    created_at: str
    subject: str
    status: str
    description: str


def _month_days(month: str) -> list[date]:
    y, m = map(int, month.split("-"))
    n = calendar.monthrange(y, m)[1]
    return [date(y, m, d) for d in range(1, n + 1)]


def _make_ticket(rng, seq: int, order: Order) -> Ticket:
    late = order.delivered_days is not None and order.delivered_days > order.promised_days
    if order.cancel_reason == "atraso na entrega" or late:
        subject = "atraso na entrega"
        desc = (
            f"Cliente relata que o pedido {order.order_id} ultrapassou o prazo prometido de "
            f"{order.promised_days} dias com a transportadora {order.carrier}."
        )
    elif order.status == "cancelado":
        subject = "pedido de cancelamento"
        desc = f"Cliente solicita cancelamento do pedido {order.order_id}."
    else:
        subject = rng.choice(TICKET_SUBJECTS)
        desc = f"Contato sobre o pedido {order.order_id}: {subject}."
    created = date.fromisoformat(order.created_at) + timedelta(days=rng.randint(0, 8))
    return Ticket(
        ticket_id=f"T{seq:06d}",
        order_id=order.order_id,
        created_at=created.isoformat(),
        subject=subject,
        status=rng.choices(["aberto", "resolvido", "escalado"], weights=[30, 60, 10])[0],
        description=desc,
    )



def generate(seed: int = SEED) -> tuple[list[Customer], list[Order], list[Ticket]]:
    rng = random.Random(seed)

    customers = [
        Customer(
            customer_id=f"C{idx:05d}",
            region=rng.choices(REGIONS, weights=[45, 20, 20, 10, 5])[0],
            segment=rng.choices(SEGMENTS, weights=[60, 30, 10])[0],
        )
        for idx in range(1, 801)
    ]

    orders: list[Order] = []
    tickets: list[Ticket] = []
    order_seq = 0
    ticket_seq = 0

    for month in DATA_MONTHS:
        days = _month_days(month)
        n_orders = rng.randint(1150, 1250)
        is_ref = month == REFERENCE_MONTH

        for _ in range(n_orders):
            order_seq += 1
            cust = rng.choice(customers)
            created = rng.choice(days)
            carrier = rng.choices(CARRIERS, weights=[40, 35, 25])[0]
            promised = rng.choice([3, 5, 7])

            in_target = is_ref and cust.segment == TARGET_SEGMENT and carrier == TARGET_CARRIER
            cancelled = rng.random() < (SPIKE_CANCEL_RATE if in_target else BASE_CANCEL_RATE)

            delivered_days: int | None = None
            cancel_reason: str | None = None
            cancelled_at: str | None = None

            if cancelled:
                status = "cancelado"
                if in_target:
                    cancel_reason = rng.choices(
                        ["atraso na entrega", "desistencia do cliente", None], weights=[75, 15, 10]
                    )[0]
                else:
                    cancel_reason = rng.choices(CANCEL_REASONS, weights=[20, 30, 15, 15, 10, 10])[0]
                cancelled_at = (created + timedelta(days=rng.randint(1, 10))).isoformat()
            else:
                roll = rng.random()
                if roll < 0.85:
                    status = "entregue"
                    delay_bias = 4 if in_target else 0
                    delivered_days = max(1, promised + rng.randint(-2, 2) + delay_bias)
                elif roll < 0.95:
                    status = "em_transito"
                else:
                    status = "processando"

            order = Order(
                order_id=f"P{order_seq:06d}",
                customer_id=cust.customer_id,
                created_at=created.isoformat(),
                status=status,
                channel=rng.choices(CHANNELS, weights=[50, 35, 15])[0],
                category=rng.choice(CATEGORIES),
                amount=round(rng.lognormvariate(5.0, 0.6), 2),
                carrier=carrier,
                promised_days=promised,
                delivered_days=delivered_days,
                cancel_reason=cancel_reason,
                cancelled_at=cancelled_at,
            )
            orders.append(order)

            ticket_prob = 0.08
            if cancel_reason == "atraso na entrega":
                ticket_prob = 0.8
            elif delivered_days is not None and delivered_days > promised:
                ticket_prob = 0.35
            if rng.random() < ticket_prob:
                ticket_seq += 1
                tickets.append(_make_ticket(rng, ticket_seq, order))

    # Tickets sem pedido associado (informação insuficiente, de propósito)
    for _ in range(25):
        ticket_seq += 1
        month = rng.choice(DATA_MONTHS)
        tickets.append(
            Ticket(
                ticket_id=f"T{ticket_seq:06d}",
                order_id=None,
                created_at=rng.choice(_month_days(month)).isoformat(),
                subject="duvida geral",
                status="resolvido",
                description="Contato sem pedido identificado.",
            )
        )

    orders.sort(key=lambda o: (o.created_at, o.order_id))
    tickets.sort(key=lambda t: (t.created_at, t.ticket_id))
    return customers, orders, tickets


def write_csvs(customers, orders, tickets, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("customers", customers), ("orders", orders), ("tickets", tickets)):
        with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
            w.writeheader()
            for r in rows:
                w.writerow(asdict(r))


def load_db(customers, orders, tickets, db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    with write_connection(db_path) as conn:
        conn.executemany(
            "INSERT INTO customers VALUES (:customer_id, :region, :segment)",
            [asdict(c) for c in customers],
        )
        conn.executemany(
            """INSERT INTO orders VALUES (:order_id, :customer_id, :created_at, :status, :channel,
               :category, :amount, :carrier, :promised_days, :delivered_days, :cancel_reason,
               :cancelled_at)""",
            [asdict(o) for o in orders],
        )
        conn.executemany(
            """INSERT INTO tickets VALUES (:ticket_id, :order_id, :created_at, :subject, :status,
               :description)""",
            [asdict(t) for t in tickets],
        )


def main() -> None:
    settings = get_settings()
    customers, orders, tickets = generate()
    out_dir = PROJECT_ROOT / "data" / "synthetic"
    write_csvs(customers, orders, tickets, out_dir)
    load_db(customers, orders, tickets, settings.db_file)
    cancelled = sum(1 for o in orders if o.status == "cancelado")
    print(
        f"[sintético] seed={SEED} clientes={len(customers)} pedidos={len(orders)} "
        f"cancelados={cancelled} tickets={len(tickets)}"
    )
    print(f"[sintético] banco: {settings.db_file}")
    print(f"[sintético] CSVs: {out_dir}")


if __name__ == "__main__":
    main()
