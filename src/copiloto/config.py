"""Configuração central do Copiloto, carregada de variáveis de ambiente/.env."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Mês de referência da demonstração (fixo, independente da data do computador)
REFERENCE_MONTH = "2025-09"
DATA_MONTHS = ["2025-07", "2025-08", "2025-09"]
SEED = 20250901


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COPILOTO_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["none", "ollama", "gemini"] = "none"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    gemini_model: str = "gemini-2.0-flash"

    retrieval_mode: Literal["lexical", "vector", "hybrid"] = "lexical"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    top_k: int = 5

    max_tool_calls: int = 6
    llm_timeout_seconds: int = 120
    approval_ttl_minutes: int = 30

    db_path: Path = Field(default=Path("data/synthetic/copiloto.db"))
    policies_dir: Path = Field(default=Path("data/policies"))
    index_dir: Path = Field(default=Path("data/index"))
    log_dir: Path = Field(default=Path("logs"))

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path)

    @property
    def policies_path(self) -> Path:
        return self.resolve(self.policies_dir)

    @property
    def index_path(self) -> Path:
        return self.resolve(self.index_dir)

    @property
    def log_path(self) -> Path:
        return self.resolve(self.log_dir)


def get_settings() -> Settings:
    return Settings()
