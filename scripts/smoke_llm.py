"""Smoke test do fluxo principal com o provedor configurado em .env/ambiente.

Uso: python scripts/smoke_llm.py [--provider ollama|gemini|none] [--out arquivo.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from copiloto.agents.graph import run_agent
from copiloto.config import get_settings
from copiloto.providers import get_provider

MAIN_Q = "Por que os cancelamentos aumentaram neste mês e quais ações podemos tomar?"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None)
    ap.add_argument("--question", default=MAIN_Q)
    ap.add_argument("--user", default="ana.analista")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    s = get_settings()
    if args.provider:
        s = s.model_copy(update={"llm_provider": args.provider})
    prov = get_provider(s)
    if prov is not None:
        ok, msg = prov.is_available()
        print(f"[provedor] {prov.model_id()} disponível={ok} ({msg})")
        if not ok:
            return 2
    final, trace = run_agent(args.question, args.user, want_proposal=True, settings=s,
                             provider=prov)
    result = {
        "status": final.get("status"), "answer": final.get("answer"),
        "citations": [c["chunk_id"] for c in final.get("citations", [])],
        "proposal": final["proposal"].model_dump() if final.get("proposal") else None,
        "limitations": final.get("limitations"), "trace": trace.to_dict(),
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] resultado em {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
