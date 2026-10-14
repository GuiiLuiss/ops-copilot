"""Interface de provedor de LLM. Evita acoplamento a um SDK específico."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reported_by_provider: bool = False  # True se os números vieram do provedor
    estimated: bool = False             # True se foram estimados localmente


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    def generate(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.1, timeout_s: int = 120) -> LLMResponse: ...

    def is_available(self) -> tuple[bool, str]:
        return True, "ok"


class ProviderError(RuntimeError):
    pass


def estimate_tokens(text: str) -> int:
    """Estimativa grosseira (≈4 chars/token). Sempre marcada como estimada."""
    return max(1, len(text) // 4)
