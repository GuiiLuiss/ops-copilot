"""CLI: `copiloto <comando>`."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(prog="copiloto")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate-data", help="gera dados sintéticos e banco SQLite")
    sub.add_parser("api", help="sobe a API FastAPI em http://127.0.0.1:8000")
    sub.add_parser("ui", help="abre a interface Streamlit")
    ev = sub.add_parser("eval", help="executa os casos de avaliação")
    ev.add_argument("--variants", default="lexical", help="ex.: lexical,hybrid,vector")
    ev.add_argument("--llm", action="store_true", help="usar o provedor configurado")
    args = ap.parse_args()

    if args.cmd == "generate-data":
        from copiloto.data.generate import main as gen

        gen()
    elif args.cmd == "api":
        import uvicorn

        uvicorn.run("copiloto.api.app:app", host="127.0.0.1", port=8000, reload=False)
    elif args.cmd == "ui":
        ui = Path(__file__).with_name("ui") / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(ui)])
    elif args.cmd == "eval":
        from copiloto.evals.run import main as run_eval

        return run_eval(variants=args.variants.split(","), use_llm=args.llm)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
