"""Smoke test da interface Streamlit (headless), fluxo principal em modo determinístico."""

import pytest
from streamlit.testing.v1 import AppTest

from copiloto.config import PROJECT_ROOT

APP = PROJECT_ROOT / "src" / "copiloto" / "ui" / "app.py"


@pytest.fixture
def at(monkeypatch, tmp_path, synthetic_db):
    monkeypatch.setenv("COPILOTO_LLM_PROVIDER", "none")
    monkeypatch.setenv("COPILOTO_DB_PATH", str(synthetic_db))
    monkeypatch.setenv("COPILOTO_LOG_DIR", str(tmp_path / "logs"))
    t = AppTest.from_file(str(APP), default_timeout=90)
    t.run()
    assert not t.exception
    return t


def test_ui_loads_with_demo_notice(at):
    captions = " ".join(c.value for c in at.caption)
    assert "Demonstração com dados fictícios" in captions
    assert "não é um login" in captions
    assert "setembro de 2025" in " ".join(m.value for m in at.markdown)


def test_ui_main_flow_and_approval_gate(at):
    at.button(key="ex0").click().run()  # primeira sugestão: cancelamentos no mês
    assert "cancelamentos" in at.text_area(key="question_input").value
    at.button(key="ask_btn").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Resposta" in text and "Ação sugerida" in text
    assert any("Aguardando aprovação" in c.value for c in at.caption)
    assert any("Taxa de cancelamento" in m.label for m in at.metric)
    # analista: sem botão Aprovar, com aviso de perfil
    assert any("perfil de gestor" in i.value for i in at.info)
    assert not [b for b in at.button if b.label == "Aprovar proposta"]


def test_ui_out_of_scope_question(at):
    at.text_area(key="question_input").set_value("Qual a previsão do tempo amanhã?").run()
    at.button(key="ask_btn").click().run()
    assert any("suficientes para responder" in i.value for i in at.info)
