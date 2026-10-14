"""Montagem de contexto para o LLM, resposta determinística (sem LLM) e validação."""

from __future__ import annotations

import json
import re

from copiloto.tools.contracts import PolicyHit, QueryOperationsOutput

# Captura qualquer coisa com cara de citação, inclusive malformada (ex.: [POL-008#sXX])
CITE_RE = re.compile(r"\[([A-Z]+-[A-Za-z0-9-]+#[A-Za-z0-9]+)\]")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


_RATE_KEYS = ("taxa_cancelamento", "taxa_atual", "taxa_anterior", "taxa_no_prazo", "participacao")


def _with_pct(obj: dict) -> dict:
    """Adiciona versões já formatadas (ex.: taxa_atual_pct='12,3%') para o LLM não calcular."""
    out = dict(obj)
    for k in _RATE_KEYS:
        if k in obj and isinstance(obj[k], (int, float)):
            out[f"{k}_pct"] = pct(obj[k])
    return out


def build_context(data: list[QueryOperationsOutput], hits: list[PolicyHit]) -> str:
    """Contexto com evidências rotuladas como DADOS (conteúdo não confiável)."""
    parts = ["<evidencias_dados>"]
    for d in data:
        parts.append(json.dumps({
            "metric": d.metric, "month": d.month, "compare_to": d.compare_to,
            "filters": d.filters, "definition": d.definition, "summary": _with_pct(d.summary),
            "rows": [_with_pct(r) for r in d.rows[:8]],
            "data_sufficient": d.data_sufficient, "note": d.note,
        }, ensure_ascii=False))
    parts.append("</evidencias_dados>")
    parts.append("<evidencias_documentos>")
    for h in hits:
        parts.append(f"[{h.chunk_id}] {h.title} v{h.version} — {h.section}\n{h.text}\n")
    parts.append("</evidencias_documentos>")
    valid = ", ".join(f"[{h.chunk_id}]" for h in hits) or "(nenhum)"
    parts.append(f"<citacoes_permitidas>{valid}</citacoes_permitidas>")
    return "\n".join(parts)


def deterministic_answer(data: list[QueryOperationsOutput],
                         hits: list[PolicyHit], limitations: list[str]) -> str:
    """Resposta sem LLM: só números das ferramentas e trechos recuperados."""
    out = ["**Modo determinístico (sem LLM)** — resposta montada diretamente das ferramentas.\n"]
    if data:
        out.append("**Dados consultados**")
        for d in data:
            f = f" [{', '.join(f'{k}={v}' for k, v in d.filters.items())}]" if d.filters else ""
            if d.metric == "period_comparison":
                s = d.summary
                out.append(
                    f"- Taxa de cancelamento {d.month}: {pct(s['taxa_atual'])} "
                    f"({s['cancelados_atual']}/{s['pedidos_atual']}) vs {d.compare_to}: "
                    f"{pct(s['taxa_anterior'])} ({s['cancelados_anterior']}/{s['pedidos_anterior']}); "
                    f"variação {s['variacao_pp']:+.2f} p.p.{f}".replace(".", ",", 0)
                )
                if d.filters.get("group_by"):
                    top = sorted(d.rows, key=lambda r: -r["variacao_pp"])[:3]
                    for r in top:
                        flag = " (amostra pequena)" if r["amostra_pequena"] else ""
                        out.append(f"  - {r['grupo']}: {pct(r['taxa_atual'])} vs "
                                   f"{pct(r['taxa_anterior'])} ({r['variacao_pp']:+.2f} p.p.){flag}")
            elif d.metric == "cancellation_rate":
                s = d.summary
                out.append(f"- Taxa de cancelamento {d.month}{f}: {pct(s['taxa_cancelamento'])} "
                           f"({s['cancelados']}/{s['pedidos']})")
                for r in d.rows[:5] if d.filters.get("group_by") else []:
                    out.append(f"  - {r['grupo']}: {pct(r['taxa_cancelamento'])} "
                               f"({r['cancelados']}/{r['pedidos']})")
            elif d.metric == "cancellation_breakdown":
                out.append(f"- Motivos de cancelamento {d.month}{f} ({d.summary['cancelados']} cancelados):")
                for r in d.rows[:6]:
                    out.append(f"  - {r['grupo']}: {r['cancelados']} ({pct(r['participacao'])})")
            elif d.metric == "delivery_performance":
                out.append(f"- Desempenho de entrega {d.month}{f}:")
                for r in d.rows[:5]:
                    g = r.get("grupo", "total")
                    out.append(f"  - {g}: {pct(r['taxa_no_prazo'])} no prazo "
                               f"({r['no_prazo']}/{r['entregues']}), atraso médio "
                               f"{r['atraso_medio_dias'] or 0} dias")
            elif d.metric == "ticket_volume":
                out.append(f"- Chamados {d.month}{f}: {d.summary['chamados']}")
                for r in d.rows[:4]:
                    out.append(f"  - {r['assunto']}: {r['chamados']}")
            elif d.metric == "order_volume":
                out.append(f"- Pedidos {d.month}{f}: {d.summary['pedidos']}")
                for r in d.rows[:5] if d.filters.get("group_by") else []:
                    out.append(f"  - {r['grupo']}: {r['pedidos']}")
            if not d.data_sufficient:
                out.append(f"  - ⚠ dados insuficientes: {d.note or 'amostra pequena ou vazia'}")
    if hits:
        out.append("\n**Políticas recuperadas**")
        for h in hits:
            snippet = h.text.split("\n", 1)[-1].strip().replace("\n", " ")[:220]
            out.append(f"- [{h.chunk_id}] {h.title} v{h.version} — {h.section}: {snippet}…")
    if limitations:
        out.append("\n**Limitações**")
        out.extend(f"- {lim}" for lim in limitations)
    out.append("\n_Sem LLM, não há síntese ou hipóteses: apenas evidências brutas._")
    return "\n".join(out)


def validate_answer(answer: str, hits: list[PolicyHit],
                    data: list[QueryOperationsOutput]) -> tuple[list[str], list[str]]:
    """Retorna (citações válidas, problemas). Citações desconhecidas são problema."""
    known = {h.chunk_id for h in hits}
    cited = CITE_RE.findall(answer)
    bad = sorted({c for c in cited if c not in known})
    problems = [f"citação inexistente: {c}" for c in bad]
    valid = [c for c in dict.fromkeys(cited) if c in known]
    if hits and data and not cited:
        problems.append("resposta sem citações apesar de haver documentos recuperados")
    return valid, problems


def strip_bad_citations(answer: str, valid: set[str]) -> str:
    return CITE_RE.sub(lambda m: m.group(0) if m.group(1) in valid else "[citação removida]",
                       answer)
