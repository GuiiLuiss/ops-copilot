"""Runner de avaliação: executa os 30 casos por variante de recuperação e gera relatório JSON.

Uso: copiloto eval --variants lexical,hybrid [--llm]
Métricas não executadas ficam como null, nunca preenchidas.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from copiloto import __version__
from copiloto.agents.graph import run_agent
from copiloto.agents.prompts import PROMPT_VERSION
from copiloto.config import PROJECT_ROOT, get_settings
from copiloto.data.generate import generate, load_db
from copiloto.evals.checks import check_case
from copiloto.evals.flows import run_flow
from copiloto.evals.metrics import summarize
from copiloto.providers import get_provider
from copiloto.retrieval.retriever import Retriever

CASES_FILE = PROJECT_ROOT / "evals" / "cases.json"
RESULTS_DIR = PROJECT_ROOT / "evals" / "results"


def run_variant(cases, variant, settings, provider, retriever, db_path) -> dict:
    results = []
    for case in cases:
        t0 = time.perf_counter()
        final, trace = run_agent(
            case["question"], case["user"], want_proposal=case.get("want_proposal", False),
            settings=settings, provider=provider, retriever=retriever, db_path=db_path,
            retrieval_mode=variant)
        chk = check_case(case, final, trace, db_path)
        flow_fail = run_flow(case, final, trace, db_path) if (
            case.get("flow") or case.get("want_proposal")) else []
        failures = chk["failures"] + flow_fail
        llm_ms = sum(s.duration_ms for s in trace.steps if s.name.startswith("llm:"))
        results.append({
            "id": case["id"], "category": case["category"], "user": case["user"],
            "status": final.get("status"), "passed": not failures, "failures": failures,
            "numbers_ok": chk["numbers_ok"], "numbers_total": chk["numbers_total"],
            "recall": chk["recall"], "citation_precision": chk["citation_precision"],
            "retrieved_docs": chk["retrieved_docs"], "cited_docs": chk["cited_docs"],
            "tool_calls": trace.tool_calls, "total_ms": trace.total_ms,
            "llm_ms": llm_ms or None,
            "prompt_tokens": trace.prompt_tokens, "completion_tokens": trace.completion_tokens,
            "tokens_reported_by_provider": trace.tokens_reported_by_provider,
            "injection_flags": final.get("injection_flags", []),
            "wall_ms": int((time.perf_counter() - t0) * 1000),
        })
        print(f"  [{variant}] {case['id']} {'OK  ' if not failures else 'FAIL'} "
              f"{trace.total_ms}ms {'; '.join(failures)[:110]}", file=sys.stderr)
    return {"cases": results, "metrics": summarize(results)}


def main(variants: list[str], use_llm: bool = False, out: Path | None = None) -> int:
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]
    settings = get_settings()
    provider = get_provider(settings) if use_llm else None
    if use_llm and provider is None:
        print("COPILOTO_LLM_PROVIDER=none; --llm exige provedor configurado", file=sys.stderr)
        return 2
    if provider:
        ok, msg = provider.is_available()
        if not ok:
            print(f"provedor indisponível: {msg}", file=sys.stderr)
            return 2

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    db_path = RESULTS_DIR / "_eval.db"  # banco isolado: não polui a demo
    load_db(*generate(), db_path)
    retriever = Retriever(settings=settings)

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "app_version": __version__, "prompt_version": PROMPT_VERSION,
        "index_version": retriever.index_version, "cases_version": "1.0",
        "mode": "llm" if provider else "deterministico",
        "model": provider.model_id() if provider else None,
        "embedding_model": settings.embedding_model if any(
            v in ("vector", "hybrid") for v in variants) else None,
        "hardware": {"platform": platform.platform(), "python": platform.python_version(),
                     "machine": platform.machine()},
        "repetitions": 1, "cache": "sem cache de respostas",
        "variants": {},
        "notes": ["Métricas null = não medidas nesta execução.",
                  "Amostra pequena (30 casos): percentis só com n>=5; não generalizar."],
    }
    for v in variants:
        print(f"== variante {v}", file=sys.stderr)
        report["variants"][v] = run_variant(cases, v, settings, provider, retriever, db_path)
        if v in ("vector", "hybrid") and retriever.vector_error:
            report["variants"][v]["note"] = f"vetorial indisponível: {retriever.vector_error}"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out or RESULTS_DIR / f"eval-{report['mode']}-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    db_path.unlink(missing_ok=True)
    for v, data in report["variants"].items():
        m = data["metrics"]
        print(f"[{v}] {m['cases_passed']}/{m['cases_total']} casos OK | números "
              f"{m['numeric_checks']} | recall@k {m['recall_at_k_mean']} | "
              f"p50 {m['latency_ms']['p50']}ms p95 {m['latency_ms']['p95']}ms")
    print(f"relatório: {out}")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(main(args[0].split(",") if args else ["lexical"],
                          use_llm="--llm" in sys.argv))
