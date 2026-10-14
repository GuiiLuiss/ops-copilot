"""Fixtures e utilitários compartilhados pelos testes."""

from __future__ import annotations

from pathlib import Path

import pytest

from copiloto.agents.graph import run_agent
from copiloto.config import PROJECT_ROOT, get_settings
from copiloto.data.generate import generate, load_db
from copiloto.providers.base import LLMProvider, LLMResponse, LLMUsage
from copiloto.retrieval.retriever import Retriever

MAIN_Q = "Por que os cancelamentos aumentaram neste mês e quais ações podemos tomar?"


@pytest.fixture(scope="session")
def synthetic_db(tmp_path_factory) -> Path:
    """Banco sintético temporário gerado com a seed fixa."""
    db = tmp_path_factory.mktemp("db") / "copiloto_test.db"
    customers, orders, tickets = generate()
    load_db(customers, orders, tickets, db)
    return db


@pytest.fixture(scope="session")
def settings(tmp_path_factory):
    """Configuração de teste: sem LLM, busca lexical, logs em diretório temporário."""
    logs = tmp_path_factory.mktemp("logs")
    return get_settings().model_copy(update={"retrieval_mode": "lexical", "log_dir": logs,
                                             "llm_provider": "none"})


@pytest.fixture(scope="session")
def retriever(settings):
    return Retriever(settings=settings, policies_dir=PROJECT_ROOT / "data" / "policies")


class FakeLLM(LLMProvider):
    """Provedor falso que devolve sempre o mesmo texto e reporta tokens fixos."""

    name = "fake"

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def model_id(self):
        return "fake/test"

    def generate(self, system, user, *, json_mode=False, temperature=0.1, timeout_s=120):
        self.calls += 1
        return LLMResponse(text=self.text, model=self.model_id(),
                           usage=LLMUsage(10, 5, reported_by_provider=True))


def run_case(q, user, *, settings, retriever, synthetic_db, **kw):
    """Atalho para executar o agente com as fixtures de teste."""
    return run_agent(q, user, settings=settings, retriever=retriever, db_path=synthetic_db, **kw)
