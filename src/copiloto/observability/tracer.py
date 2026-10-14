"""Rastreio por execução: run_id, etapas com duração, ferramentas, tokens e erros.

Logs JSON locais com minimização: não gravamos contexto integral nem segredos.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|senha|password)\s*[:=]\s*\S+")


def redact(text: str, max_len: int = 300) -> str:
    text = _SECRET_RE.sub(r"\1=[REDACTED]", text)
    return text if len(text) <= max_len else text[:max_len] + f"...[+{len(text) - max_len}]"


@dataclass
class StepRecord:
    name: str
    duration_ms: int
    ok: bool = True
    error: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class RunTrace:
    run_id: str
    user_id: str
    role: str
    mode: str
    model: str | None
    index_version: str | None
    prompt_version: str
    started_at: str
    steps: list[StepRecord] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    tool_calls: int = 0
    retries: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tokens_reported_by_provider: bool = False
    tokens_estimated: int | None = None
    final_state: str = "received"
    error: str | None = None
    total_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class Tracer:
    def __init__(self, user_id: str, role: str, mode: str, model: str | None,
                 index_version: str | None, prompt_version: str, log_dir: Path | None = None):
        self.trace = RunTrace(
            run_id=uuid.uuid4().hex[:12], user_id=user_id, role=role, mode=mode, model=model,
            index_version=index_version, prompt_version=prompt_version,
            started_at=datetime.now(UTC).isoformat(),
        )
        self._t0 = time.perf_counter()
        self.log_dir = log_dir

    @contextmanager
    def step(self, name: str, **meta):
        t = time.perf_counter()
        rec = StepRecord(name=name, duration_ms=0, meta=meta)
        try:
            yield rec
        except Exception as e:
            rec.ok = False
            rec.error = redact(f"{type(e).__name__}: {e}")
            raise
        finally:
            rec.duration_ms = int((time.perf_counter() - t) * 1000)
            self.trace.steps.append(rec)

    def tool_used(self, name: str) -> None:
        self.trace.tools_used.append(name)
        self.trace.tool_calls += 1

    def add_usage(self, prompt: int | None, completion: int | None, reported: bool,
                  estimated: int | None = None) -> None:
        t = self.trace
        if reported and prompt is not None:
            t.prompt_tokens = (t.prompt_tokens or 0) + prompt
            t.completion_tokens = (t.completion_tokens or 0) + (completion or 0)
            t.tokens_reported_by_provider = True
        if estimated is not None:
            t.tokens_estimated = (t.tokens_estimated or 0) + estimated

    def finish(self, state: str, error: str | None = None) -> RunTrace:
        self.trace.final_state = state
        self.trace.error = redact(error) if error else None
        self.trace.total_ms = int((time.perf_counter() - self._t0) * 1000)
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(UTC).strftime("%Y%m%d")
            with (self.log_dir / f"runs-{day}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(self.trace.to_dict(), ensure_ascii=False) + "\n")
        return self.trace
