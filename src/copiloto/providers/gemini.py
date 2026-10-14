"""Provedor Gemini via REST (sem SDK adicional). Opcional; exige GEMINI_API_KEY.

A disponibilidade de cota gratuita depende das condições vigentes do provedor.
Este projeto não promete acesso gratuito permanente.
"""

from __future__ import annotations

import os
import time

import httpx

from copiloto.providers.base import LLMProvider, LLMResponse, LLMUsage, ProviderError

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def model_id(self) -> str:
        return f"gemini/{self.model}"

    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "GEMINI_API_KEY não definida"
        return True, "ok (chave presente; cota não verificada)"

    def generate(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.1, timeout_s: int = 120) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY não definida")
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature},
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = f"{_BASE}/{self.model}:generateContent"
        t0 = time.perf_counter()
        backoff = [1, 2, 4]  # retry limitado só para 429/503 (operação idempotente de leitura)
        last_err: Exception | None = None
        for attempt in range(len(backoff) + 1):
            try:
                r = httpx.post(url, json=payload, timeout=timeout_s,
                               headers={"x-goog-api-key": self.api_key})
                if r.status_code in (429, 503) and attempt < len(backoff):
                    time.sleep(backoff[attempt])
                    continue
                r.raise_for_status()
                break
            except httpx.HTTPError as e:
                last_err = e
                if attempt >= len(backoff):
                    raise ProviderError(f"erro no Gemini: {e}") from e
        else:  # pragma: no cover
            raise ProviderError(f"erro no Gemini: {last_err}")
        data = r.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ProviderError(f"resposta inesperada do Gemini: {str(data)[:200]}") from e
        um = data.get("usageMetadata", {})
        usage = LLMUsage(prompt_tokens=um.get("promptTokenCount"),
                         completion_tokens=um.get("candidatesTokenCount"),
                         reported_by_provider=True)
        return LLMResponse(text=text, model=self.model_id(), usage=usage,
                           latency_ms=int((time.perf_counter() - t0) * 1000))
