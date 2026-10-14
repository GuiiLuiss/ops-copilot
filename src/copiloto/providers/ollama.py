"""Provedor Ollama (local) via API HTTP /api/chat."""

from __future__ import annotations

import time

import httpx

from copiloto.providers.base import LLMProvider, LLMResponse, LLMUsage, ProviderError


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def model_id(self) -> str:
        return f"ollama/{self.model}"

    def is_available(self) -> tuple[bool, str]:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3)
            r.raise_for_status()
            names = {m.get("name") for m in r.json().get("models", [])}
            if self.model not in names:
                return False, f"modelo {self.model!r} não encontrado; disponíveis: {sorted(names)}"
            return True, "ok"
        except Exception as e:  # noqa: BLE001
            return False, f"Ollama indisponível em {self.base_url}: {type(e).__name__}"

    def generate(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.1, timeout_s: int = 120) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": 8192},
            "think": False,
        }
        if json_mode:
            payload["format"] = "json"
        t0 = time.perf_counter()
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout_s)
            r.raise_for_status()
        except httpx.TimeoutException as e:
            raise ProviderError(f"timeout de {timeout_s}s no Ollama") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"erro HTTP no Ollama: {e}") from e
        data = r.json()
        text = (data.get("message") or {}).get("content", "")
        usage = LLMUsage(
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            reported_by_provider=True,
        )
        return LLMResponse(
            text=text, model=self.model_id(), usage=usage,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            raw={k: data.get(k) for k in ("total_duration", "eval_duration", "done_reason")},
        )
