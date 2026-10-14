"""Testes do gerador sintético: reprodutibilidade e padrão intencional."""

from copiloto.config import DATA_MONTHS, REFERENCE_MONTH
from copiloto.data.generate import TARGET_CARRIER, TARGET_SEGMENT, generate


def test_generate_is_deterministic():
    a = generate()
    b = generate()
    assert [o.order_id for o in a[1]] == [o.order_id for o in b[1]]
    assert [o.status for o in a[1]] == [o.status for o in b[1]]
    assert [t.ticket_id for t in a[2]] == [t.ticket_id for t in b[2]]


def test_covers_three_months_including_reference():
    _, orders, _ = generate()
    months = sorted({o.created_at[:7] for o in orders})
    assert months == DATA_MONTHS
    assert REFERENCE_MONTH in months


def test_spike_concentrated_in_target_segment_and_carrier():
    customers, orders, _ = generate()
    seg = {c.customer_id: c.segment for c in customers}

    def rate(filt):
        sub = [o for o in orders if filt(o)]
        return sum(o.status == "cancelado" for o in sub) / len(sub)

    ref_target = rate(lambda o: o.created_at.startswith(REFERENCE_MONTH)
                      and seg[o.customer_id] == TARGET_SEGMENT and o.carrier == TARGET_CARRIER)
    ref_other = rate(lambda o: o.created_at.startswith(REFERENCE_MONTH)
                     and not (seg[o.customer_id] == TARGET_SEGMENT and o.carrier == TARGET_CARRIER))
    prev_target = rate(lambda o: o.created_at.startswith(DATA_MONTHS[1])
                       and seg[o.customer_id] == TARGET_SEGMENT and o.carrier == TARGET_CARRIER)
    assert ref_target > 0.15
    assert ref_other < 0.10
    assert prev_target < 0.12


def test_has_cases_without_enough_information():
    _, orders, tickets = generate()
    assert any(o.status == "cancelado" and o.cancel_reason is None for o in orders)
    assert any(t.order_id is None for t in tickets)


def test_no_pii_fields():
    customers, _, _ = generate()
    fields = set(vars(customers[0]).keys())
    assert fields == {"customer_id", "region", "segment"}
