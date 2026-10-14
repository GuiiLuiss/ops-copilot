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


def test_ui_loads_with_demo_warning(at):
    assert any("não é autenticação" in w.value for w in at.warning)
    assert any("determinístico" in m.value for m in at.markdown)


def test_ui_main_flow_and_approval_gate(at):
    at.button(key="ex0").click().run()  # primeiro exemplo = pergunta principal
    assert "cancelamentos" in at.text_input(key="question_input").value
    at.button(key="ask_btn").click().run()
    assert not at.exception, [str(e)[:300] for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Modo determinístico" in text
    assert "awaiting_approval" in text
    assert any("Proposta de ação" in s.value for s in at.subheader)
    # analista: botão Aprovar desabilitado e aviso exibido
    assert any("Somente o papel" in i.value for i in at.info)
