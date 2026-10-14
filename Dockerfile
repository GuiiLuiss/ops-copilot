# Imagem única para API e UI. Sem dependências vetoriais (torch) por padrão:
#   docker build -t ops-copilot .
#   docker build --build-arg EXTRAS="dev,vector" -t ops-copilot:vector .
#
# Execução:
#   docker run -p 8000:8000 ops-copilot                 # API
#   docker run -p 8501:8501 ops-copilot copiloto ui     # UI
# Com Ollama no host: -e COPILOTO_LLM_PROVIDER=ollama -e COPILOTO_OLLAMA_BASE_URL=http://host.docker.internal:11434

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Usuário sem privilégios
RUN groupadd --system app && useradd --system --gid app --create-home app

# Dependências primeiro (cache de camada)
COPY pyproject.toml README.md ./
COPY src ./src
ARG EXTRAS="dev"
RUN pip install -e ".[${EXTRAS}]"

# Dados, políticas e casos de avaliação
COPY data ./data
COPY evals ./evals
COPY scripts ./scripts
COPY tests ./tests

# Gera o banco sintético na build: a imagem já sobe pronta para responder
RUN copiloto generate-data && chown -R app:app /app

USER app

# Diretórios graváveis em runtime
ENV COPILOTO_LOG_DIR=/tmp/copiloto-logs \
    COPILOTO_INDEX_DIR=/tmp/copiloto-index

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/health',timeout=3).status_code==200 else 1)" || exit 1

CMD ["uvicorn", "copiloto.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
