"""Agregação de métricas do relatório de avaliação. Métricas não medidas ficam null."""

from __future__ import annotations

import statistics


def pctl(values: list[int], p: float) -> int | None:
    if len(values) < 5:  # amostra pequena: não reportar percentis
        return None
    vs = sorted(values)
    k = max(0, min(len(vs) - 1, round(p * (len(vs) - 1))))
    return vs[k]


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def summarize(results: list[dict]) -> dict:
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"], {"total": 0, "passed": 0})
        c["total"] += 1
        c["passed"] += int(r["passed"])
    nums_total = sum(r["numbers_total"] for r in results)
    nums_ok = sum(r["numbers_ok"] for r in results)
    lat = [r["total_ms"] for r in results]
    llm_lat = [r["llm_ms"] for r in results if r["llm_ms"]]
    tok_reported = [r for r in results if r["tokens_reported_by_provider"]]

    def count_fail(pred) -> int:
        return sum(1 for r in results if any(pred(f) for f in r["failures"]))

    return {
        "cases_total": len(results),
        "cases_passed": sum(r["passed"] for r in results),
        "completion_rate": round(sum(r["status"] != "failed" for r in results) / len(results), 4),
        "numeric_accuracy": round(nums_ok / nums_total, 4) if nums_total else None,
        "numeric_checks": f"{nums_ok}/{nums_total}",
        "recall_at_k_mean": mean([r["recall"] for r in results]),
        "citation_precision_mean": mean([r["citation_precision"] for r in results]),
        "authorization_violations": count_fail(lambda f: "proibido apareceu" in f),
        "unapproved_executions": count_fail(
            lambda f: "sem aprovação" in f or "duplicada" in f or "conseguiu" in f),
        "fake_citations_detected": count_fail(lambda f: "inexistente" in f),
        "latency_ms": {"p50": pctl(lat, 0.5), "p95": pctl(lat, 0.95), "mean": mean(lat)},
        "llm_latency_ms": {"p50": pctl(llm_lat, 0.5), "p95": pctl(llm_lat, 0.95),
                           "n": len(llm_lat)},
        "tokens_provider_total": {
            "prompt": sum(r["prompt_tokens"] or 0 for r in tok_reported) or None,
            "completion": sum(r["completion_tokens"] or 0 for r in tok_reported) or None,
            "runs_reported": len(tok_reported)},
        "by_category": by_cat,
    }
