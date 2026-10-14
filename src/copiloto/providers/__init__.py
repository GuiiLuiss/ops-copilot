"""Fábrica de provedores. `none` = modo determinístico, sem inferência de LLM."""

from __future__ import annotations

from copiloto.config import Settings, get_settings
from copiloto.providers.base import LLMProvider, LLMResponse, LLMUsage, ProviderError


def get_provider(settings: Settings | None = None) -> LLMProvider | None:
    s = settings or get_settings()
    if s.llm_provider == "none":
        return None
    if s.llm_provider == "ollama":
        from copiloto.providers.ollama import OllamaProvider

        return OllamaProvider(s.ollama_base_url, s.ollama_model)
    if s.llm_provider == "gemini":
        from copiloto.providers.gemini import GeminiProvider

        return GeminiProvider(s.gemini_model)
    raise ValueError(f"provedor desconhecido: {s.llm_provider}")


__all__ = ["LLMProvider", "LLMResponse", "LLMUsage", "ProviderError", "get_provider"]
